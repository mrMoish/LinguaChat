import os
import uuid
import json
import base64
import ssl
import io
import asyncio
from random import SystemRandom
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
    get_exercise_prompt,
    get_summary_update_prompt,
    get_summary_rebuild_prompt,
)


# ============================================================
# CONFIG
# ============================================================

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


from admin import router as admin_router

app.include_router(
    admin_router,
    prefix="/api/admin",
)


DEFAULT_LANGUAGE = "Chinese"
WELCOME_MESSAGE_CONTENT = (
    "Я AI-переводчик, который также поможет тебе учить язык"
)

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

TRANSCRIPTION_URL = (
    "https://openrouter.ai/api/v1/audio/transcriptions"
)

DATABASE_URL = os.getenv("DATABASE_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY"
)

STORAGE_BUCKET = "chat-images"

TEXT_MODEL = "openai/gpt-5.6-luna"
VISION_MODEL = "openai/gpt-5.6-luna"
TRANSCRIPTION_MODEL = "openai/whisper-large-v3"

RANDOMIZER = SystemRandom()

DEFAULT_TEMPERATURE = 0.7
TRANSLATOR_TEMPERATURE = 0.82

MAX_IMAGE_SIZE = 1600
JPEG_QUALITY = 80

OPENROUTER_TIMEOUT = httpx.Timeout(
    connect=20,
    read=90,
    write=90,
    pool=20,
)

DEFAULT_CONVERSATION_MODE = "translator"


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

        app.state.db_pool = db_pool

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

            await conn.execute(
                """
                ALTER TABLE chat_history
                ADD COLUMN IF NOT EXISTS
                exercise_data TEXT
                """
            )

            await conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS
                conversation_mode VARCHAR(20)
                DEFAULT 'translator'
                """
            )

            await conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS
                welcome_exercise_data TEXT
                """
            )

            # ==================================================
            # LONG-TERM CHAT MEMORY
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

    1. X-Session-Id
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
    exercise=None,
):
    user_message_id = await conn.fetchval(
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
        RETURNING id
        """,
        session_id,
        "user",
        user_text,
        msg_type,
        media_url,
    )

    exercise_json = None

    if exercise is not None:
        exercise_json = json.dumps(
            exercise,
            ensure_ascii=False,
        )

    assistant_message_id = await conn.fetchval(
        """
        INSERT INTO chat_history
        (
            session_id,
            role,
            content,
            message_type,
            media_url,
            exercise_data
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        session_id,
        "assistant",
        ai_reply,
        "text",
        None,
        exercise_json,
    )

    return user_message_id, assistant_message_id


async def update_message_media_url(
    message_id: int,
    media_url: str,
):
    if not db_pool:
        return

    try:
        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                UPDATE chat_history
                SET media_url = $1
                WHERE id = $2
                """,
                media_url,
                message_id,
            )

        print(
            f"media_url updated for message "
            f"{message_id}"
        )

    except Exception as e:
        print(
            f"Failed to update media_url "
            f"for message {message_id}: {e}"
        )


async def upload_image_and_update_history(
    image_bytes: bytes,
    message_id: int,
):
    """
    Background upload.

    OpenRouter response is returned to user first.
    Supabase upload happens independently.
    """

    try:

        media_url = await upload_to_supabase(
            image_bytes,
            "image/jpeg",
            "jpg",
        )

        await update_message_media_url(
            message_id,
            media_url,
        )

        print(
            f"Background image upload completed "
            f"for message {message_id}"
        )

    except Exception as e:

        print(
            f"Background image upload failed "
            f"for message {message_id}: {e}"
        )


def normalize_conversation_mode(value) -> str:
    if value == "teacher":
        return "teacher"

    return DEFAULT_CONVERSATION_MODE


def normalize_learner_level_hint(value) -> str:
    allowed = {
        "unknown",
        "beginner",
        "elementary",
        "intermediate",
        "upper_intermediate",
    }

    value = str(value or "unknown").strip().lower()

    if value in allowed:
        return value

    return "unknown"


def detect_preferred_exercise_type(
    chat_summary: str,
) -> str:
    summary = (chat_summary or "").lower()

    if any(
        marker in summary
        for marker in (
            "поиск пар",
            "пары между",
            "pinyin и перевод",
            "пары и перевод",
        )
    ):
        return "matching_pairs"

    return "auto"


async def get_user_settings(
    session_id: uuid.UUID,
) -> tuple[str, str]:

    if not db_pool:
        return (
            DEFAULT_LANGUAGE,
            DEFAULT_CONVERSATION_MODE,
        )

    try:

        async with db_pool.acquire() as conn:

            row = await conn.fetchrow(
                """
                SELECT
                    target_language_name,
                    conversation_mode
                FROM user_settings
                WHERE session_id = $1
                """,
                session_id,
            )

            if row:
                language = (
                    row["target_language_name"]
                    or DEFAULT_LANGUAGE
                )

                mode = normalize_conversation_mode(
                    row["conversation_mode"]
                )

                return language, mode

            await conn.execute(
                """
                INSERT INTO user_settings
                (
                    session_id,
                    target_language_name,
                    conversation_mode
                )
                VALUES ($1, $2, $3)
                ON CONFLICT (session_id)
                DO NOTHING
                """,
                session_id,
                DEFAULT_LANGUAGE,
                DEFAULT_CONVERSATION_MODE,
            )

    except Exception as e:

        print(
            f"Error getting user settings: {e}"
        )

    return (
        DEFAULT_LANGUAGE,
        DEFAULT_CONVERSATION_MODE,
    )


async def get_user_language(
    session_id: uuid.UUID,
) -> str:

    language, _ = await get_user_settings(
        session_id
    )

    return language


async def save_conversation_mode(
    session_id: uuid.UUID,
    mode: str,
):
    mode = normalize_conversation_mode(mode)

    if not db_pool:
        return

    try:

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                INSERT INTO user_settings
                (
                    session_id,
                    target_language_name,
                    conversation_mode
                )
                VALUES ($1, $2, $3)
                ON CONFLICT (session_id)
                DO UPDATE SET
                    conversation_mode =
                        EXCLUDED.conversation_mode
                """,
                session_id,
                DEFAULT_LANGUAGE,
                mode,
            )

    except Exception as e:

        print(
            f"Error saving conversation_mode: {e}"
        )


