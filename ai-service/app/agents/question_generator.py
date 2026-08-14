"""出题 Agent —— AI 链路分析管线的最后一个节点

本模块根据 JD 分析、简历分析和差距分析的结果，生成 8-12 道面试题目。
它是分析管线的终点（question_generator → END），生成的题目将驱动后续的 Q&A 交互。

核心设计要点：
1. 题目分类分配策略（40/30/20/10）：
   - 40% 技术基础题（八股文）：根据 JD 技术栈出题，如"HashMap 原理""MySQL 索引"
   - 30% 项目深挖题：根据简历项目出题，考察候选人真实经历和深度理解
   - 20% 场景设计题：结合 JD 业务场景，考察架构思维和方案设计能力
   - 10% 软技能题：考察沟通、团队协作、学习能力等非技术维度
   这个比例确保面试既考察基础功底，又考察实战能力和综合素质。

2. 公司规模难度调整：
   - 大厂：hard 40% / medium 50% / easy 10% → 重底层原理、系统设计、算法思维
   - 中型公司：hard 20% / medium 60% / easy 20% → 重框架实战、业务理解、问题排查
   - 创业公司：hard 10% / medium 50% / easy 40% → 重全栈能力、解决问题、实战经验
   公司规模来自 jd_analysis 中的 company_scale 字段，由 JD 分析节点判断。

3. 使用 get_creative_llm()（高温度 0.8）：
   出题是创意生成任务，高温度增加题目表述和考察角度的多样性，
   避免同一岗位每次面试都出相同的题目。

4. reference_answer 设计（四类区别对待）：
   - 技术基础（八股文）：完整 200-500 字参考答案，作为面试标准答案供候选人学习
   - 项目深挖：留空字符串，候选人的项目经历各不相同，无标准答案
   - 场景设计：留空字符串，设计方案因人而异，考察的是思路而非固定答案
   - 软技能：给出示例性参考答案，让候选人了解什么样的回答是高质量的

5. expected_answer_points 设计（四类区别对待）：
   - 技术基础：覆盖参考答案的核心知识点，要点 = 答案的知识骨架
   - 项目深挖：基于简历分析中该候选人的具体项目信息（tech_stack、highlights、项目角色）
     来定制要点，每个要点必须引用具体的项目名、技术栈或业务场景，引导候选人展开真实项目细节。
     禁止使用泛化表述如"项目背景清晰""明确个人职责"，务必具体到项目细节
   - 场景设计：列出关键的架构决策点和设计权衡（选型理由、数据一致性方案、高并发策略等）
   - 软技能：列出高质量回答应覆盖的维度，引导候选人用 STAR 原则结构化表达

详见 AI链路学习路径.md 第6步（出题节点）
"""

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from app.core.llm import get_creative_llm
from app.agents.state import InterviewState
from app.core.rag_engine import retrieve_resume_context
import json
import logging

logger = logging.getLogger(__name__)


