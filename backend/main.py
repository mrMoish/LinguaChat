import os
import uuid
import json
import base64
import ssl
import io
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncpg
from dotenv import load_dotenv
from PIL import Image, ImageOps
import pillow_heif

from prompts import get_text_prompt, get_image_prompt

load_dotenv()
pillow_heif.register_heif_opener()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешить все домены (для MVP это нормально)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Session-Id"],
)

DEFAULT_LANGUAGE = "Chinese"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
STORAGE_BUCKET = "chat-images"

TEXT_MODEL = "openai/gpt-5.6-luna" # "deepseek/deepseek-chat"
VISION_MODEL = "openai/gpt-5.6-luna" # google/gemini-2.0-flash-exp:free # google/gemini-2.5-flash-lite # google/gemini-3.8-flash

db_pool = None


@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            db_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=5, timeout=60,
                command_timeout=60, max_inactive_connection_lifetime=60,
                ssl=ctx, statement_cache_size=0
            )
            async with db_pool.acquire() as conn:
                await conn.execute(
                    '''CREATE TABLE IF NOT EXISTS chat_history (id SERIAL PRIMARY KEY, session_id UUID NOT NULL, role VARCHAR(50) NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)''')
                await conn.execute(
                    '''CREATE TABLE IF NOT EXISTS user_settings (session_id UUID PRIMARY KEY, target_language_name VARCHAR(100) DEFAULT 'Chinese')''')
                await conn.execute(
                    "ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS message_type VARCHAR(20) DEFAULT 'text'")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS media_url TEXT")
            print("База данных успешно подключена!")
        except Exception as e:
            print(f"DB Error: {e}")


@app.on_event("shutdown")
async def shutdown():
    if db_pool: await db_pool.close()


def get_session_id(req: Request):
    return req.headers.get("X-Session-Id") or str(uuid.uuid4())


async def save_message(conn, session_id, user_text, ai_reply, msg_type="text", media_url=None):
    await conn.execute(
        "INSERT INTO chat_history (session_id, role, content, message_type, media_url) VALUES ($1, $2, $3, $4, $5)",
        session_id, "user", user_text, msg_type, media_url)
    await conn.execute(
        "INSERT INTO chat_history (session_id, role, content, message_type, media_url) VALUES ($1, $2, $3, $4, $5)",
        session_id, "assistant", ai_reply, "text", None)


async def get_user_language(session_id: uuid.UUID) -> str:
    if not db_pool: return DEFAULT_LANGUAGE
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT target_language_name FROM user_settings WHERE session_id = $1",
                                      session_id)
            if row and row["target_language_name"]: return row["target_language_name"]
            await conn.execute(
                "INSERT INTO user_settings (session_id, target_language_name) VALUES ($1, $2) ON CONFLICT (session_id) DO NOTHING",
                session_id, DEFAULT_LANGUAGE)
    except Exception as e:
        print(f"Error getting language: {e}")
    return DEFAULT_LANGUAGE


async def call_openrouter(messages: list, model: str):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "response_format": {"type": "json_object"}, "temperature": 0.7}
    async with httpx.AsyncClient() as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
        if response.status_code != 200:
            print(f"OpenRouter Error {response.status_code}: {response.text}")
            if response.status_code == 429: raise HTTPException(status_code=429, detail="ИИ перегружен.")
            raise HTTPException(status_code=response.status_code, detail="Ошибка ИИ.")
        data = response.json()
        if "choices" not in data or not data["choices"]: raise HTTPException(status_code=500,
                                                                             detail="ИИ не вернул ответ.")
        raw_text = data["choices"][0]["message"]["content"].strip()
        try:
            return json.loads(raw_text).get("translation", "Ошибка обработки ИИ.")
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Ошибка формата ИИ.")


async def upload_to_supabase(jpeg_bytes: bytes) -> str:
    file_name = f"{uuid.uuid4().hex}.jpg"
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{file_name}"
    headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "Content-Type": "image/jpeg", "x-upsert": "true"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(upload_url, headers=headers, content=jpeg_bytes, timeout=30.0)
        if resp.status_code != 200:
            print(f"Supabase Upload Error: {resp.text}")
            raise HTTPException(500, "Failed to upload to Supabase Storage")
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{file_name}"


