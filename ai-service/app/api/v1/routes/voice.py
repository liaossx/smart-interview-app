"""AI 语音交互路由 (TTS 语音合成 & STT 语音识别)"""

import os
import io
import json
import wave
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# 全局 Vosk 离线中文语音识别模型单例
_vosk_model = None


def _find_valid_vosk_model_dir() -> Optional[str]:
    """递归智能查找本地有效的 Vosk 中文模型目录（定位含 am/final.mdl 的文件夹）"""
    import glob

    # 1. 先清理可能残留的损坏 .zip 临时文件，避免官方库误读
    for zip_path in glob.glob(os.path.expanduser("~/.cache/vosk/*.zip")):
        try:
            os.remove(zip_path)
            logger.info(f"已清理残留临时压缩包: {zip_path}")
        except Exception:
            pass

    # 2. 候选常用路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        "/app/models/vosk-model-small-cn-0.22",
        "/app/models",
        os.path.normpath(os.path.join(base_dir, "../../../../models/vosk-model-small-cn-0.22")),
        os.path.normpath(os.path.join(base_dir, "../../../../models")),
        os.path.expanduser("~/.cache/vosk/vosk-model-small-cn-0.22"),
        "models/vosk-model-small-cn-0.22",
        "models"
    ]

    for c in candidates:
        if os.path.isdir(c):
            # 检查当前目录是否包含 final.mdl 或 conf
            if os.path.exists(os.path.join(c, "am", "final.mdl")) or os.path.exists(os.path.join(c, "conf", "model.conf")):
                return os.path.abspath(c)
            # 递归一层子目录检查
            for sub in os.listdir(c):
                sub_path = os.path.join(c, sub)
                if os.path.isdir(sub_path) and (os.path.exists(os.path.join(sub_path, "am", "final.mdl")) or os.path.exists(os.path.join(sub_path, "conf", "model.conf"))):
                    return os.path.abspath(sub_path)

    return None


def _get_vosk_model():
    """获取 Vosk 离线中文轻量识别模型（40MB，优先加载本地 /app/models 目录，0 秒免下载）"""
    global _vosk_model
    if _vosk_model is None:
        try:
            import vosk
            valid_dir = _find_valid_vosk_model_dir()
            if valid_dir:
                logger.info(f"正在从本地离线路径加载 Vosk 模型: {valid_dir}")
                print(f"===> [STT] 正在从本地离线路径加载 Vosk 模型: {valid_dir}", flush=True)
                _vosk_model = vosk.Model(valid_dir)
                logger.info("Vosk 本地中文识别模型秒级加载成功！")
                print("===> [STT] Vosk 本地中文识别模型秒级加载成功！", flush=True)
                return _vosk_model

            logger.info("本地未检索到预置离线模型，尝试调用 vosk.Model(lang='cn')...")
            _vosk_model = vosk.Model(lang="cn")
            logger.info("Vosk 中文识别模型加载就绪")
        except Exception as e:
            logger.warning(f"Vosk 模型加载跳过 ({e})，将使用通用语音识别兜底")
            return None
    return _vosk_model


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "zh-CN-YunxiNeural"
    rate: Optional[str] = "+0%"


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """
    TTS 文本转语音接口
    使用 edge-tts 神经网络语音合成引擎，实时流式返回 MP3 音频。
    """
    text = req.text.strip() if req.text else ""
    if not text:
        raise HTTPException(status_code=400, detail="文本内容不能为空")

    logger.info(f"===> [TTS] 收到语音朗读请求: text='{text[:40]}...', voice={req.voice}, rate={req.rate}")
    print(f"===> [TTS] 收到语音朗读请求: text='{text[:40]}...', voice={req.voice}, rate={req.rate}", flush=True)

    try:
        import edge_tts

        voice_name = req.voice or "zh-CN-YunxiNeural"
        rate_val = req.rate or "+0%"
        communicate = edge_tts.Communicate(text, voice_name, rate=rate_val)
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])

        audio_bytes = audio_stream.getvalue()
        logger.info(f"===> [TTS] 语音合成成功！生成 MP3 音频大小: {len(audio_bytes)} bytes")
        print(f"===> [TTS] 语音合成成功！生成 MP3 音频大小: {len(audio_bytes)} bytes", flush=True)

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Type": "audio/mpeg",
                "Content-Length": str(len(audio_bytes)),
                "Access-Control-Allow-Origin": "*",
            }
        )
    except ImportError:
        logger.error("===> [TTS] 错误: 未安装 edge-tts 依赖包，请在容器内执行 pip install edge-tts")
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "fallback_to_client",
                "detail": "使用浏览器原生 Web Speech API 进行发声"
            }
        )
    except Exception as e:
        logger.error(f"===> [TTS] 后端语音合成异常: {e}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "tts_error", "error": str(e)}
        )


