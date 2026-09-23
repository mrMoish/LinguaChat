import os
import uuid
import json
import base64
import ssl
import io
from typing import Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware

import httpx
import asyncpg
from dotenv import load_dotenv

from PIL import Image, ImageOps
import pillow_heif

from prompts import (
    get_unified_prompt,
    get_summary_update_prompt,
    get_summary_rebuild_prompt,
)


load_dotenv()
pillow_heif.register_heif_opener()


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


DEFAULT_LANGUAGE = "Chinese"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

TRANSCRIPTION_URL = (
    "https://openrouter.ai/api/v1/audio/transcriptions"
)

DATABASE_URL = os.getenv("DATABASE_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

STORAGE_BUCKET = "chat-images"

TEXT_MODEL = "openai/gpt-5.6-luna"
VISION_MODEL = "openai/gpt-5.6-luna"
TRANSCRIPTION_MODEL = "openai/whisper-large-v3"


db_pool = None


# ============================================================
# DATABASE
# ============================================================

@app.on_event("startup")
async def startup():
    global db_pool

    if not DATABASE_URL:
        print("DATABASE_URL is not configured.")
        return

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=60,
            command_timeout=60,
            max_inactive_connection_lifetime=60,
            ssl=ctx,
            statement_cache_size=0,
        )

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    session_id UUID NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    session_id UUID PRIMARY KEY,
                    target_language_name VARCHAR(100)
                        DEFAULT 'Chinese'
                )
                """
            )

            await conn.execute(
                """
                ALTER TABLE chat_history
                ADD COLUMN IF NOT EXISTS
                message_type VARCHAR(20)
                DEFAULT 'text'
                """
            )

            await conn.execute(
                """
                ALTER TABLE chat_history
                ADD COLUMN IF NOT EXISTS
                media_url TEXT
                """
            )

            # ==================================================
            # Долговременная память одного постоянного чата
            # ==================================================

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory (
                    session_id UUID PRIMARY KEY,

                    chat_summary TEXT NOT NULL DEFAULT '',

                    summary_message_count INTEGER NOT NULL
                        DEFAULT 0,

                    updated_at TIMESTAMP WITH TIME ZONE
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        print("База данных успешно подключена!")

    except Exception as e:
        print(f"DB Error: {e}")


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()


# ============================================================
# SESSION
# ============================================================

def get_session_id(
    req: Request,
    fallback_session_id: Optional[str] = None,
):
    """
    Приоритет:

    1. X-Session-Id header
    2. session_id из Form/query
    3. новый UUID
    """

    return (
        req.headers.get("X-Session-Id")
        or fallback_session_id
        or req.query_params.get("session_id")
        or str(uuid.uuid4())
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

async def save_message(
    conn,
    session_id,
    user_text,
    ai_reply,
    msg_type="text",
    media_url=None,
):
    await conn.execute(
        """
        INSERT INTO chat_history
        (
            session_id,
            role,
            content,
            message_type,
            media_url
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        session_id,
        "user",
        user_text,
        msg_type,
        media_url,
    )

    await conn.execute(
        """
        INSERT INTO chat_history
        (
            session_id,
            role,
            content,
            message_type,
            media_url
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        session_id,
        "assistant",
        ai_reply,
        "text",
        None,
    )


async def get_user_language(
    session_id: uuid.UUID,
) -> str:

    if not db_pool:
        return DEFAULT_LANGUAGE

    try:
        async with db_pool.acquire() as conn:

            row = await conn.fetchrow(
                """
                SELECT target_language_name
                FROM user_settings
                WHERE session_id = $1
                """,
                session_id,
            )

            if row and row["target_language_name"]:
                return row["target_language_name"]

            await conn.execute(
                """
                INSERT INTO user_settings
                (
                    session_id,
                    target_language_name
                )
                VALUES ($1, $2)
                ON CONFLICT (session_id)
                DO NOTHING
                """,
                session_id,
                DEFAULT_LANGUAGE,
            )

    except Exception as e:
        print(
            f"Error getting language: {e}"
        )

    return DEFAULT_LANGUAGE


# ============================================================
# RECENT HISTORY
# ============================================================

RECENT_HISTORY_LIMIT = 20


async def get_recent_history(
    conn,
    session_id: uuid.UUID,
    limit: int = RECENT_HISTORY_LIMIT,
):
    rows = await conn.fetch(
        """
        SELECT role, content
        FROM chat_history
        WHERE session_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )

    return list(reversed(rows))


