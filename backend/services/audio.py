import base64
from fastapi import HTTPException
from backend.core.config import (
    OPENROUTER_API_KEY,
    TRANSCRIPTION_URL,
    TRANSCRIPTION_MODEL,
)
from backend.services.http_client import client_manager

AUDIO_EXTENSIONS = {
    ".webm",
    ".mp3",
    ".mpeg",
    ".mp4",
    ".m4a",
    ".wav",
    ".ogg",
    ".oga",
    ".flac",
    ".aac",
}

AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/flac",
    "audio/aac",
    "video/mp4",
    "video/webm",
    "application/mp4",
}

def is_audio_file(
    content_type: str,
    filename: str = "",
) -> bool:
    mime_type = content_type.split(";")[0].lower().strip()
    if mime_type in AUDIO_MIME_TYPES:
        return True

    filename_lower = (filename or "").lower()
    return any(
        filename_lower.endswith(ext)
        for ext in AUDIO_EXTENSIONS
    )

def get_audio_format(
    content_type: str,
    filename: str = "",
) -> str:
    mime_type = content_type.split(";")[0].lower().strip()

    format_map = {
        "audio/webm": "webm",
        "video/webm": "webm",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "video/mp4": "m4a",
        "application/mp4": "m4a",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
        "audio/aac": "aac",
    }

    if mime_type in format_map:
        return format_map[mime_type]

    filename_lower = (filename or "").lower()
    for ext in ("m4a", "mp4", "mp3", "wav", "ogg", "flac", "aac", "webm"):
        if filename_lower.endswith(f".{ext}"):
            return "m4a" if ext in ("m4a", "mp4") else ext

    return "webm"

def get_audio_storage_content_type(audio_format: str) -> str:
    content_types = {
        "webm": "audio/webm",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }
    return content_types.get(audio_format, "application/octet-stream")

async def transcribe_audio(
    audio_bytes: bytes,
    content_type: str,
    filename: str = "",
) -> str:
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    audio_format = get_audio_format(content_type, filename)

    payload = {
        "model": TRANSCRIPTION_MODEL,
        "input_audio": {
            "data": audio_base64,
            "format": audio_format,
        },
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    print(
        "Transcribing audio: "
        f"format={audio_format}, "
        f"content_type={content_type}, "
        f"filename={filename}, "
        f"size={len(audio_bytes)} bytes"
    )

    client = await client_manager.get_client()
    resp = await client.post(
        TRANSCRIPTION_URL,
        headers=headers,
        json=payload,
    )

    if resp.status_code != 200:
        print(f"Transcription error {resp.status_code}: {resp.text}")
        raise HTTPException(
            status_code=500,
            detail="Ошибка распознавания аудио.",
        )

    data = resp.json()
    if "text" not in data:
        print("Unexpected transcription response:", data)
        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул текст аудио.",
        )

    transcription = data["text"].strip()
    if not transcription:
        raise HTTPException(
            status_code=400,
            detail="Не удалось распознать речь в аудио.",
        )

    print(f"Transcription result: {transcription}")
    return transcription
