"""测试语音模块路由 (TTS / STT)"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_voice_tts_endpoint_empty():
    """测试 TTS 文本为空时返回 400 校验错误"""
    response = client.post("/api/v1/voice/tts", json={"text": ""})
    assert response.status_code == 400


def test_voice_tts_endpoint_success():
    """测试 TTS 接口正常调用"""
    response = client.post(
        "/api/v1/voice/tts",
        json={"text": "请简述 HashMap 的底层实现原理", "voice": "zh-CN-YunxiNeural"}
    )
    # 当后端无 edge-tts 时降级返回 200 JSON，安装了 edge-tts 时返回 audio/mpeg
    assert response.status_code == 200


def test_voice_stt_endpoint():
    """测试 STT 接口上传音频"""
    files = {"file": ("test.wav", b"fake audio byte data", "audio/wav")}
    response = client.post("/api/v1/voice/stt", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["data"]["bytes_size"] == len(b"fake audio byte data")