async def get_all_history(
    conn,
    session_id: uuid.UUID,
):
    rows = await conn.fetch(
        """
        SELECT role, content
        FROM chat_history
        WHERE session_id = $1
        ORDER BY created_at ASC, id ASC
        """,
        session_id,
    )

    return list(rows)


async def get_message_count(
    conn,
    session_id: uuid.UUID,
) -> int:

    result = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM chat_history
        WHERE session_id = $1
        """,
        session_id,
    )

    return int(result or 0)


# ============================================================
# CHAT MEMORY
# ============================================================

SUMMARY_REBUILD_EVERY_MESSAGES = 200


async def get_chat_memory(
    conn,
    session_id: uuid.UUID,
):
    row = await conn.fetchrow(
        """
        SELECT
            chat_summary,
            summary_message_count
        FROM chat_memory
        WHERE session_id = $1
        """,
        session_id,
    )

    if not row:

        await conn.execute(
            """
            INSERT INTO chat_memory
            (
                session_id,
                chat_summary,
                summary_message_count
            )
            VALUES ($1, '', 0)
            ON CONFLICT (session_id)
            DO NOTHING
            """,
            session_id,
        )

        return "", 0

    return (
        row["chat_summary"] or "",
        row["summary_message_count"] or 0,
    )


def normalize_memory_updates(
    value,
):
    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        if not isinstance(item, str):
            continue

        item = item.strip()

        if item:
            result.append(item)

    return result[:5]


async def save_chat_summary(
    session_id: uuid.UUID,
    summary: str,
):
    summary = (summary or "").strip()

    if not summary:
        return

    async with db_pool.acquire() as conn:

        message_count = await get_message_count(
            conn,
            session_id,
        )

        await conn.execute(
            """
            INSERT INTO chat_memory
            (
                session_id,
                chat_summary,
                summary_message_count,
                updated_at
            )
            VALUES (
                $1,
                $2,
                $3,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (session_id)
            DO UPDATE SET
                chat_summary = EXCLUDED.chat_summary,
                summary_message_count =
                    EXCLUDED.summary_message_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            session_id,
            summary,
            message_count,
        )


