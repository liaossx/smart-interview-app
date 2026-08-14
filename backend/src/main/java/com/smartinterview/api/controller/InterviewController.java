package com.smartinterview.api.controller;

import com.smartinterview.data.entity.JD;
import com.smartinterview.data.entity.QA;
import com.smartinterview.data.entity.Resume;
import com.smartinterview.data.entity.Session;
import com.smartinterview.data.repository.JDRepository;
import com.smartinterview.data.repository.QARepository;
import com.smartinterview.data.repository.ResumeRepository;
import com.smartinterview.data.repository.SessionRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.CompletableFuture;

import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 面试流程控制器 —— Java 与 Python AI 服务之间的桥接层（代理层）。
 * <p>
 * 本控制器不直接处理 AI 逻辑，而是将前端请求转发给 Python AI 服务（FastAPI）。
 * 架构链路：前端 → InterviewController（Java）→ Python AI Service（FastAPI）
 * <p>
 * 职责：
 * <ul>
 *   <li>从数据库读取面试会话状态（JD、简历、QA 列表），直接返回给前端</li>
 *   <li>将面试核心流程（开始面试、提交回答、恢复面试、获取结果）代理转发至 Python AI 服务</li>
 *   <li>将简历文件转发给 Python 端进行解析</li>
 * </ul>
 * <p>
 * 注意：当前使用 RestTemplate 进行同步 HTTP 转发，不支持 SSE 流式传输。
 * 若未来需要流式 AI 回复，需改用 WebClient 或手动写入 SseEmitter。
 * <p>
 * 详见 AI链路学习路径.md 第八步
 */
@RestController
@RequestMapping("/api/v1")
public class InterviewController {

    /** 用于向 Python AI 服务发起 HTTP 请求的同步客户端 */
    private final RestTemplate restTemplate;
    private final SessionRepository sessionRepository;
    private final JDRepository jdRepository;
    private final ResumeRepository resumeRepository;
    private final QARepository qaRepository;
    /** Python AI 服务的基础 URL，来自配置项 ai.service-url，默认指向本地 FastAPI 实例 */
    private final String aiBaseUrl;