async def save_welcome_exercise(
    session_id: uuid.UUID,
    exercise: dict,
):
    if not db_pool:
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_settings
                (
                    session_id,
                    target_language_name,
                    conversation_mode,
                    welcome_exercise_data
                )
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (session_id)
                DO UPDATE SET
                    welcome_exercise_data = EXCLUDED.welcome_exercise_data
                """,
                session_id,
                DEFAULT_LANGUAGE,
                DEFAULT_CONVERSATION_MODE,
                json.dumps(exercise, ensure_ascii=False),
            )

            await conn.execute(
                """
                INSERT INTO chat_history
                (
                    session_id,
                    role,
                    content,
                    message_type,
                    exercise_data
                )
                SELECT $1, 'assistant', $2, 'text', $3
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM chat_history
                    WHERE session_id = $1
                      AND role = 'assistant'
                      AND content = $2
                )
                """,
                session_id,
                WELCOME_MESSAGE_CONTENT,
                json.dumps(exercise, ensure_ascii=False),
            )
    except Exception as e:
        print(f"Error saving welcome exercise: {e}")


async def get_welcome_exercise(
    session_id: uuid.UUID,
):
    if not db_pool:
        return None

    try:
        async with db_pool.acquire() as conn:
            raw = await conn.fetchval(
                """
                SELECT welcome_exercise_data
                FROM user_settings
                WHERE session_id = $1
                """,
                session_id,
            )

        if not raw:
            return None

        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, dict) else None
    except Exception as e:
        print(f"Error reading welcome exercise: {e}")
        return None


async def clear_welcome_exercise(
    session_id: uuid.UUID,
):
    if not db_pool:
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_settings
                SET welcome_exercise_data = NULL
                WHERE session_id = $1
                """,
                session_id,
            )
    except Exception as e:
        print(f"Error clearing welcome exercise: {e}")