async def update_summary_from_memory_updates(
    session_id: uuid.UUID,
    current_summary: str,
    memory_updates: list[str],
):
    if not memory_updates:
        return

    messages = [
        {
            "role": "system",
            "content": get_summary_update_prompt(
                current_summary
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        memory_updates,
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    ]

    result = await call_openrouter(
        messages,
        model=TEXT_MODEL,
    )

    new_summary = (
        result.get("chat_summary") or ""
    ).strip()

    if not new_summary:
        print(
            "Summary update returned empty summary."
        )
        return

    await save_chat_summary(
        session_id,
        new_summary,
    )

    print(
        "Chat summary updated from memory updates."
    )


async def rebuild_chat_summary(
    session_id: uuid.UUID,
    current_summary: str,
):
    async with db_pool.acquire() as conn:
        history_rows = await get_all_history(
            conn,
            session_id,
        )

    if not history_rows:
        return

    history_messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history_rows
        if row["content"]
    ]

    if not history_messages:
        return

    messages = [
        {
            "role": "system",
            "content": get_summary_rebuild_prompt(
                current_summary
            ),
        },
        *history_messages,
    ]

    result = await call_openrouter(
        messages,
        model=TEXT_MODEL,
    )

    new_summary = (
        result.get("chat_summary") or ""
    ).strip()

    if not new_summary:
        print(
            "Full summary rebuild returned empty summary."
        )
        return

    await save_chat_summary(
        session_id,
        new_summary,
    )

    print(
        "Chat summary fully rebuilt from history."
    )


async def refresh_chat_memory(
    session_id: uuid.UUID,
    memory_updates: list[str],
):
    """
    Обновление памяти.

    Приоритет:

    1. Если появился новый важный факт —
       сразу обновить summary.

    2. Если новых фактов нет, но накопилось
       достаточно сообщений —
       выполнить полную пересборку summary
       из исходной истории.

    Ошибка памяти не должна ломать
    основной ответ пользователю.
    """

    try:

        async with db_pool.acquire() as conn:

            current_summary, summary_message_count = (
                await get_chat_memory(
                    conn,
                    session_id,
                )
            )

            total_message_count = (
                await get_message_count(
                    conn,
                    session_id,
                )
            )

        # ----------------------------------------------------
        # Новый важный факт
        # ----------------------------------------------------

        if memory_updates:

            await update_summary_from_memory_updates(
                session_id,
                current_summary,
                memory_updates,
            )

            return

        # ----------------------------------------------------
        # Периодическая защита от накопления ошибок
        # ----------------------------------------------------

        messages_since_summary = (
            total_message_count
            - summary_message_count
        )

        if (
            messages_since_summary
            >= SUMMARY_REBUILD_EVERY_MESSAGES
        ):

            await rebuild_chat_summary(
                session_id,
                current_summary,
            )

    except Exception as e:

        print(
            f"Chat memory update error: {e}"
        )


# ============================================================
# OPENROUTER
# ============================================================

async def call_openrouter(
    messages: list,
    model: str,
):

    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_object"
        },
        "temperature": 0.7,
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=60.0,
        )

    if response.status_code != 200:

        print(
            f"OpenRouter Error "
            f"{response.status_code}: "
            f"{response.text}"
        )

        if response.status_code == 429:

            raise HTTPException(
                status_code=429,
                detail="ИИ перегружен.",
            )

        raise HTTPException(
            status_code=response.status_code,
            detail="Ошибка ИИ.",
        )

    data = response.json()

    if (
        "choices" not in data
        or not data["choices"]
    ):

        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул ответ.",
        )

    raw_content = (
        data["choices"][0]["message"]["content"]
    )

    if not raw_content:
        raise HTTPException(
            status_code=500,
            detail="ИИ вернул пустой ответ.",
        )

    raw_text = raw_content.strip()

    try:

        parsed = json.loads(raw_text)

        print("\n========== PARSED TRANSLATION ==========")
        print(repr(parsed.get("translation")))
        print("========================================\n")

    except json.JSONDecodeError:

        print(
            "Invalid JSON returned by model:",
            raw_text,
        )

        raise HTTPException(
            status_code=500,
            detail="Ошибка формата ИИ.",
        )

    if not isinstance(parsed, dict):

        raise HTTPException(
            status_code=500,
            detail="Ошибка формата ИИ.",
        )

    return parsed


# ============================================================
# SUPABASE STORAGE
# ============================================================

async def upload_to_supabase(
    file_bytes: bytes,
    content_type: str,
    extension: str,
) -> str:

    file_name = (
        f"{uuid.uuid4().hex}.{extension}"
    )

    upload_url = (
        f"{SUPABASE_URL}"
        f"/storage/v1/object/"
        f"{STORAGE_BUCKET}/"
        f"{file_name}"
    )

    headers = {
        "Authorization": (
            f"Bearer {SUPABASE_SERVICE_KEY}"
        ),
        "Content-Type": content_type,
        "x-upsert": "true",
    }

    async with httpx.AsyncClient() as client:

        resp = await client.post(
            upload_url,
            headers=headers,
            content=file_bytes,
            timeout=30.0,
        )

    if resp.status_code not in (200, 201):

        print(
            f"Supabase upload error "
            f"{resp.status_code}: "
            f"{resp.text}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to upload to "
                "Supabase Storage"
            ),
        )

    return (
        f"{SUPABASE_URL}"
        f"/storage/v1/object/public/"
        f"{STORAGE_BUCKET}/"
        f"{file_name}"
    )