RECENT_HISTORY_LIMIT = 8  # сколько последних сообщений диалога передавать модели для определения намерения


async def get_recent_history(conn, session_id: uuid.UUID, limit: int = RECENT_HISTORY_LIMIT):
    """Последние сообщения диалога (в хронологическом порядке) — нужны, чтобы модель могла
    определить, отвечает ли пользователь на предыдущий вопрос AI, а не только по языку сообщения."""
    rows = await conn.fetch(
        "SELECT role, content FROM chat_history WHERE session_id = $1 AND message_type = 'text' "
        "ORDER BY created_at DESC LIMIT $2",
        session_id, limit
    )
    return list(reversed(rows))


async def process_text(text: str, session_id: uuid.UUID) -> dict:
    target_lang = await get_user_language(session_id)
    async with db_pool.acquire() as conn:
        history_rows = await get_recent_history(conn, session_id)

    history_messages = [{"role": r["role"], "content": r["content"]} for r in history_rows]
    if not history_messages:
        # Первое сообщение в диалоге — своего последнего вопроса у AI ещё не было
        history_messages = [{"role": "assistant", "content": "Какой у вас уровень китайского?"}]

    print("history_messages: ", history_messages)
    print('target_lang: ', target_lang)
    messages = [
        {"role": "system", "content": get_text_prompt(target_lang)},
        *history_messages,
        {"role": "user", "content": [{"type": "text", "text": text}]}
    ]
    translation = await call_openrouter(messages, model=TEXT_MODEL)
    async with db_pool.acquire() as conn:
        await save_message(conn, session_id, text, translation, msg_type="text")
    return {"translation": translation}


async def process_image(file: UploadFile, session_id: uuid.UUID) -> dict:
    target_lang = await get_user_language(session_id)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024: raise HTTPException(status_code=413, detail="Файл слишком большой.")

    try:
        img = Image.open(io.BytesIO(contents))
        img = ImageOps.exif_transpose(img)  # ПРИМЕНЯЕМ EXIF ОРИЕНТАЦИЮ
        img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        jpeg_bytes = buffer.getvalue()
    except Exception as img_err:
        print(f"Image processing error: {img_err}")
        raise HTTPException(status_code=400, detail="Invalid image file")

    media_url = await upload_to_supabase(jpeg_bytes)
    image_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
    user_content = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]
    messages = [
        {"role": "system", "content": get_image_prompt(target_lang)},
        {"role": "user", "content": user_content}
    ]
    translation = await call_openrouter(messages, model=VISION_MODEL)
    async with db_pool.acquire() as conn:
        await save_message(conn, session_id, "", translation, msg_type="image", media_url=media_url)
    return {"translation": translation, "media_url": media_url}


@app.post("/api/message")
async def message(req: Request, text: Optional[str] = Form(None), file: UploadFile = File(None)):
    if not OPENROUTER_API_KEY: raise HTTPException(status_code=500, detail="API Key not configured")
    if not db_pool: raise HTTPException(status_code=503, detail="База данных не подключена.")
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)
    if file:
        if file.content_type and file.content_type.startswith("image/"):
            result = await process_image(file, session_id)
            return {"session_id": session_id_str, "translation": result["translation"],
                    "media_url": result["media_url"]}
        else:
            raise HTTPException(status_code=400, detail="Только изображения.")
    elif text:
        result = await process_text(text, session_id)
        return {"session_id": session_id_str, "translation": result["translation"]}
    else:
        raise HTTPException(status_code=400, detail="Сообщение пусто.")


@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content, message_type, media_url FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id)
            history = [{"role": r["role"], "content": r["content"], "message_type": r["message_type"],
                        "media_url": r["media_url"]} for r in rows]
            return {"session_id": session_id_str, "history": history}
    return {"session_id": session_id_str, "history": []}


@app.get("/")
def read_root():
    return {"status": "Backend is running"}