async def attach_welcome_exercises_to_message(
    session_id: uuid.UUID,
    assistant_message_id: Optional[int],
    exercises,
):
    if not exercises or not db_pool:
        return

    try:
        async with db_pool.acquire() as conn:
            message_id = assistant_message_id

            if not message_id:
                message_id = await conn.fetchval(
                    """
                    SELECT id
                    FROM chat_history
                    WHERE session_id = $1
                      AND role = 'assistant'
                      AND content = $2
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    session_id,
                    WELCOME_MESSAGE_CONTENT,
                )

            if not message_id:
                return

            await conn.execute(
                """
                UPDATE chat_history
                SET exercise_data = $1
                WHERE id = $2
                  AND session_id = $3
                  AND role = 'assistant'
                """,
                json.dumps(exercises, ensure_ascii=False),
                message_id,
                session_id,
            )
    except Exception as e:
        print(f"Error attaching welcome exercises: {e}")


# ============================================================
# HISTORY
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


async def get_recent_exercises(
    conn,
    session_id: uuid.UUID,
    limit: int = 40,
):
    rows = await conn.fetch(
        """
        SELECT exercise_data
        FROM chat_history
        WHERE session_id = $1
          AND exercise_data IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )

    exercises = []

    for row in reversed(rows):
        raw = row["exercise_data"]

        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue

        values = value if isinstance(value, list) else [value]

        for exercise in values:
            if not isinstance(exercise, dict):
                continue

            question = (
                exercise.get("question")
                or exercise.get("text")
                or ""
            )

            if question:
                exercises.append(str(question).strip())

    return exercises


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