# ============================================================
# AUDIO
# ============================================================

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

    mime_type = (
        content_type
        .split(";")[0]
        .lower()
        .strip()
    )

    if mime_type in AUDIO_MIME_TYPES:
        return True

    filename_lower = (
        filename or ""
    ).lower()

    return any(
        filename_lower.endswith(ext)
        for ext in AUDIO_EXTENSIONS
    )


def get_audio_format(
    content_type: str,
    filename: str = "",
) -> str:

    mime_type = (
        content_type
        .split(";")[0]
        .lower()
        .strip()
    )

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

    filename_lower = (
        filename or ""
    ).lower()

    if filename_lower.endswith(".m4a"):
        return "m4a"

    if filename_lower.endswith(".mp4"):
        return "m4a"

    if filename_lower.endswith(".mp3"):
        return "mp3"

    if filename_lower.endswith(".wav"):
        return "wav"

    if filename_lower.endswith(".ogg"):
        return "ogg"

    if filename_lower.endswith(".flac"):
        return "flac"

    if filename_lower.endswith(".aac"):
        return "aac"

    if filename_lower.endswith(".webm"):
        return "webm"

    return "webm"


def get_audio_storage_content_type(
    audio_format: str,
) -> str:

    content_types = {
        "webm": "audio/webm",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }

    return content_types.get(
        audio_format,
        "application/octet-stream",
    )


async def transcribe_audio(
    audio_bytes: bytes,
    content_type: str,
    filename: str = "",
) -> str:

    audio_base64 = base64.b64encode(
        audio_bytes
    ).decode("utf-8")

    audio_format = get_audio_format(
        content_type,
        filename,
    )

    payload = {
        "model": TRANSCRIPTION_MODEL,
        "input_audio": {
            "data": audio_base64,
            "format": audio_format,
        },
    }

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    print(
        "Transcribing audio: "
        f"format={audio_format}, "
        f"content_type={content_type}, "
        f"filename={filename}, "
        f"size={len(audio_bytes)} bytes"
    )

    async with httpx.AsyncClient() as client:

        resp = await client.post(
            TRANSCRIPTION_URL,
            headers=headers,
            json=payload,
            timeout=60.0,
        )

    if resp.status_code != 200:

        print(
            f"Transcription error "
            f"{resp.status_code}: "
            f"{resp.text}"
        )

        raise HTTPException(
            status_code=500,
            detail="Ошибка распознавания аудио.",
        )

    data = resp.json()

    if "text" not in data:

        print(
            "Unexpected transcription response:",
            data,
        )

        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул текст аудио.",
        )

    transcription = (
        data["text"].strip()
    )

    print(
        "Transcription result: "
        f"{transcription}"
    )

    if not transcription:

        raise HTTPException(
            status_code=400,
            detail=(
                "Не удалось распознать "
                "речь в аудио."
            ),
        )

    return transcription


# ============================================================
# MAIN AI PROCESSING
# ============================================================