    /**
     * 构造函数，初始化 RestTemplate 并注入各 Repository。
     *
     * @param aiBaseUrl 配置项 {@code ai.service-url}，指向 Python AI 服务地址。
     *                  开发环境默认为 http://127.0.0.1:8001/api/v1
     */
    public InterviewController(SessionRepository sessionRepository, JDRepository jdRepository,
                               ResumeRepository resumeRepository, QARepository qaRepository,
                               @Value("${ai.service-url:http://127.0.0.1:8001/api/v1}") String aiBaseUrl) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);   // 连接超时 5 秒：快速失败，避免长时间等待 Python 服务启动
        factory.setReadTimeout(60000);     // 读取超时 60 秒：LLM 推理耗时较长（生成面试问题、评分反馈），需留足等待时间
        this.restTemplate = new RestTemplate(factory);
        this.sessionRepository = sessionRepository;
        this.jdRepository = jdRepository;
        this.resumeRepository = resumeRepository;
        this.qaRepository = qaRepository;
        this.aiBaseUrl = aiBaseUrl;
    }

    /**
     * 获取面试会话状态（不经过 Python，直接读数据库）。
     * 前端用于恢复页面状态：JD 内容、简历文本、已有 QA 列表、题目列表等。
     * 此接口纯 Java 侧实现，无需调用 AI 服务。
     */
    @GetMapping("/interview/state/{sessionId}")
    public ResponseEntity<?> getSessionState(@PathVariable Long sessionId, HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        Session session = sessionRepository.findById(sessionId).orElse(null);
        if (session == null || !session.getUserId().equals(userId)) {
            return ResponseEntity.status(404).body("{\"code\":404,\"message\":\"会话不存在\",\"data\":null}");
        }

        Map<String, Object> state = new LinkedHashMap<>();
        state.put("sessionId", session.getId());
        state.put("status", session.getStatus().name());

        // JD content
        if (session.getJdId() != null) {
            jdRepository.findById(session.getJdId())
                    .ifPresent(jd -> state.put("jdContent", jd.getContent()));
        }

        // Resume parsed text
        if (session.getResumeId() != null) {
            resumeRepository.findById(session.getResumeId())
                    .ifPresent(resume -> state.put("resumeContent",
                            resume.getParsedText() != null ? resume.getParsedText() : ""));
        }

        // QA list
        List<QA> qas = qaRepository.findBySessionIdOrderByCreatedAtAsc(sessionId);
        List<Map<String, Object>> qaList = new ArrayList<>();
        for (QA qa : qas) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("question", qa.getQuestion());
            m.put("category", qa.getCategory());
            m.put("answer", qa.getAnswer());
            m.put("score", qa.getScore());
            m.put("feedback", qa.getFeedback());
            m.put("followUpQuestion", qa.getFollowUpQuestion());
            qaList.add(m);
        }
        state.put("qas", qaList);
        state.put("currentQuestionIndex", qas.size());

        // Questions list (saved when interview started)
        String questionsJson = session.getQuestionsJson();
        if (questionsJson != null && !questionsJson.isEmpty()) {
            try {
                ObjectMapper mapper = new ObjectMapper();
                state.put("questions", mapper.readTree(questionsJson));
            } catch (Exception e) {
                state.put("questions", null);
            }
        } else {
            state.put("questions", null);
        }

        return ResponseEntity.ok(state);
    }

    /**
     * 恢复面试会话 —— 代理转发至 Python AI 服务的 /interview/restore 接口。
     * Python 端会根据会话历史重建对话上下文（LLM memory）。
     */
    @PostMapping("/interview/restore")
    public ResponseEntity<?> restoreInterview(@RequestBody Map<String, Object> body,
                                              HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        body.put("user_id", userId);
        return proxy(aiBaseUrl + "/interview/restore", HttpMethod.POST, body, null);
    }

    /**
     * 开始面试 —— 代理转发至 Python AI 服务的 /interview/start 接口。
     * Python 端会根据 JD + 简历，调用 LLM 生成面试题目列表。
     */
    @PostMapping("/interview/start")
    public ResponseEntity<?> startInterview(@RequestBody Map<String, Object> body,
                                            HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        body.put("user_id", userId);
        return proxy(aiBaseUrl + "/interview/start", HttpMethod.POST, body, null);
    }

    /**
     * 开始面试（SSE 流式）—— 实时推送分析进度。
     * <p>
     * 返回 SseEmitter 保持 HTTP 连接打开，异步线程连接 Python /stream 端点，
     * 逐行读取 SSE 流并转发给前端。前端可实时看到"正在分析职位描述..."等进度事件。
     * <p>
     * 事件序列：progress(jd_analysis) → progress(jd_analysis_done) → progress(resume_analysis_done)
     *           → progress(gap_analysis_done) → progress(questions_ready) → complete(完整结果)
     */
    @PostMapping("/interview/start/stream")
    public SseEmitter startInterviewStream(@RequestBody Map<String, Object> body,
                                            HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        body.put("user_id", userId);
        SseEmitter emitter = new SseEmitter(120_000L);

        CompletableFuture.runAsync(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(aiBaseUrl + "/interview/start/stream");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(120_000);
                conn.setDoOutput(true);
                try (var os = conn.getOutputStream()) {
                    new ObjectMapper().writeValue(os, body);
                }

                int status = conn.getResponseCode();
                if (status != 200) {
                    emitter.send(SseEmitter.event().name("error")
                            .data("{\"message\":\"AI服务返回错误: " + status + "\"}"));
                    emitter.complete();
                    return;
                }

                try (var reader = new java.io.BufferedReader(new java.io.InputStreamReader(
                        conn.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    StringBuilder eventData = new StringBuilder();
                    String eventType = "message";
                    while ((line = reader.readLine()) != null) {
                        if (line.startsWith("event: ")) {
                            eventType = line.substring(7);
                        } else if (line.startsWith("data: ")) {
                            eventData.append(line.substring(6));
                        } else if (line.isEmpty() && eventData.length() > 0) {
                            emitter.send(SseEmitter.event()
                                    .name(eventType)
                                    .data(eventData.toString(), MediaType.APPLICATION_JSON));
                            eventData.setLength(0);
                            eventType = "message";
                        }
                    }
                }
                emitter.complete();
            } catch (Exception e) {
                try { emitter.send(SseEmitter.event().name("error")
                        .data("{\"message\":\"AI服务不可用\"}")); } catch (Exception ignored) {}
                emitter.complete();
            } finally {
                if (conn != null) conn.disconnect();
            }
        });

        emitter.onTimeout(() -> System.err.println("[SSE] start stream timeout"));
        emitter.onCompletion(() -> System.out.println("[SSE] start stream completed"));
        return emitter;
    }

    /**
     * 提交回答 —— 代理转发至 Python AI 服务的 /interview/answer 接口。
     * Python 端会调用 LLM 对用户回答进行评分 + 生成反馈 + 决定追问。
     */
    @PostMapping("/interview/answer")
    public ResponseEntity<?> submitAnswer(@RequestBody Map<String, Object> body,
                                          HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        body.put("user_id", userId);
        return proxy(aiBaseUrl + "/interview/answer", HttpMethod.POST, body, null);
    }

    /**
     * 提交回答（SSE 流式）—— 实时推送评分进度。
     * <p>
     * 事件序列：progress(scoring, "正在评分...") → scored(评分结果，面试继续) 或 complete(面试结束)
     */
    @PostMapping("/interview/answer/stream")
    public SseEmitter submitAnswerStream(@RequestBody Map<String, Object> body,
                                          HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        body.put("user_id", userId);
        String sessionId = (String) body.get("session_id");
        SseEmitter emitter = new SseEmitter(120_000L);

        CompletableFuture.runAsync(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(aiBaseUrl + "/interview/answer/stream");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(120_000);
                conn.setDoOutput(true);
                try (var os = conn.getOutputStream()) {
                    new ObjectMapper().writeValue(os, body);
                }

                int status = conn.getResponseCode();
                if (status != 200) {
                    emitter.send(SseEmitter.event().name("error")
                            .data("{\"message\":\"AI服务返回错误: " + status + "\"}"));
                    emitter.complete();
                    return;
                }

                try (var reader = new java.io.BufferedReader(new java.io.InputStreamReader(
                        conn.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    StringBuilder eventData = new StringBuilder();
                    String eventType = "message";
                    while ((line = reader.readLine()) != null) {
                        if (line.startsWith("event: ")) {
                            eventType = line.substring(7);
                        } else if (line.startsWith("data: ")) {
                            eventData.append(line.substring(6));
                        } else if (line.isEmpty() && eventData.length() > 0) {
                            emitter.send(SseEmitter.event()
                                    .name(eventType)
                                    .data(eventData.toString(), MediaType.APPLICATION_JSON));
                            eventData.setLength(0);
                            eventType = "message";
                        }
                    }
                }
                emitter.complete();
            } catch (Exception e) {
                try { emitter.send(SseEmitter.event().name("error")
                        .data("{\"message\":\"AI服务不可用\"}")); } catch (Exception ignored) {}
                emitter.complete();
            } finally {
                if (conn != null) conn.disconnect();
            }
        });

        emitter.onTimeout(() -> System.err.println("[SSE] answer stream timeout"));
        emitter.onCompletion(() -> System.out.println("[SSE] answer stream completed"));
        return emitter;
    }

    /**
     * 获取面试结果报告 —— 代理转发至 Python AI 服务的 /interview/result/{sessionId} 接口。
     * Python 端汇总全部 QA 评分，调用 LLM 生成综合评价报告。
     */
    @GetMapping("/interview/result/{sessionId}")
    public ResponseEntity<?> getResult(@PathVariable String sessionId,
                                       HttpServletRequest req) {
        Long userId = (Long) req.getAttribute("userId");
        String url = aiBaseUrl + "/interview/result/" + sessionId + "?user_id=" + userId;
        return proxy(url, HttpMethod.GET, null, null);
    }

    /**
     * 简历解析 —— 将上传的文件以 multipart 形式转发至 Python AI 服务的 /resume/parse 接口。
     * Python 端使用 OCR / 文本提取 + LLM 结构化解析，返回 JSON 格式的简历字段。
     * 注意：此处未走通用 proxy() 方法，因为需要处理 multipart 请求体。
     */
    @PostMapping("/resume/parse")
    public ResponseEntity<?> parseResume(@RequestParam("file") MultipartFile file,
                                         HttpServletRequest req) {
        try {
            var headers = new HttpHeaders();
            headers.setContentType(MediaType.MULTIPART_FORM_DATA);

            var body = new org.springframework.util.LinkedMultiValueMap<String, Object>();
            body.add("file", file.getResource());

            var entity = new HttpEntity<>(body, headers);
            var resp = restTemplate.exchange(aiBaseUrl + "/resume/parse", HttpMethod.POST, entity, String.class);
            return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
        } catch (Exception e) {
            return ResponseEntity.status(502).body(
                    "{\"code\":502,\"message\":\"AI service unavailable\",\"data\":null}");
        }
    }

    /**
     * TTS 语音合成接口代理 —— 转发至 Python AI 服务的 /voice/tts 接口
     */
    @PostMapping("/voice/tts")
    public ResponseEntity<?> voiceTts(@RequestBody Map<String, Object> reqBody) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(reqBody, headers);
            ResponseEntity<byte[]> resp = restTemplate.exchange(
                    aiBaseUrl + "/voice/tts",
                    HttpMethod.POST,
                    entity,
                    byte[].class
            );
            HttpHeaders respHeaders = new HttpHeaders();
            if (resp.getHeaders().getContentType() != null) {
                respHeaders.setContentType(resp.getHeaders().getContentType());
            } else {
                respHeaders.setContentType(MediaType.valueOf("audio/mpeg"));
            }
            return new ResponseEntity<>(resp.getBody(), respHeaders, resp.getStatusCode());
        } catch (Exception e) {
            return ResponseEntity.status(500).body("{\"code\":500,\"message\":\"语音合成服务暂不可用\"}");
        }
    }

    /**
     * 通用代理方法：将请求转发至 Python AI 服务，并原样返回响应。
     * <p>
     * 逻辑：
     * <ol>
     *   <li>构造 JSON 请求头，可选附加额外头</li>
     *   <li>使用 RestTemplate 发起同步 HTTP 请求</li>
     *   <li>透传 Python 返回的状态码和响应体</li>
     *   <li>若 Python 服务不可达或超时，返回 502 Bad Gateway</li>
     * </ol>
     * <p>
     * 注意：RestTemplate 是同步阻塞客户端，不支持 SSE 流式传输。
     * 当前所有 AI 接口均以 JSON 请求/响应模式工作。
     * 若后续需要流式回复（如逐字输出 LLM 回答），需改用 WebClient 或 SseEmitter。
     *
     * @param url          目标 Python AI 服务 URL
     * @param method       HTTP 方法（GET / POST 等）
     * @param body         请求体，null 表示无请求体
     * @param extraHeaders 额外请求头，null 表示无
     * @return 透传的 Python 响应，或 502 错误
     */
    private ResponseEntity<?> proxy(String url, HttpMethod method, Object body, HttpHeaders extraHeaders) {
        try {
            var headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (extraHeaders != null) headers.addAll(extraHeaders);

            var entity = body != null ? new HttpEntity<>(body, headers) : new HttpEntity<>(headers);
            var resp = restTemplate.exchange(url, method, entity, String.class);
            // 透传 Python 服务返回的状态码与响应体
            return ResponseEntity.status(resp.getStatusCode()).body(resp.getBody());
        } catch (Exception e) {
            // Python 服务不可达 / 超时 / 连接拒绝 → 返回 502，前端据此提示"AI 服务不可用"
            System.err.println("[proxy] ERROR calling " + url + ": " + e.getClass().getSimpleName() + " - " + e.getMessage());
            return ResponseEntity.status(502).body(
                    "{\"code\":502,\"message\":\"AI service unavailable\",\"data\":null}");
        }
    }
}