# ---- System Prompt 设计 ----
# 这是整个 AI 链路中最复杂的 Prompt，包含四部分关键指令：
# 1. 公司规模出题风格规则：定义大厂/中型/创业公司各自的出题侧重点和难度比例
# 2. JSON 输出 schema：定义题目结构，含 category/question/difficulty/参考答案等
# 3. reference_answer 和 expected_answer_points 的按类别差异化规则
# 4. 题目分配建议：40%技术基础 + 30%项目深挖 + 20%场景设计 + 10%软技能
SYSTEM_PROMPT = """你是一位亲切、专业、充满真实交流感的资深技术 Leader 面试官。根据 JD 要求、候选人简历和差距分析，生成 8-12 道面试题。

【核心要求：完全拟真人类面对面口语化与语音呼吸感】
所有的题目文本未来会被 TTS 语音合成引擎朗读出来。因此题目的语言风格必须 100% 像一位温和有耐心的资深技术专家坐在对面轻松交流，彻底杜绝任何机械试卷感！

【1. 禁令与口语转换规则】
❌ 绝对禁止使用：“请简述……”、“请阐述……”、“谈谈……的定义”、“请列举……的特性”等刻板试卷用语。
✅ 强制采用口语交流句式：
- “咱们先从基础聊起——你平时开发肯定常用……，能跟我聊聊它底层主要机制是怎样的吗？”
- “我看你简历里做过……项目，当时在实际高并发场景下，你是怎么保证……的？中间有没有遇到什么挑战？”
- “那咱们换个场景来看看：如果让你负责……模块的设计，你通常会如何权衡？”
- “在团队协作或者技术选型发生分歧时，你一般会怎样推进？”

【2. TTS 语音断句与发音节奏（呼吸感）】
- 单句长度控制在 25 字以内，善用逗号“，”或破折号“——”进行自然停顿，让语音朗读时有呼吸节奏，不紧迫、不单调；
- 适当融入自然的口语语气词（“对吧”、“呢”、“具体是怎样”），增强互动亲和力。

【3. 题目按面试推进阶段自然承接（Stage Progression）】
- 第 1 题（破冰暖场）：“你好！欢迎参加今天的面试，不用紧张，咱们先从一些 Java 核心基础轻松聊起……”
- 第 2~3 题（基础拓展）：“挺好的！那咱们顺着这个思路再往下看一个高频技术点……”
- 第 4~6 题（项目深挖）：“我看你的项目经历里写到了……，当时在实际落地时……”（必须结合简历具体项目名/技术栈）
- 第 7~8 题（场景设计）：“那咱们换一个实际的架构场景来看看……”
- 最后一题（综合收尾）：“技术细节聊得很扎实，最后想跟你探讨一个关于技术成长或团队协作的小话题……”

公司规模决定了出题风格，必须严格遵守以下规则：

【大厂出题风格】
- 重底层原理：结合场景问底层实现原理与设计权衡（如 HashMap 底层、JVM 垃圾回收、线程池参数）
- 重系统设计：考察分布式系统架构与可用性权衡
- 重算法思维：时间/空间复杂度分析、高并发与缓存策略
- 题目深度：hard 占 40%，medium 占 50%，easy 占 10%

【中型公司出题风格】
- 重框架实战：Spring Boot 自动配置机制、MyBatis / Redis 线上实战
- 重业务理解：结合业务场景的技术方案落地
- 重问题排查：“在线上如果遇到慢 SQL 或内存溢出，你平时的排查思路是怎样的？”
- 题目深度：hard 占 20%，medium 占 60%，easy 占 20%

【创业公司出题风格】
- 重全栈能力与落地：CRUD 之外的技术深度与技术选型能力
- 重解决问题：“如果让你从零搭建这个微服务架构，你的技术选型思路是什么？”
- 重实战经验：能否快速上手并解决实际业务痛点
- 题目深度：hard 占 10%，medium 占 50%，easy 占 40%

以 JSON 格式返回题目列表：
{
  "questions": [
    {
      "id": 1,
      "category": "技术基础/项目经验/场景设计/软技能",
      "question": "口语化、亲切自然且带阶段承接的题目内容",
      "purpose": "考察什么能力",
      "difficulty": "easy/medium/hard",
      "expected_answer_points": ["见下方规则"],
      "reference_answer": "见下方规则"
    }
  ]
}

==== reference_answer 规则（按 category 区分）====

【技术基础】必须填写完整的参考答案，200-500 字，作为面试标准答案供候选人学习：
- 用清晰的分点或段落阐述核心概念、原理、关键步骤
- 覆盖 expected_answer_points 中的所有要点并展开
- 语言专业但不晦涩，让候选人读完能真正理解这个知识点

【项目经验】必须留空字符串 "" —— 候选人的项目经历各不相同，无标准答案

【场景设计】必须留空字符串 "" —— 设计方案因人而异，没有唯一正确答案

【软技能】填写一段示例性参考答案（100-200 字），展示高质量回答的结构和深度：
- 用 STAR 原则（情境-任务-行动-结果）组织
- 让候选人明白这类开放题应该如何回答

==== expected_answer_points 规则（按 category 区分）====

【技术基础】要点 = 参考答案的知识骨架，列出 3-5 个必须覆盖的核心知识点

【项目经验】要点必须来自简历分析中该候选人的具体项目信息：
- 每个要点必须引用简历分析里的具体项目名、技术栈或项目亮点（highlights）
- 引导候选人展开真实项目细节，例如：
  - "订单系统从单体拆分微服务时，如何保证数据一致性"（引用简历中的项目名和 tech_stack）
  - "项目中 Redis 缓存与 DB 的读写一致性方案"（引用简历中具体使用的技术）
- 严禁使用泛化表述如"项目背景和业务目标清晰"、"明确个人职责"等

【场景设计】列出 3-5 个关键的架构决策点和设计权衡：
- 如"选型理由及替代方案对比"、"数据一致性保证"、"高并发下的性能优化策略"
- 考察候选人做 trade-off 的能力

【软技能】列出高质量回答应覆盖的维度：
- 如"使用了 STAR 原则"、"有具体案例和数据支撑"、"展示了自我反思"

==== 题目分配 ====
- 40% 技术基础题（根据 JD 技术栈）
- 30% 项目深挖题（根据简历项目）
- 20% 场景设计题（结合 JD 业务场景）
- 10% 软技能题

只返回 JSON。"""


def create_question_generator():
    """
    创建出题 ReAct Agent。

    使用 get_creative_llm()（高温度 0.8）：出题是创意生成任务，
    高温度让 LLM 生成更多样的题目表述和考察角度。
    这是整个链路中唯一使用高温度的节点，其他分析节点都用低温度。
    """
    return create_agent(
        model=get_creative_llm(),
        tools=[],
        name="question_generator",
        system_prompt=SYSTEM_PROMPT,
    )


# 单例 Agent 实例（懒加载）
_question_agent = None


def _get_question_generator():
    """获取出题 Agent 单例（懒加载模式）"""
    global _question_agent
    if _question_agent is None:
        _question_agent = create_question_generator()
    return _question_agent