async def process_message(
    user_content,
    session_id,
    msg_type="text",
    media_url=None,
    user_text_for_history="",
):

    target_lang = await get_user_language(
        session_id
    )

    # --------------------------------------------------------
    # Получаем summary + последние сообщения
    # --------------------------------------------------------

    async with db_pool.acquire() as conn:

        history_rows = await get_recent_history(
            conn,
            session_id,
            RECENT_HISTORY_LIMIT,
        )

        chat_summary, _ = await get_chat_memory(
            conn,
            session_id,
        )

    history_messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history_rows
    ]

    # --------------------------------------------------------
    # Первый вопрос
    # --------------------------------------------------------

    if not history_messages:

        history_messages = [
            {
                "role": "assistant",
                "content": (
                    "Какой у вас уровень китайского?"
                ),
            }
        ]

    # --------------------------------------------------------
    # Основной запрос к AI
    # --------------------------------------------------------

    messages = [
        {
            "role": "system",
            "content": get_unified_prompt(
                target_lang,
                chat_summary=chat_summary,
            ),
        },
        *history_messages,
        {
            "role": "user",
            "content": user_content,
        },
    ]

    result = await call_openrouter(
        messages,
        model=TEXT_MODEL,
    )

    translation = (
        result.get("translation") or ""
    ).strip()

    if not translation:

        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул ответ.",
        )

    memory_updates = normalize_memory_updates(
        result.get("memory_updates")
    )

    # --------------------------------------------------------
    # Сохраняем основную историю
    # --------------------------------------------------------

    async with db_pool.acquire() as conn:

        await save_message(
            conn,
            session_id,
            user_text_for_history,
            translation,
            msg_type=msg_type,
            media_url=media_url,
        )

    # --------------------------------------------------------
    # Обновляем долгосрочную память
    # --------------------------------------------------------

    await refresh_chat_memory(
        session_id,
        memory_updates,
    )

    return {
        "translation": translation,
        "media_url": media_url,
    }


# ============================================================
# TEXT
# ============================================================

async def process_text(
    text: str,
    session_id: uuid.UUID,
) -> dict:

    user_content = [
        {
            "type": "text",
            "text": text,
        }
    ]

    return await process_message(
        user_content,
        session_id,
        msg_type="text",
        user_text_for_history=text,
    )


# ============================================================
# IMAGE
# ============================================================

async def process_image(
    file: UploadFile,
    session_id: uuid.UUID,
) -> dict:

    contents = await file.read()

    if len(contents) > 5 * 1024 * 1024:

        raise HTTPException(
            status_code=413,
            detail="Файл слишком большой.",
        )

    try:

        img = Image.open(
            io.BytesIO(contents)
        )

        img = ImageOps.exif_transpose(
            img
        )

        img = img.convert("RGB")

        buffer = io.BytesIO()

        img.save(
            buffer,
            format="JPEG",
            quality=85,
        )

        jpeg_bytes = buffer.getvalue()

    except Exception as img_err:

        print(
            f"Image processing error: "
            f"{img_err}"
        )

        raise HTTPException(
            status_code=400,
            detail="Invalid image file",
        )

    media_url = await upload_to_supabase(
        jpeg_bytes,
        "image/jpeg",
        "jpg",
    )

    image_base64 = base64.b64encode(
        jpeg_bytes
    ).decode("utf-8")

    user_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": (
                    "data:image/jpeg;base64,"
                    f"{image_base64}"
                )
            },
        },
        {
            "type": "text",
            "text": (
                "(User sent an image. "
                "Please analyze it.)"
            ),
        },
    ]

    return await process_message(
        user_content,
        session_id,
        msg_type="image",
        media_url=media_url,
        user_text_for_history="",
    )


# ============================================================
# /api/message
# ============================================================