async def refresh_chat_memory(
    session_id: uuid.UUID,
    memory_updates: list[str],
):

    try:

        async with db_pool.acquire() as conn:

            (
                current_summary,
                summary_message_count,
            ) = await get_chat_memory(
                conn,
                session_id,
            )

            total_message_count = (
                await get_message_count(
                    conn,
                    session_id,
                )
            )

        if memory_updates:

            await update_summary_from_memory_updates(
                session_id,
                current_summary,
                memory_updates,
            )

            return

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
    temperature: float = DEFAULT_TEMPERATURE,
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
        "temperature": temperature,
    }

    async with httpx.AsyncClient(
        timeout=OPENROUTER_TIMEOUT
    ) as client:

        response = await client.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
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

        print(
            "\n========== AI RESPONSE =========="
        )
        print(
            json.dumps(
                parsed,
                ensure_ascii=False,
                indent=2,
            )
        )
        print(
            "=================================\n"
        )

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

        raise Exception(
            "Failed to upload to Supabase Storage"
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

    async with httpx.AsyncClient(
        timeout=OPENROUTER_TIMEOUT
    ) as client:

        resp = await client.post(
            TRANSCRIPTION_URL,
            headers=headers,
            json=payload,
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

    if not transcription:

        raise HTTPException(
            status_code=400,
            detail=(
                "Не удалось распознать "
                "речь в аудио."
            ),
        )

    print(
        "Transcription result: "
        f"{transcription}"
    )

    return transcription


# ============================================================
# EXERCISE
# ============================================================

def fallback_exercise(translation: str) -> dict:
    snippet = (translation or "").strip()

    if "\n" in snippet:
        snippet = snippet.split("\n", 1)[0].strip()

    if len(snippet) > 80:
        snippet = snippet[:77].rstrip() + "…"

    if snippet:
        is_negative = (
            sum(ord(char) for char in snippet) % 2
        ) == 1

        if is_negative:
            question = (
                "Означает ли этот перевод "
                "противоположное исходному смыслу: "
                f"«{snippet}»?"
            )
            correct_answer = "no"
            explanation = (
                "Нет, перевод сохраняет исходный смысл."
            )
        else:
            question = (
                "Передаёт ли этот перевод смысл "
                f"исходной фразы: «{snippet}»?"
            )
            correct_answer = "yes"
            explanation = (
                "Да, перевод сохраняет исходный смысл."
            )
    else:
        question = (
            "Правильно ли вы поняли перевод?"
        )
        correct_answer = "yes"
        explanation = (
            "Это упражнение к текущему переводу."
        )

    return {
        "type": "yes_no",
        "question": question,
        "correct_answer": correct_answer,
        "explanation": explanation,
    }


def normalize_exercise(
    exercise,
    conversation_mode: str,
    translation: str,
):
    question = ""
    correct_answer = ""
    explanation = ""

    if isinstance(exercise, dict):
        exercise_type = str(
            exercise.get("type") or "yes_no"
        ).strip().lower()

        if exercise_type in (
            "matching_pairs",
            "translation_choice",
        ):
            pairs = exercise.get("pairs")

            if isinstance(pairs, list):
                normalized_pairs = []

                for pair in pairs:
                    if not isinstance(pair, dict):
                        continue

                    term = str(
                        pair.get("term")
                        or pair.get("word")
                        or ""
                    ).strip()
                    translation_value = str(
                        pair.get("translation")
                        or ""
                    ).strip()

                    if term and translation_value:
                        normalized_pairs.append({
                            "term": term,
                            "translation": translation_value,
                        })

            else:
                normalized_pairs = []

            if 2 <= len(normalized_pairs) <= 5:
                RANDOMIZER.shuffle(normalized_pairs)
                translations = [
                    pair["translation"]
                    for pair in normalized_pairs
                ]
                RANDOMIZER.shuffle(translations)

                first_pair = normalized_pairs[0]
                distractors = [
                    value
                    for value in translations
                    if value != first_pair["translation"]
                ]
                initial_options = [
                    first_pair["translation"]
                ]
                if distractors:
                    initial_options.append(
                        RANDOMIZER.choice(distractors)
                    )
                RANDOMIZER.shuffle(initial_options)

                return {
                    "type": "matching_pairs",
                    "question": str(
                        "Найди пары"
                    ),
                    "pairs": normalized_pairs,
                    "translations": translations,
                    "initial_options": initial_options,
                    "explanation": str(
                        exercise.get("explanation") or ""
                    ).strip(),
                }

        question = (
            exercise.get("question")
            or exercise.get("text")
            or ""
        )
        question = str(question).strip()

        correct_answer = (
            exercise.get("correct_answer")
            or exercise.get("answer")
            or ""
        )
        correct_answer = str(
            correct_answer
        ).strip().lower()

        if correct_answer in (
            "да",
            "true",
            "1",
        ):
            correct_answer = "yes"

        if correct_answer in (
            "нет",
            "false",
            "0",
        ):
            correct_answer = "no"

        explanation = str(
            exercise.get("explanation") or ""
        ).strip()

        for prefix in (
            "Мини-упражнение:",
            "Упражнение:",
        ):
            if question.startswith(prefix):
                question = question[
                    len(prefix):
                ].strip()

    if (
        question
        and correct_answer in ("yes", "no")
    ):
        return {
            "type": "yes_no",
            "question": question,
            "correct_answer": correct_answer,
            "explanation": explanation,
        }

    return fallback_exercise(translation)


# ============================================================
# MAIN AI PROCESSING
# ============================================================

async def process_message(
    user_content,
    session_id,
    msg_type="text",
    media_url=None,
    user_text_for_history="",
    learner_level_hint="unknown",
):

    (
        target_lang,
        conversation_mode,
    ) = await get_user_settings(
        session_id
    )

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

        used_exercises = await get_recent_exercises(
            conn,
            session_id,
        )

    used_exercises_block = "\n".join(
        f"- {question}"
        for question in used_exercises
    )

    preferred_exercise_type = detect_preferred_exercise_type(
        chat_summary
    )

    history_messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history_rows
    ]

    messages = [
        {
            "role": "system",
            "content": get_unified_prompt(
                target_lang,
                chat_summary=chat_summary,
                conversation_mode=conversation_mode,
                learner_level_hint=normalize_learner_level_hint(
                    learner_level_hint
                ),
                used_exercises=used_exercises_block,
                preferred_exercise_type=preferred_exercise_type,
            ),
        },
        *history_messages,
        {
            "role": "user",
            "content": user_content,
        },
    ]

    model = TEXT_MODEL

    if msg_type == "image":
        model = VISION_MODEL

    result = await call_openrouter(
        messages,
        model=model,
        temperature=(
            TRANSLATOR_TEMPERATURE
            if conversation_mode == "translator"
            else DEFAULT_TEMPERATURE
        ),
    )

    translation = (
        result.get("translation") or ""
    ).strip()

    if not translation:

        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул ответ.",
        )

    returned_mode = result.get("mode")

    if returned_mode in (
        "translator",
        "teacher",
    ) and returned_mode != conversation_mode:

        await save_conversation_mode(
            session_id,
            returned_mode,
        )
        conversation_mode = returned_mode

    memory_updates = normalize_memory_updates(
        result.get("memory_updates")
    )

    exercise = normalize_exercise(
        result.get("exercise"),
        conversation_mode,
        translation,
    )

    async with db_pool.acquire() as conn:

        (
            user_message_id,
            assistant_message_id,
        ) = await save_message(
            conn,
            session_id,
            user_text_for_history,
            translation,
            msg_type=msg_type,
            media_url=media_url,
            exercise=None,
        )

    await refresh_chat_memory(
        session_id,
        memory_updates,
    )

    return {
        "translation": translation,
        "exercise": exercise,
        "media_url": media_url,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "mode": conversation_mode,
    }