def question_generator_node(state: InterviewState) -> InterviewState:
    """
    RAG-enhanced question generator node.

    Adds RAG context injection before question generation:
    1. Extracts JD focus topics (tech_stack + missing_skills + common backend topics)
    2. Queries the session Chroma vector DB for matching resume project snippets
    3. Injects retrieved snippets into the prompt for targeted project deep-dive questions
    4. Falls back gracefully if no RAG data is available
    """
    session_id = state.get("session_id", "")

    # RAG: retrieve relevant resume context for project deep-dive questions
    rag_context_lines = []
    try:
        jd_analysis = state.get("jd_analysis", {})
        gap_analysis = state.get("gap_analysis", {})

        query_topics = []
        tech_stack = jd_analysis.get("tech_stack", [])
        if isinstance(tech_stack, list):
            query_topics.extend(tech_stack[:4])
        missing_skills = gap_analysis.get("missing_skills", [])
        if isinstance(missing_skills, list):
            query_topics.extend(missing_skills[:3])
        query_topics.extend(["高并发", "分布式", "缓存"])

        seen = set()
        unique_topics = [t for t in query_topics if t and t not in seen and not seen.add(t)]

        for topic in unique_topics[:6]:
            snippet = retrieve_resume_context(session_id, topic, top_k=1, min_similarity=0.35)
            if snippet:
                rag_context_lines.append(f"[\xe8\x80\x83\xe7\x82\xb9: {topic}]\n{snippet}")

    except Exception as e:
        logger.warning(f"Session {session_id}: RAG retrieval failed ({e}), using fallback mode")

    jd_json = json.dumps(state.get("jd_analysis", {}), ensure_ascii=False, indent=2)
    resume_json = json.dumps(state.get("resume_analysis", {}), ensure_ascii=False, indent=2)
    gap_json = json.dumps(state.get("gap_analysis", {}), ensure_ascii=False, indent=2)

    input_text = f"JD \xe5\x88\x86\xe6\x9e\x90: {jd_json}\n\n\xe7\xae\x80\xe5\x8e\x86\xe5\x88\x86\xe6\x9e\x90: {resume_json}\n\n\xe5\xb7\xae\xe8\xb7\x9d\xe5\x88\x86\xe6\x9e\x90: {gap_json}\n"

    if rag_context_lines:
        rag_block = "\n\n".join(rag_context_lines)
        rag_note = (
            "\n\n[RAG \xe7\xae\x80\xe5\x8e\x86\xe8\xaf\xad\xe4\xb9\x89\xe6\xa3\x80\xe7\xb4\xa2\xe7\xbb\x93\xe6\x9e\x9c -- \xe9\xa1\xb9\xe7\x9b\xae\xe6\xb7\xb1\xe6\x8c\x96\xe5\x8f\x82\xe8\x80\x83]\n"
            "\xe4\xbb\xa5\xe4\xb8\x8b\xe6\x98\xaf\xe4\xbb\x8e\xe5\x80\x99\xe9\x80\x89\xe4\xba\xba\xe7\xae\x80\xe5\x8e\x86\xe8\xaf\xad\xe4\xb9\x89\xe6\xa3\x80\xe7\xb4\xa2\xe5\x88\xb0\xe7\x9a\x84\xe6\x9c\x80\xe7\x9b\xb8\xe5\x85\xb3\xe9\xa1\xb9\xe7\x9b\xae\xe7\x89\x87\xe6\xae\xb5\xef\xbc\x8c\xe5\x9c\xa8\xe7\x94\x9f\xe6\x88\x90\xe9\xa1\xb9\xe7\x9b\xae\xe6\xb7\xb1\xe6\x8c\x96\xe9\xa2\x98\xe6\x97\xb6\xe5\xbf\x85\xe9\xa1\xbb\xe5\x8f\x82\xe8\x80\x83\xe8\xbf\x99\xe4\xba\x9b\xe7\x9c\x9f\xe5\xae\x9e\xe9\xa1\xb9\xe7\x9b\xae\xe4\xb8\xad\xe7\x9a\x84\xe5\x85\xb7\xe4\xbd\x93\xe6\x8a\x80\xe6\x9c\xaf\xe7\xbb\x86\xe8\x8a\x82\xe8\xbf\x9b\xe8\xa1\x8c\xe5\xae\x9a\xe5\x88\xb6\xe5\x8c\x96\xe6\xb7\xb1\xe6\x8c\x96\xe9\x97\xae\xe9\xa2\x98\xef\xbc\x9a\n\n"
        )
        input_text += rag_note + rag_block
        logger.info(f"Session {session_id}: RAG injected {len(rag_context_lines)} snippets into prompt")
    else:
        logger.info(f"Session {session_id}: No RAG context, using standard mode")

    agent = _get_question_generator()
    result = agent.invoke({"messages": [HumanMessage(content=input_text)]})

    try:
        data = json.loads(result["messages"][-1].content)
        questions = data.get("questions", [])
    except (json.JSONDecodeError, KeyError):
        questions = []

    return {
        **state,
        "questions": questions,
        "current_question_index": 0,
        "phase": "questions_ready",
    }
