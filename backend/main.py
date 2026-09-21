import os
import ssl
import uuid
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv

from prompts import get_translation_prompt

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://trachat.vercel.app",
        "https://linguachat-x26d.onrender.com"
    ],
    allow_methods=["*"],
    allow_headers=["*", "X-Session-Id"],
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "deepseek/deepseek-chat" # "openai/gpt-5.6-luna" #
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv("DATABASE_URL")

# Язык обучения по умолчанию — теперь английский (был китайский)
DEFAULT_LANGUAGE_CODE = "es"
DEFAULT_LANGUAGE_NAME = "испанский (Аргентина)"
DEFAULT_LANGUAGE_LOCALE = "es-AR"

# Уровень пользователя известен заранее и зафиксирован — экран/логика оценки уровня не нужны
USER_LEVEL = "A2"

RECENT_HISTORY_LIMIT = 8

db_pool = None


def build_ssl_arg():
    """
    Определяет, нужен ли SSL для подключения к Postgres.
    DB_SSL_MODE=disable -> без SSL. DB_SSL_MODE=require -> с SSL.
    По умолчанию (auto): localhost/127.0.0.1/::1 в DATABASE_URL -> без SSL, иначе -> с SSL
    (подходит для managed Postgres вроде Render/Supabase/Neon).
    """
    mode = os.getenv("DB_SSL_MODE", "auto").lower()

    if mode == "disable":
        return None

    if mode == "auto":
        if not DATABASE_URL:
            return None
        local_markers = ("localhost", "127.0.0.1", "::1")
        if any(marker in DATABASE_URL for marker in local_markers):
            return None

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=5, timeout=60,
                command_timeout=60, max_inactive_connection_lifetime=60,
                ssl=build_ssl_arg(),
                # Многие managed Postgres (Supabase pooler, pgbouncer в режиме transaction/statement
                # pooling и т.п.) не поддерживают серверные prepared statements между запросами —
                # без этого asyncpg падает с DuplicatePreparedStatementError. Отключаем кэш
                # подготовленных запросов на стороне asyncpg — рекомендация из самого asyncpg.
                statement_cache_size=0
            )
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        role VARCHAR(50) NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS user_settings (
                        session_id UUID PRIMARY KEY,
                        target_language_code VARCHAR(20),
                        target_language_name VARCHAR(100)
                    )
                ''')
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language_locale VARCHAR(20)")

                # Логика "уровень из диалога" и "известный материал" относилась к прежней
                # концепции друга-собеседника и больше не нужна для простого переводчика.
                await conn.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS language_level")
                await conn.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS known_material")
        except Exception as e:
            print(f"DB Error: {e}")
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан!")


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()


class MessageRequest(BaseModel):
    message: str


def get_session_id(req: Request):
    session_id_str = req.headers.get("X-Session-Id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    return session_id_str


async def call_openrouter(messages):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL_NAME, "messages": messages, "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient() as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
        response.raise_for_status()
        return response.json()


def handle_llm_error(e: Exception, context: str):
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 429:
            raise HTTPException(status_code=429, detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    print(f"{context}: {str(e)}")
    raise HTTPException(status_code=500, detail=str(e))


async def build_recent_summary(session_id):
    """Недавние сообщения пользователя — используются, чтобы понять, какие слова/выражения
    он уже успешно употреблял (сигнал, что они ему знакомы для разметки B1)."""
    if not db_pool:
        return "История пуста."
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2",
            session_id, RECENT_HISTORY_LIMIT
        )
    if not rows:
        return "История пуста."
    ordered = list(reversed(rows))
    return "\n".join(f"{r['role']}: {r['content']}" for r in ordered)


async def ensure_settings(conn, session_id):
    row = await conn.fetchrow(
        "SELECT target_language_code, target_language_name, language_locale FROM user_settings WHERE session_id = $1",
        session_id
    )
    if row:
        return row
    await conn.execute(
        "INSERT INTO user_settings (session_id, target_language_code, target_language_name, language_locale) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (session_id) DO NOTHING",
        session_id, DEFAULT_LANGUAGE_CODE, DEFAULT_LANGUAGE_NAME, DEFAULT_LANGUAGE_LOCALE
    )
    return await conn.fetchrow(
        "SELECT target_language_code, target_language_name, language_locale FROM user_settings WHERE session_id = $1",
        session_id
    )


@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if not db_pool:
        return {"session_id": session_id_str, "history": []}

    async with db_pool.acquire() as conn:
        await ensure_settings(conn, session_id)
        rows = await conn.fetch(
            "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
            session_id
        )
        history = [{"role": r["role"], "content": r["content"]} for r in rows]

    return {"session_id": session_id_str, "history": history}


@app.post("/api/message")
async def message(request: MessageRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    async with db_pool.acquire() as conn:
        settings = await ensure_settings(conn, session_id)

    target_lang_name = settings["target_language_name"] or DEFAULT_LANGUAGE_NAME
    recent_summary = await build_recent_summary(session_id)

    system_content = get_translation_prompt(target_lang_name, USER_LEVEL, recent_summary)
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": request.message}
    ]

    try:
        data = await call_openrouter(messages)
        raw_text = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)
    except Exception as e:
        handle_llm_error(e, "Translation Error")
        return

    translation = parsed.get("translation", "") or ""

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chat_history (session_id, role, content) VALUES ($1, 'user', $2)",
            session_id, request.message
        )
        await conn.execute(
            "INSERT INTO chat_history (session_id, role, content) VALUES ($1, 'assistant', $2)",
            session_id, translation
        )

    return {"session_id": session_id_str, "translation": translation}


@app.get("/")
def read_root():
    return {"status": "Backend is running"}