# ============================================================
# TEXT
# ============================================================

async def process_text(
    text: str,
    session_id: uuid.UUID,
    learner_level_hint="unknown",
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
        learner_level_hint=learner_level_hint,
    )


# ============================================================
# /api/message
# ============================================================

@app.post("/api/welcome-exercise")
async def generate_welcome_exercise(
    req: Request,
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form(
        "unknown"
    ),
    preferred_exercise_type: Optional[str] = Form(None),
):
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    existing = await get_welcome_exercise(session_id)

    existing_question = str(
        (existing or {}).get("question") or ""
    ).lower()

    generic_greeting = any(
        marker in existing_question
        for marker in (
            "你好",
            "nǐ hǎo",
            "ни хао",
            "hola",
            "привет",
        )
    )

    if existing and not generic_greeting:
        await save_welcome_exercise(
            session_id,
            existing,
        )

        return {
            "exercise": existing,
            "session_id": session_id_str,
        }

    target_lang, _ = await get_user_settings(session_id)

    async with db_pool.acquire() as conn:
        recent_rows = await get_recent_history(
            conn,
            session_id,
            20,
        )
        chat_summary, _ = await get_chat_memory(
            conn,
            session_id,
        )

        used_exercises = await get_recent_exercises(
            conn,
            session_id,
        )

    context_parts = []

    if chat_summary:
        context_parts.append(
            f"Сохранённое обобщение:\n{chat_summary}"
        )

    if recent_rows:
        context_parts.append(
            "История сообщений:\n" + "\n".join(
                f"{row['role']}: {str(row['content'] or '')[:500]}"
                for row in recent_rows
                if str(row['content'] or '').strip()
            )
        )

    prompt = get_exercise_prompt(
        target_lang,
        normalize_learner_level_hint(
            learner_level_hint
        ),
        learning_context="\n\n".join(context_parts),
        used_exercises="\n".join(
            f"- {question}"
            for question in used_exercises
        ),
        preferred_exercise_type=(
            preferred_exercise_type
            if preferred_exercise_type in (
                "matching_pairs",
                "yes_no",
            )
            else detect_preferred_exercise_type(
                chat_summary
            )
        ),
    )

    result = await call_openrouter(
        [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": (
                    "Создай welcome-упражнение для нового шага. "
                    "Не привязывай его к последнему переводу: "
                    "выбери простую интересную тему или частотное "
                    "выражение, подходящее уровню пользователя. "
                    "Не используй стандартный пример «你好 (nǐ hǎo) "
                    "означает «привет»» и не начинай всегда с приветствия. "
                    "Выбери другую тему: еда, покупки, транспорт, "
                    "время, числа, повседневные действия или интересы "
                    "пользователя."
                ),
            },
        ],
        model=TEXT_MODEL,
        temperature=TRANSLATOR_TEMPERATURE,
    )

    exercise = normalize_exercise(
        result.get("exercise"),
        "translator",
        "",
    )

    await save_welcome_exercise(
        session_id,
        exercise,
    )

    return {
        "exercise": exercise,
        "session_id": session_id_str,
    }

