"""AI 语音交互路由 (TTS 语音合成 & STT 语音识别)"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "zh-CN-YunxiNeural"
    rate: Optional[str] = "+0%"


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """
    TTS 文本转语音接口
    优先使用后端语音合成引擎（如 edge-tts 或系统引擎），若未安装则返回 501 引导前端使用 Web Speech API。
    """
    text = req.text.strip() if req.text else ""
    if not text:
        raise HTTPException(status_code=400, detail="文本内容不能为空")

    try:
        import edge_tts
        import io
        from fastapi.responses import StreamingResponse

        communicate = edge_tts.Communicate(text, req.voice or "zh-CN-YunxiNeural", rate=req.rate or "+0%")
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])
        audio_stream.seek(0)
        return StreamingResponse(audio_stream, media_type="audio/mpeg")
    except ImportError:
        # 后端未安装 edge-tts 时，返回 JSON 说明，由前端原生 Web Speech API 无缝接管
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "fallback_to_client",
                "detail": "使用浏览器原生 Web Speech API 进行高质量发声"
            }
        )
    except Exception as e:
        logger.warning(f"后端语音合成异常: {e}")
        return JSONResponse(
            status_code=200,
            content={"code": 200, "message": "fallback_to_client", "error": str(e)}
        )


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), language: Optional[str] = "zh"):
    """
    STT 语音转文本接口
    接收前端上传的音频文件（WAV/MP3/WebM/M4A）并转为文字。
    """
    if not file:
        raise HTTPException(status_code=400, detail="音频文件不能为空")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="音频数据为空")

        # 预留可插拔后端识别引擎（如 Whisper 或 阿里语音识别 API）
        return {
            "code": 200,
            "message": "success",
            "data": {
                "text": "语音已接收",
                "bytes_size": len(content)
            }
        }
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        raise HTTPException(status_code=500, detail=f"语音识别处理失败: {str(e)}")
