import os
import uuid
import json
import io
import base64
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv
from PIL import Image
import pillow_heif
from pypdf import PdfReader

# Импорты промптов
from prompts import (
    SETUP_SYSTEM_PROMPT,
    get_translation_prompt,
    get_lesson_prompt,
    get_lesson_from_history_prompt,
    get_assessment_prompt,
    get_single_word_prompt,
    get_lesson_evaluation_prompt
)
import random

load_dotenv()

# Регистрируем плагин HEIF для Pillow (чтобы открывать фото с iPhone)
pillow_heif.register_heif_opener()

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
MODEL_NAME = "deepseek/deepseek-chat"
AUDIO_MODEL_NAME = "google/gemini-2.5-flash-lite"  # Модель для аудио и фото
DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None


@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                timeout=60,
                command_timeout=60,
                max_inactive_connection_lifetime=60
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
                        target_language_code VARCHAR(10),
                        target_language_name VARCHAR(100)
                    )
                ''')
                await conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_level INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS is_lesson BOOLEAN DEFAULT FALSE")
                await conn.execute(
                    "ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS is_evaluation BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS source_language VARCHAR(50)")

                # Колонка для общей суммы трат пользователя
                await conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS total_cost NUMERIC(10, 5) DEFAULT 0.0")

                # Таблица для логов брошенных уроков
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS lesson_logs (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для оригинальных текстов PDF
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        filename VARCHAR(255),
                        original_text TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для детальной статистики API запросов
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS api_usage_logs (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        endpoint VARCHAR(50) NOT NULL,
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost NUMERIC(10, 5) DEFAULT 0.0,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
        except Exception as e:
            print(f"DB Error: {e}")
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан!")


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()


# --- МОДЕЛИ PYDANTIC ---
class ChatRequest(BaseModel):
    message: str


class LessonRequest(BaseModel):
    user_text: Optional[str] = None
    ai_text: Optional[str] = None
    use_history: bool = False


class CheckLessonRequest(BaseModel):
    lesson_text: str
    user_answer: str


class SetLevelRequest(BaseModel):
    level: str


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_session_id(req: Request):
    session_id_str = req.headers.get("X-Session-Id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    return session_id_str


async def log_api_usage(conn, session_id, endpoint, usage_data):
    if not usage_data: return
    prompt_tokens = usage_data.get("prompt_tokens", 0)
    completion_tokens = usage_data.get("completion_tokens", 0)
    total_tokens = usage_data.get("total_tokens", 0)
    cost = usage_data.get("cost", 0.0)

    await conn.execute(
        "INSERT INTO api_usage_logs (session_id, endpoint, prompt_tokens, completion_tokens, total_tokens, cost) VALUES ($1, $2, $3, $4, $5, $6)",
        session_id, endpoint, prompt_tokens, completion_tokens, total_tokens, cost
    )
    await conn.execute(
        "UPDATE user_settings SET total_cost = total_cost + $1 WHERE session_id = $2",
        cost, session_id
    )


# --- ЭНДПОИНТЫ ---

@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_code = None
    if db_pool:
        async with db_pool.acquire() as conn:
            row_settings = await conn.fetchrow("SELECT target_language_code FROM user_settings WHERE session_id = $1",
                                               session_id)
            if row_settings:
                target_lang_code = row_settings["target_language_code"]

            # Проверяем последнее сообщение (если это урок - переносим в логи)
            last_row = await conn.fetchrow(
                "SELECT id, is_lesson, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
                session_id
            )
            if last_row and last_row["is_lesson"]:
                await conn.execute("DELETE FROM chat_history WHERE id = $1", last_row["id"])
                await conn.execute(
                    "INSERT INTO lesson_logs (session_id, content) VALUES ($1, $2)",
                    session_id, last_row["content"]
                )

            rows = await conn.fetch(
                "SELECT role, content, is_lesson, is_evaluation, source_language FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id
            )
            history = [{
                "role": row["role"],
                "content": row["content"],
                "isLesson": row["is_lesson"],
                "isEvaluation": row["is_evaluation"],
                "source_language": row["source_language"]
            } for row in rows]

            return {"session_id": session_id_str, "history": history, "target_language_code": target_lang_code}

    return {"session_id": session_id_str, "history": [], "target_language_code": None}


@app.post("/api/chat")
async def chat(request: ChatRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_code = None
    target_lang_name = None
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT target_language_code, target_language_name, total_cost FROM user_settings WHERE session_id = $1",
                session_id)
            if row:
                target_lang_code = row["target_language_code"]
                target_lang_name = row["target_language_name"]

                # Проверка лимита средств (1$)
                if row["total_cost"] is not None and row["total_cost"] >= 1.0:
                    spent = round(row["total_cost"], 2)
                    return {
                        "session_id": session_id_str,
                        "reply": f"Вы исчерпали лимит бесплатных запросов, потратив ${spent}. Чтобы продолжить пользоваться переводчиком, купите подписку через техподдержку.",
                        "source_language": "Система",
                        "target_language_code": target_lang_code
                    }

    if not target_lang_code:
        messages = [
            {"role": "system", "content": SETUP_SYSTEM_PROMPT},
            {"role": "user", "content": request.message}
        ]
    else:
        cleaned_message = request.message.strip().replace('.', '').replace(',', '').replace('!', '').replace('?', '')
        is_single_word = len(cleaned_message.split()) == 1

        if is_single_word:
            system_content = get_single_word_prompt(target_lang_name, target_lang_code)
        else:
            system_content = get_translation_prompt(target_lang_name, target_lang_code)

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": request.message}
        ]

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload,
                                         timeout=60.0)
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage")

            raw_text = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw_text)

            source_lang_name = parsed.get("source_language_name", "")

            if not target_lang_code:
                ai_reply = parsed.get("reply", "Ошибка обработки.")
                detected_lang_code = parsed.get("target_language_code")
                detected_lang_name = parsed.get("target_language_name")

                if detected_lang_code and db_pool:
                    async with db_pool.acquire() as conn:
                        await log_api_usage(conn, session_id, "chat_setup", usage)
                        await conn.execute(
                            "INSERT INTO user_settings (session_id, target_language_code, target_language_name, proficiency_level) VALUES ($1, $2, $3, 0) ON CONFLICT (session_id) DO UPDATE SET target_language_code = $2, target_language_name = $3, proficiency_level = 0",
                            session_id, detected_lang_code, detected_lang_name
                        )
                    target_lang_code = detected_lang_code
            else:
                ai_reply = parsed.get("translation", "Ошибка перевода.")

        if db_pool:
            async with db_pool.acquire() as conn:
                await log_api_usage(conn, session_id, "chat", usage)
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, source_language) VALUES ($1, $2, $3, $4)",
                    session_id, "user", request.message, source_lang_name
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_reply
                )

        return {"session_id": session_id_str, "reply": ai_reply, "source_language": source_lang_name,
                "target_language_code": target_lang_code}


    except httpx.HTTPStatusError as e:

        if e.response.status_code == 429:
            print("OpenRouter Rate Limit (429): Слишком много запросов")

            raise HTTPException(status_code=429,
                                detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")

        raise HTTPException(status_code=e.response.status_code, detail=str(e))

    except Exception as e:

        print(f"Check Lesson Error: {str(e)}")

        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/lesson")
async def mini_lesson(request: LessonRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_name = "Китайский (мандаринский)"
    proficiency_level = 0

    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT target_language_name, proficiency_level, total_cost FROM user_settings WHERE session_id = $1",
                session_id)
            if row:
                if row["target_language_name"]:
                    target_lang_name = row["target_language_name"]

                if row["proficiency_level"] is not None:
                    proficiency_level = row["proficiency_level"]
                else:
                    proficiency_level = 0

                if row["total_cost"] is not None and row["total_cost"] >= 1.0:
                    return {"action": "lesson",
                            "lesson": "Вы достигли лимита бесплатных запросов (1$). Пожалуйста, купите подписку через техподдержку."}

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    # ВСЕГДА берем историю из БД для контекста урока
    history_log = "История пуста."
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 12",
                session_id
            )
            if rows:
                history_log = "\n".join([f"{r['role']}: {r['content']}" for r in reversed(rows)])

    question_or_phrase = [('Ответь', 'Question'), ('Переведи', 'Phrase')][random.choice([0, 1])]
    system_prompt = get_lesson_from_history_prompt(target_lang_name, proficiency_level, history_log, question_or_phrase)

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "system", "content": system_prompt}],
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload,
                                         timeout=60.0)
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage")

            parsed = json.loads(data["choices"][0]["message"]["content"].strip())
            lesson_text = parsed.get("lesson_text", "Не удалось создать урок.")

            if db_pool:
                async with db_pool.acquire() as conn:
                    await log_api_usage(conn, session_id, "lesson_generate", usage)
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, is_lesson) VALUES ($1, $2, $3, TRUE)",
                        session_id, "assistant", lesson_text
                    )
                    new_level = min(100, proficiency_level + 5)
                    await conn.execute("UPDATE user_settings SET proficiency_level = $1 WHERE session_id = $2",
                                       new_level, session_id)

            return {"action": "lesson", "lesson": lesson_text}

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print("OpenRouter Rate Limit (429): Слишком много запросов")
            raise HTTPException(status_code=429, detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        print(f"Check Lesson Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/abandon_lesson")
async def abandon_lesson(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if db_pool:
        async with db_pool.acquire() as conn:
            last_row = await conn.fetchrow(
                "SELECT id, is_lesson, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
                session_id
            )
            if last_row and last_row["is_lesson"]:
                await conn.execute("DELETE FROM chat_history WHERE id = $1", last_row["id"])
                await conn.execute(
                    "INSERT INTO lesson_logs (session_id, content) VALUES ($1, $2)",
                    session_id, last_row["content"]
                )

    return {"status": "ok"}


@app.post("/api/check_lesson")
async def check_lesson(request: CheckLessonRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT total_cost FROM user_settings WHERE session_id = $1", session_id)
                if row and row["total_cost"] is not None and row["total_cost"] >= 1.0:
                    return {"grade": "Не понятно", "correct_answer": "Вы достигли лимита. Купите подписку.",
                            "explanation": "Лимит исчерпан."}
        except Exception as db_err:
            print(f"DB connection failed: {db_err}")

    system_prompt = get_lesson_evaluation_prompt(request.lesson_text, request.user_answer)

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "system", "content": system_prompt}],
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload,
                                         timeout=60.0)
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage")

            raw_text = data["choices"][0]["message"]["content"].strip()

            try:
                parsed = json.loads(raw_text)
                grade = parsed.get("grade", "Ошибка")
                explanation = parsed.get("translation_and_explanation", parsed.get("explanation", "Нет пояснения."))
                correct_answer = parsed.get("correct_answer", "")
            except json.JSONDecodeError:
                grade = "Ошибка"
                explanation = raw_text
                correct_answer = ""

        eval_data = {
            "grade": grade,
            "explanation": explanation,
            "correct_answer": correct_answer
        }
        eval_json_str = json.dumps(eval_data, ensure_ascii=False)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    await log_api_usage(conn, session_id, "check_lesson", usage)
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                        session_id, "user", request.user_answer
                    )
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, is_evaluation) VALUES ($1, $2, $3, TRUE)",
                        session_id, "assistant", eval_json_str
                    )
            except Exception as db_err:
                print(f"Database connection failed: {db_err}")

        return {
            "grade": grade,
            "explanation": explanation,
            "correct_answer": correct_answer
        }


    except httpx.HTTPStatusError as e:

        if e.response.status_code == 429:
            print("OpenRouter Rate Limit (429): Слишком много запросов")

            raise HTTPException(status_code=429,
                                detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")

        raise HTTPException(status_code=e.response.status_code, detail=str(e))

    except Exception as e:

        print(f"Check Lesson Error: {str(e)}")

        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/set_level")
async def set_level(request: SetLevelRequest, req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    level_map = {
        "0": 0, "A1": 10, "A2": 25, "B1": 40, "B2": 60, "C1": 80, "C2": 95
    }
    proficiency_level = level_map.get(request.level, 0)

    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE user_settings SET proficiency_level = $1 WHERE session_id = $2",
                               proficiency_level, session_id)

    return {"status": "ok"}


@app.post("/api/upload_pdf")
async def upload_pdf(file: UploadFile = File(...), req: Request = None):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    contents = await file.read()
    reader = PdfReader(io.BytesIO(contents))

    extracted_text = ""
    for page in reader.pages:
        extracted_text += page.extract_text() + "\n"

    extracted_text = extracted_text.strip()
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Не удалось извлечь текст или файл пуст.")

    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO documents (session_id, filename, original_text) VALUES ($1, $2, $3)",
                session_id, file.filename, extracted_text
            )

    chunk_size = 2000
    chunks = [extracted_text[i:i + chunk_size] for i in range(0, len(extracted_text), chunk_size)]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    async def translate_stream():
        full_translation = ""
        async with httpx.AsyncClient() as client:
            for i, chunk in enumerate(chunks):
                system_prompt = """You are a professional translator. Translate the following part of a document to Russian. 
                Output only the translated text without any markdown or comments."""

                payload = {
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": chunk}
                    ]
                }

                try:
                    response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers,
                                                 json=payload, timeout=60.0)
                    response.raise_for_status()
                    data = response.json()
                    translated_chunk = data["choices"][0]["message"]["content"].strip()
                    full_translation += translated_chunk + "\n"
                    yield translated_chunk + "\n"
                except Exception as e:
                    yield f"\n[Ошибка перевода части {i + 1}]\n"

        if db_pool:
            async with db_pool.acquire() as conn:
                user_msg = f"📄 Загружен файл: {file.filename}"
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "user", user_msg
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", full_translation
                )

    return StreamingResponse(translate_stream(), media_type="text/plain")


@app.post("/api/image_translate")
async def image_translate(file: UploadFile = File(...), req: Request = None):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT total_cost FROM user_settings WHERE session_id = $1", session_id)
                if row and row["total_cost"] is not None and row["total_cost"] >= 1.0:
                    return {
                        "reply": "Вы достигли лимита бесплатных запросов (1$). Пожалуйста, купите подписку через техподдержку.",
                        "source_language": "Система"}
        except Exception as db_err:
            print(f"DB connection failed: {db_err}")

    contents = await file.read()

    try:
        img = Image.open(io.BytesIO(contents))
        img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        jpeg_bytes = buffer.getvalue()
        base64_image = base64.b64encode(jpeg_bytes).decode('utf-8')
    except Exception as img_err:
        print(f"Image conversion error: {img_err}")
        base64_image = base64.b64encode(contents).decode('utf-8')

    mime_type = 'image/jpeg'
    data_uri = f"data:{mime_type};base64,{base64_image}"

    prompt_text = """Проанализируй изображение. Что это?
Переведи необрезанный текст на русский язык.
Объедини описание изображения и переведённый текст в одно поле "reply".
Используй Markdown-форматирование внутри поля "reply" для лучшей читаемости.
Определи язык текста на изображении (на русском языке, например: "Английский", "Французский"). Если текста нет, используй "Нет текста".
Верни СТРОГО JSON без markdown:
{
  "source_language_name": "Название языка на русском",
  "reply": "Описание изображения и переведённый текст"
}"""

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload,
                                         timeout=60.0)
            if response.status_code != 200:
                error_text = response.text
                print(f"--- OpenRouter Image Error ---\n{error_text}\n-----------------------------")
                raise HTTPException(status_code=response.status_code, detail=f"OpenRouter API Error: {error_text}")

            data = response.json()
            usage = data.get("usage")
            raw_text = data["choices"][0]["message"]["content"].strip()

            try:
                parsed = json.loads(raw_text)
                ai_reply = parsed.get("reply", "Ошибка обработки ответа.")
                source_lang = parsed.get("source_language_name", "Фото")
            except json.JSONDecodeError:
                ai_reply = raw_text
                source_lang = "Фото"

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    await log_api_usage(conn, session_id, "image_translate", usage)
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, source_language) VALUES ($1, $2, $3, $4)",
                        session_id, "user", "📷 Фото для перевода", source_lang
                    )
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                        session_id, "assistant", ai_reply
                    )
            except Exception as db_err:
                print(f"Database connection failed: {db_err}")

        return {"reply": ai_reply, "source_language": source_lang}


    except httpx.HTTPStatusError as e:

        if e.response.status_code == 429:
            print("OpenRouter Rate Limit (429): Слишком много запросов")

            raise HTTPException(status_code=429,
                                detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")

        raise HTTPException(status_code=e.response.status_code, detail=str(e))

    except Exception as e:

        print(f"Check Lesson Error: {str(e)}")

        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audio_translate")
async def audio_translate(file: UploadFile = File(...), req: Request = None):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT total_cost FROM user_settings WHERE session_id = $1", session_id)
                if row and row["total_cost"] is not None and row["total_cost"] >= 1.0:
                    return {
                        "reply": "Вы достигли лимита бесплатных запросов (1$). Пожалуйста, купите подписку через техподдержку.",
                        "source_language": "Система"}
        except Exception as db_err:
            print(f"DB connection failed: {db_err}")

    target_lang_name = "Русский"
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT target_language_name FROM user_settings WHERE session_id = $1",
                                      session_id)
            if row:
                target_lang_name = row["target_language_name"]

    contents = await file.read()
    base64_audio = base64.b64encode(contents).decode('utf-8')
    mime_type = 'audio/webm'
    data_uri = f"data:{mime_type};base64,{base64_audio}"

    prompt_text = f"""You are a professional translator. Listen to the audio. 
    If the user speaks in Russian, translate it to {target_lang_name}.
    If the user speaks in any other language, translate it to Russian.
    Output strictly only the translated text without any comments, markdown, or quotes."""

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": AUDIO_MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload,
                                         timeout=60.0)
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage")
            ai_reply = data["choices"][0]["message"]["content"].strip()

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    await log_api_usage(conn, session_id, "audio_translate", usage)
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, source_language) VALUES ($1, $2, $3, $4)",
                        session_id, "user", "🎤 Голосовое сообщение", "audio"
                    )
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                        session_id, "assistant", ai_reply
                    )
            except Exception as db_err:
                print(f"Database connection failed: {db_err}")

        return {"reply": ai_reply, "source_language": "Голос"}


    except httpx.HTTPStatusError as e:

        if e.response.status_code == 429:
            print("OpenRouter Rate Limit (429): Слишком много запросов")

            raise HTTPException(status_code=429,
                                detail="ИИ перегружен. Слишком много запросов, попробуйте через минуту.")

        raise HTTPException(status_code=e.response.status_code, detail=str(e))

    except Exception as e:

        print(f"Check Lesson Error: {str(e)}")

        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"status": "Backend is running"}