@app.post("/api/message")
async def message(
    req: Request,
    text: Optional[str] = Form(None),
    file: UploadFile = File(None),
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form(
        "unknown"
    ),
    welcome_exercises: Optional[str] = Form(
        None
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

    saved_welcome_exercises = []

    if welcome_exercises:
        try:
            parsed_welcome = json.loads(welcome_exercises)

            if isinstance(parsed_welcome, dict):
                parsed_welcome = [parsed_welcome]

            if isinstance(parsed_welcome, list):
                saved_welcome_exercises = [
                    item
                    for item in parsed_welcome
                    if isinstance(item, dict)
                ]
        except Exception:
            saved_welcome_exercises = []

    if not saved_welcome_exercises:
        pending_welcome = await get_welcome_exercise(
            session_id
        )

        if pending_welcome:
            saved_welcome_exercises = [
                pending_welcome
            ]

    async def finalize_welcome_exercises(result):
        if saved_welcome_exercises:
            await attach_welcome_exercises_to_message(
                session_id,
                result.get("assistant_message_id"),
                saved_welcome_exercises,
            )

        await clear_welcome_exercise(session_id)

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

                img.thumbnail(
                    (
                        MAX_IMAGE_SIZE,
                        MAX_IMAGE_SIZE,
                    ),
                    Image.LANCZOS,
                )

                buffer = io.BytesIO()

                img.save(
                    buffer,
                    format="JPEG",
                    quality=JPEG_QUALITY,
                )

                jpeg_bytes = (
                    buffer.getvalue()
                )

            except Exception as e:

                print(
                    f"Image processing error: {e}"
                )

                raise HTTPException(
                    status_code=400,
                    detail="Invalid image file",
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
                        "User sent an image. "
                        "Extract any text and "
                        "translate it. Do not "
                        "start a discussion about "
                        "the photo."
                    ),
                },
            ]

            # ------------------------------------------------
            # OPENROUTER FIRST
            # ------------------------------------------------

            result = await process_message(
                user_content,
                session_id,
                msg_type="image",
                media_url=None,
                user_text_for_history="",
                learner_level_hint=learner_level_hint,
            )

            # ------------------------------------------------
            # SUPABASE IN BACKGROUND
            # ------------------------------------------------

            asyncio.create_task(
                upload_image_and_update_history(
                    jpeg_bytes,
                    result["user_message_id"],
                )
            )

            await finalize_welcome_exercises(result)

            return {
                "translation": result[
                    "translation"
                ],
                "exercise": result.get(
                    "exercise"
                ),
                "media_url": None,
                "assistant_message_id": result[
                    "assistant_message_id"
                ],
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

            # ------------------------------------------------
            # IMPORTANT:
            #
            # Transcription is needed before AI.
            #
            # Storage is independent and does not need
            # to block transcription.
            # ------------------------------------------------

            transcription = (
                await transcribe_audio(
                    contents,
                    content_type,
                    filename,
                )
            )

            result = await process_message(
                [
                    {
                        "type": "text",
                        "text": (
                            "User sent an audio "
                            "message.\n\n"
                            "Transcription:\n"
                            f"{transcription}"
                        ),
                    }
                ],
                session_id,
                msg_type="audio",
                media_url=None,
                user_text_for_history=(
                    transcription
                ),
                learner_level_hint=learner_level_hint,
            )

            async def upload_audio():

                try:

                    url = await upload_to_supabase(
                        contents,
                        storage_content_type,
                        audio_format,
                    )

                    await update_message_media_url(
                        result["user_message_id"],
                        url,
                    )

                    print(
                        "Background audio upload "
                        "completed:",
                        url,
                    )

                except Exception as e:

                    print(
                        "Background audio upload "
                        f"failed: {e}"
                    )

            asyncio.create_task(
                upload_audio()
            )

            await finalize_welcome_exercises(result)

            return {
                "translation": result[
                    "translation"
                ],
                "exercise": result.get(
                    "exercise"
                ),
                "media_url": None,
                "assistant_message_id": result[
                    "assistant_message_id"
                ],
                "transcription": transcription,
                "session_id": session_id_str,
            }

        # ====================================================
        # UNSUPPORTED
        # ====================================================

        else:

            raise HTTPException(
                status_code=400,
                detail="Unsupported file type.",
            )

    # ========================================================
    # TEXT
    # ========================================================

    elif text and text.strip():

        result = await process_text(
            text.strip(),
            session_id,
            learner_level_hint=learner_level_hint,
        )

        await finalize_welcome_exercises(result)

        return {
            "translation": result[
                "translation"
            ],
            "exercise": result.get(
                "exercise"
            ),
            "media_url": None,
            "assistant_message_id": result[
                "assistant_message_id"
            ],
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


@app.post("/api/exercise")
async def generate_next_exercise(
    req: Request,
    translation: str = Form(""),
    source_text: str = Form(""),
    assistant_message_id: Optional[int] = Form(None),
    answered_exercise: str = Form(""),
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form(
        "unknown"
    ),
):
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    target_lang, conversation_mode = await get_user_settings(
        session_id
    )

    async with db_pool.acquire() as conn:
        recent_rows = await get_recent_history(
            conn,
            session_id,
            20,
        )
        chat_summary, _ = await get_chat_memory(
            conn,
            session_id,
        )

        used_exercises = await get_recent_exercises(
            conn,
            session_id,
        )

    learning_context_parts = []

    if chat_summary:
        learning_context_parts.append(
            f"Сохранённое обобщение:\n{chat_summary}"
        )

    if recent_rows:
        recent_text = []

        for row in recent_rows:
            content = str(row["content"] or "").strip()

            if content:
                recent_text.append(
                    f"{row['role']}: {content[:500]}"
                )

        if recent_text:
            learning_context_parts.append(
                "Последние сообщения для выявления повторяющихся "
                "тем:\n" + "\n".join(recent_text)
            )

    learning_context = "\n\n".join(
        learning_context_parts
    )

    if assistant_message_id and answered_exercise:
        try:
            answered = json.loads(answered_exercise)

            if isinstance(answered, dict):
                async with db_pool.acquire() as conn:
                    raw = await conn.fetchval(
                        """
                        SELECT exercise_data
                        FROM chat_history
                        WHERE id = $1
                          AND session_id = $2
                          AND role = 'assistant'
                        """,
                        assistant_message_id,
                        session_id,
                    )

                    saved = []

                    if raw:
                        saved = (
                            json.loads(raw)
                            if isinstance(raw, str)
                            else raw
                        )

                    if isinstance(saved, dict):
                        saved = [saved]

                    if not isinstance(saved, list):
                        saved = []

                    saved.append(answered)

                    await conn.execute(
                        """
                        UPDATE chat_history
                        SET exercise_data = $1
                        WHERE id = $2
                          AND session_id = $3
                          AND role = 'assistant'
                        """,
                        json.dumps(
                            saved,
                            ensure_ascii=False,
                        ),
                        assistant_message_id,
                        session_id,
                    )
        except Exception as error:
            print(
                f"Exercise history save failed: {error}"
            )

    prompt = get_exercise_prompt(
        target_lang,
        normalize_learner_level_hint(
            learner_level_hint
        ),
        learning_context=learning_context,
        used_exercises="\n".join(
            f"- {question}"
            for question in used_exercises
        ),
        preferred_exercise_type=detect_preferred_exercise_type(
            chat_summary
        ),
    )

    context = (
        f"Исходная фраза пользователя:\n{source_text}\n\n"
        f"Перевод:\n{translation}"
    )

    result = await call_openrouter(
        [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": context,
                    }
                ],
            },
        ],
        model=TEXT_MODEL,
        temperature=TRANSLATOR_TEMPERATURE,
    )

    return {
        "exercise": normalize_exercise(
            result.get("exercise"),
            "translator",
            translation,
        )
    }


# ============================================================
# HISTORY
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
                    id,
                    role,
                    content,
                    message_type,
                    media_url,
                    exercise_data
                FROM chat_history
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                session_uuid,
            )

            history = []

            for r in rows:
                exercise = None
                raw_exercise = r["exercise_data"]

                if raw_exercise:
                    try:
                        if isinstance(
                            raw_exercise,
                            str,
                        ):
                            exercise = json.loads(
                                raw_exercise
                            )
                        elif isinstance(
                            raw_exercise,
                            dict,
                        ):
                            exercise = raw_exercise
                    except Exception:
                        exercise = None

                if not isinstance(exercise, (dict, list)):
                    exercise = None

                history.append(
                    {
                        "id": r["id"],
                        "role": r["role"],
                        "content": r["content"],
                        "message_type": (
                            r["message_type"]
                            or "text"
                        ),
                        "media_url": (
                            r["media_url"]
                        ),
                        "exercise": exercise,
                    }
                )

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
