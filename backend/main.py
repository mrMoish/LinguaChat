import os
import uuid
import json
import base64
import ssl
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncpg
from dotenv import load_dotenv

from prompts import get_translation_prompt, get_image_analysis_prompt

from PIL import Image
import pillow_heif
import io

# Регистрируем плагин HEIF, чтобы Pillow мог открывать фото с iPhone
pillow_heif.register_heif_opener()

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
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv("DATABASE_URL")

# Модели
TEXT_MODEL = "deepseek/deepseek-chat"
VISION_MODEL = "openai/gpt-5.6-luna" # "google/gemini-2.5-flash-lite" # google/gemini-3.8-flash # "google/gemini-2.0-flash-exp:free"
DEFAULT_LANGUAGE = "китайский"

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
                DATABASE_URL,
                min_size=1, max_size=5, timeout=60,
                command_timeout=60, max_inactive_connection_lifetime=60,
                ssl=ctx,
                statement_cache_size=0
            )
            async with db_pool.acquire() as conn:
                await conn.execute(
                    '''CREATE TABLE IF NOT EXISTS chat_history (id SERIAL PRIMARY KEY, session_id UUID NOT NULL, role VARCHAR(50) NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)''')
                await conn.execute(
                    '''CREATE TABLE IF NOT EXISTS user_settings (session_id UUID PRIMARY KEY, target_language_name VARCHAR(100) DEFAULT 'китайский')''')
            print("База данных успешно подключена!")
        except Exception as e:
            print(f"DB Error: {e}")
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан!")


@app.on_event("shutdown")
async def shutdown():
    if db_pool: await db_pool.close()


def get_session_id(req: Request):
    return req.headers.get("X-Session-Id") or str(uuid.uuid4())


async def save_message(conn, session_id, user_text, ai_reply):
    await conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)", session_id, "user",
                       user_text)
    await conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)", session_id,
                       "assistant", ai_reply)


async def get_user_language(session_id: uuid.UUID) -> str:
    if not db_pool: return DEFAULT_LANGUAGE
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT target_language_name FROM user_settings WHERE session_id = $1",
                                      session_id)
            if row and row["target_language_name"]:
                return row["target_language_name"]
            await conn.execute(
                "INSERT INTO user_settings (session_id, target_language_name) VALUES ($1, $2) ON CONFLICT (session_id) DO NOTHING",
                session_id, DEFAULT_LANGUAGE)
    except Exception as e:
        print(f"Error getting language: {e}")
    return DEFAULT_LANGUAGE


async def call_openrouter(messages: list, model: str):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}

    async with httpx.AsyncClient() as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
        if response.status_code != 200:
            # Выводим точный текст ошибки от OpenRouter в терминал
            print(f"--- OpenRouter Error {response.status_code} ---\n{response.text}\n-----------------------------")
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


async def process_text(text: str, session_id: uuid.UUID) -> str:
    target_lang = await get_user_language(session_id)
    messages = [{"role": "system", "content": get_translation_prompt(target_lang)},
                {"role": "user", "content": [{"type": "text", "text": text}]}]
    translation = await call_openrouter(messages, model=TEXT_MODEL)
    async with db_pool.acquire() as conn:
        await save_message(conn, session_id, text, translation)
    return translation


async def process_image(file: UploadFile, session_id: uuid.UUID) -> str:
    target_lang = await get_user_language(session_id)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024: raise HTTPException(status_code=413, detail="Файл слишком большой.")

    # КОНВЕРТАЦИЯ В JPEG (чтобы избежать ошибок формата HEIC и др.)
    try:
        img = Image.open(io.BytesIO(contents))
        img = img.convert('RGB')  # Убираем альфа-канал, если он есть (JPEG его не поддерживает)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        jpeg_bytes = buffer.getvalue()
        content_type = 'image/jpeg'
    except Exception as img_err:
        print(f"Image conversion error: {img_err}")
        # Если вдруг Pillow не смог открыть файл, отправляем оригинал (fallback)
        jpeg_bytes = contents
        content_type = file.content_type or 'image/jpeg'

    image_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
    user_content = [{"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_base64}"}}]

    messages = [
        {"role": "system", "content": get_image_analysis_prompt(target_lang)},
        {"role": "user", "content": user_content}
    ]
    translation = await call_openrouter(messages, model=VISION_MODEL)

    async with db_pool.acquire() as conn:
        await save_message(conn, session_id, "📷 Фото для перевода", translation)
    return translation


@app.post("/api/message")
async def message(req: Request, text: Optional[str] = Form(None), file: UploadFile = File(None)):
    if not OPENROUTER_API_KEY: raise HTTPException(status_code=500, detail="API Key not configured")
    if not db_pool: raise HTTPException(status_code=503, detail="База данных не подключена.")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if file:
        if file.content_type and file.content_type.startswith("image/"):
            translation = await process_image(file, session_id)
        else:
            raise HTTPException(status_code=400, detail="Только изображения.")
    elif text:
        translation = await process_text(text, session_id)
    else:
        raise HTTPException(status_code=400, detail="Сообщение пусто.")

    return {"session_id": session_id_str, "translation": translation}


@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC", session_id)
            return {"session_id": session_id_str,
                    "history": [{"role": r["role"], "content": r["content"]} for r in rows]}
    return {"session_id": session_id_str, "history": []}


@app.get("/")
def read_root(): return {"status": "Backend is running"}