@app.post("/api/message")
async def message(
    req: Request,
    text: Optional[str] = Form(None),
    file: UploadFile = File(None),
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
):

    if not OPENROUTER_API_KEY:

        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    if not db_pool:

        raise HTTPException(
            status_code=503,
            detail="База данных не подключена.",
        )

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:

        session_id = uuid.UUID(
            session_id_str
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    # --------------------------------------------------------
    # FILE
    # --------------------------------------------------------

    if file:

        contents = await file.read()

        if len(contents) > 5 * 1024 * 1024:

            raise HTTPException(
                status_code=413,
                detail="Файл слишком большой.",
            )

        content_type = (
            file.content_type or ""
        ).lower()

        filename = file.filename or ""

        print(
            "Received file: "
            f"name={filename}, "
            f"type={content_type}, "
            f"size={len(contents)}"
        )

        # ====================================================
        # IMAGE
        # ====================================================

        if content_type.startswith(
            "image/"
        ):

            try:

                img = Image.open(
                    io.BytesIO(contents)
                )

                img = ImageOps.exif_transpose(
                    img
                )

                img = img.convert("RGB")

                buffer = io.BytesIO()

                img.save(
                    buffer,
                    format="JPEG",
                    quality=85,
                )

                jpeg_bytes = (
                    buffer.getvalue()
                )

            except Exception as e:

                print(
                    f"Image processing error: "
                    f"{e}"
                )

                raise HTTPException(
                    status_code=400,
                    detail="Invalid image file",
                )

            media_url = (
                await upload_to_supabase(
                    jpeg_bytes,
                    "image/jpeg",
                    "jpg",
                )
            )

            image_base64 = (
                base64.b64encode(
                    jpeg_bytes
                ).decode("utf-8")
            )

            user_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            "data:image/jpeg;base64,"
                            f"{image_base64}"
                        )
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "(User sent an image. "
                        "Please analyze it.)"
                    ),
                },
            ]

            result = await process_message(
                user_content,
                session_id,
                msg_type="image",
                media_url=media_url,
                user_text_for_history="",
            )

            return {
                "translation": result[
                    "translation"
                ],
                "media_url": media_url,
                "session_id": session_id_str,
            }

        # ====================================================
        # AUDIO
        # ====================================================

        elif is_audio_file(
            content_type,
            filename,
        ):

            audio_format = get_audio_format(
                content_type,
                filename,
            )

            storage_content_type = (
                get_audio_storage_content_type(
                    audio_format
                )
            )

            print(
                "Audio detected: "
                f"format={audio_format}, "
                f"storage_type="
                f"{storage_content_type}"
            )

            # ----------------------------------------------
            # Upload audio
            # ----------------------------------------------

            media_url = (
                await upload_to_supabase(
                    contents,
                    storage_content_type,
                    audio_format,
                )
            )

            # ----------------------------------------------
            # Transcription
            # ----------------------------------------------

            transcription = (
                await transcribe_audio(
                    contents,
                    content_type,
                    filename,
                )
            )

            # ----------------------------------------------
            # Send transcription to AI
            # ----------------------------------------------

            user_content = [
                {
                    "type": "text",
                    "text": (
                        "(User sent an audio "
                        "message. "
                        "Here is the transcription: "
                        f"'{transcription}')"
                    ),
                }
            ]

            result = await process_message(
                user_content,
                session_id,
                msg_type="audio",
                media_url=media_url,
                user_text_for_history=(
                    transcription
                ),
            )

            return {
                "translation": result[
                    "translation"
                ],
                "media_url": media_url,
                "transcription": transcription,
                "session_id": session_id_str,
            }

        # ====================================================
        # UNSUPPORTED FILE
        # ====================================================

        else:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported file type."
                ),
            )

    # ========================================================
    # TEXT
    # ========================================================

    elif text and text.strip():

        result = await process_text(
            text.strip(),
            session_id,
        )

        return {
            "translation": result[
                "translation"
            ],
            "media_url": None,
            "session_id": session_id_str,
        }

    # ========================================================
    # EMPTY
    # ========================================================

    else:

        raise HTTPException(
            status_code=400,
            detail="Message is empty.",
        )


# ============================================================
# /api/history
# ============================================================

@app.get("/api/history")
async def get_history(
    req: Request,
    session_id: Optional[str] = None,
):

    session_id_str = get_session_id(
        req,
        session_id,
    )

    try:

        session_uuid = uuid.UUID(
            session_id_str
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    if db_pool:

        async with db_pool.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT
                    role,
                    content,
                    message_type,
                    media_url
                FROM chat_history
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                session_uuid,
            )

            history = [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "message_type": (
                        r["message_type"]
                        or "text"
                    ),
                    "media_url": (
                        r["media_url"]
                    ),
                }
                for r in rows
            ]

            return {
                "session_id": session_id_str,
                "history": history,
                "messages": history,
            }

    return {
        "session_id": session_id_str,
        "history": [],
        "messages": [],
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def read_root():
    return {
        "status": "Backend is running"
    }