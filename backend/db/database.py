import ssl
import json
import uuid
from typing import Optional, Tuple, List, Dict, Any
import asyncpg

from backend.core.config import (
    DATABASE_URL,
    DEFAULT_LANGUAGE,
    DEFAULT_CONVERSATION_MODE,
    WELCOME_MESSAGE_CONTENT,
)

db_pool = None

async def init_db(app):
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

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory (
                    session_id UUID PRIMARY KEY,
                    chat_summary TEXT NOT NULL DEFAULT '',
                    summary_message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # --- PERFORMANCE OPTIMIZATION: Database Indexes ---
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_history_session_created
                ON chat_history (session_id, created_at DESC, id DESC)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_history_role
                ON chat_history (session_id, role)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_history_exercise
                ON chat_history (session_id) WHERE exercise_data IS NOT NULL
                """
            )

        print("База данных успешно подключена и проиндексирована!")

    except Exception as e:
        print(f"DB Error: {e}")

async def close_db():
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None

def get_session_id(
    req,
    fallback_session_id: Optional[str] = None,
):
    return (
        req.headers.get("X-Session-Id")
        or fallback_session_id
        or req.query_params.get("session_id")
        or str(uuid.uuid4())
    )

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
        exercise_json = json.dumps(exercise, ensure_ascii=False)

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
        print(f"media_url updated for message {message_id}")
    except Exception as e:
        print(f"Failed to update media_url for message {message_id}: {e}")

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

def detect_preferred_exercise_type(chat_summary: str) -> str:
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

async def get_user_settings(session_id: uuid.UUID) -> tuple[str, str]:
    if not db_pool:
        return DEFAULT_LANGUAGE, DEFAULT_CONVERSATION_MODE

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
                language = row["target_language_name"] or DEFAULT_LANGUAGE
                mode = normalize_conversation_mode(row["conversation_mode"])
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
        print(f"Error getting user settings: {e}")

    return DEFAULT_LANGUAGE, DEFAULT_CONVERSATION_MODE

async def get_user_language(session_id: uuid.UUID) -> str:
    language, _ = await get_user_settings(session_id)
    return language

async def save_conversation_mode(session_id: uuid.UUID, mode: str):
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
                    conversation_mode = EXCLUDED.conversation_mode
                """,
                session_id,
                DEFAULT_LANGUAGE,
                mode,
            )
    except Exception as e:
        print(f"Error saving conversation_mode: {e}")

async def save_welcome_exercise(session_id: uuid.UUID, exercise: dict):
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

async def get_welcome_exercise(session_id: uuid.UUID):
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

async def clear_welcome_exercise(session_id: uuid.UUID):
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

async def get_recent_history(
    conn,
    session_id: uuid.UUID,
    limit: int = 20,
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

async def save_chat_summary(
    session_id: uuid.UUID,
    summary: str,
):
    summary = (summary or "").strip()
    if not summary:
        return

    async with db_pool.acquire() as conn:
        message_count = await get_message_count(conn, session_id)
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
                summary_message_count = EXCLUDED.summary_message_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            session_id,
            summary,
            message_count,
        )