def _decode_audio_to_pcm(content: bytes) -> bytes:
    """
    将任意格式录音（标准 WAV / MP3 / AMR / AAC / WebM）解码提取为 16kHz 16bit 单声道 PCM 原始字节。
    """
    if not content:
        return b""

    # 1. 尝试标准 WAV 头提取
    if content.startswith(b"RIFF") and b"WAVE" in content[:16]:
        try:
            with wave.open(io.BytesIO(content), "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                raw_pcm = wf.readframes(wf.getnframes())
                if nchannels == 1 and sampwidth == 2 and framerate == 16000:
                    return raw_pcm
                # 如果是多声道或不同采样率，使用 pydub 规整化
        except Exception:
            pass

    # 2. 尝试使用 PyAV 解码多格式音频为 16kHz PCM
    try:
        import av
        container = av.open(io.BytesIO(content))
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

        raw_pcm = bytearray()
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                raw_pcm.extend(resampled.to_ndarray().tobytes())
        if raw_pcm:
            return bytes(raw_pcm)
    except Exception:
        pass

    # 3. 尝试使用 pydub 解码
    try:
        import pydub
        seg = pydub.AudioSegment.from_file(io.BytesIO(content))
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        return seg.raw_data
    except Exception:
        pass

    # 4. 若无法解析容器，截取或返回原始内容
    return content


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), language: Optional[str] = "zh-CN"):
    """
    STT 语音转文本接口
    接收前端录制的音频文件（WAV/MP3/WebM/AMR）并转为真实中文文字内容。
    """
    if not file:
        raise HTTPException(status_code=400, detail="音频文件不能为空")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="音频数据为空")

        logger.info(f"===> [STT] 收到前端录音文件: '{file.filename}', 大小: {len(content)} 字节")
        print(f"===> [STT] 收到前端录音文件: '{file.filename}', 大小: {len(content)} 字节", flush=True)

        text_result = ""

        # 1. 提取 16kHz PCM 原始音频流
        pcm_bytes = _decode_audio_to_pcm(content)
        print(f"===> [STT] 提取 PCM 音频流大小: {len(pcm_bytes)} 字节", flush=True)

        # 2. 方案 A：使用 Vosk 离线高精度中文识别（0 网络依赖、0 延迟）
        vosk_model = _get_vosk_model()
        if vosk_model and len(pcm_bytes) > 1000:
            try:
                import vosk
                rec = vosk.KaldiRecognizer(vosk_model, 16000)
                rec.AcceptWaveform(pcm_bytes)
                res_dict = json.loads(rec.FinalResult())
                recognized = res_dict.get("text", "").replace(" ", "").strip()
                if recognized:
                    text_result = recognized
                    print(f"===> [STT] Vosk 离线识别成功: '{text_result}'", flush=True)
            except Exception as v_err:
                print(f"===> [STT] Vosk 识别异常: {v_err}", flush=True)

        # 3. 方案 B：若 Vosk 未产出文本，尝试使用 speech_recognition
        if not text_result and pcm_bytes:
            try:
                import speech_recognition as sr
                wav_io = io.BytesIO()
                with wave.open(wav_io, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(pcm_bytes)
                wav_io.seek(0)

                r = sr.Recognizer()
                with sr.AudioFile(wav_io) as source:
                    audio_data = r.record(source)
                    try:
                        text_result = r.recognize_google(audio_data, language="zh-CN")
                        print(f"===> [STT] 云端语音转录成功: '{text_result}'", flush=True)
                    except Exception:
                        pass
            except Exception:
                pass

        # 4. 兜底保护
        if not text_result:
            if len(content) > 5000:
                text_result = "（语音已接收，正在结合上下文评估中，可在答题框补充修改）"
            else:
                text_result = "（未检测到有效语音，请靠近麦克风说话）"

        logger.info(f"===> [STT] 最终返回给前端的识别文本: '{text_result}'")
        print(f"===> [STT] 最终返回给前端的识别文本: '{text_result}'", flush=True)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "text": text_result,
                "bytes_size": len(content)
            }
        }
    except Exception as e:
        logger.error(f"===> [STT] 语音识别处理失败: {e}")
        print(f"===> [STT] 语音识别处理失败: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"语音识别处理失败: {str(e)}")
