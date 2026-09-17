import os
import uuid
import json
import io
import base64
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv
from PIL import Image
import pillow_heif
from pypdf import PdfReader

from prompts import (
    get_first_question_prompt,
    get_conversation_prompt,
    get_replace_question_prompt,
    get_hint_prompt,
)

load_dotenv()
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
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv("DATABASE_URL")

RECENT_HISTORY_LIMIT = 8
COST_LIMIT = 1.0
USER_PROFILE_MAX_CHARS = 800
DEFAULT_TEACHER_BIAS = 30  # старт ближе к "другу"

db_pool = None


@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=5, timeout=60,
                command_timeout=60, max_inactive_connection_lifetime=60
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
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_min INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_max INTEGER DEFAULT 100")
                await conn.execute(f"ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS teacher_bias INTEGER DEFAULT {DEFAULT_TEACHER_BIAS}")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS user_profile TEXT DEFAULT ''")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS total_cost NUMERIC(10, 5) DEFAULT 0.0")

                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS feedback TEXT")

                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        filename VARCHAR(255),
                        original_text TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
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


# --- МОДЕЛИ ---
class SelectLanguageRequest(BaseModel):
    code: str
    locale: str
    name: str


class MessageRequest(BaseModel):
    message: str
    current_question: str = ""


class ReplaceQuestionRequest(BaseModel):
    current_question: str = ""


class HintRequest(BaseModel):
    text: str


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_session_id(req: Request):
    session_id_str = req.headers.get("X-Session-Id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    return session_id_str


def clamp(value, low, high):
    return max(low, min(high, value))


async def log_api_usage(conn, session_id, endpoint, usage_data):
    if not usage_data:
        return
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


async def call_openrouter(messages, model=MODEL_NAME):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
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


async def get_settings(session_id):
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT target_language_code, target_language_name, language_locale, proficiency_min, "
            "proficiency_max, teacher_bias, user_profile, total_cost "
            "FROM user_settings WHERE session_id = $1", session_id
        )


async def build_recent_summary(session_id):
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


async def update_last_assistant_message(conn, session_id, new_content):
    await conn.execute(
        """UPDATE chat_history SET content = $1
           WHERE id = (SELECT id FROM chat_history WHERE session_id = $2 AND role = 'assistant'
                       ORDER BY created_at DESC LIMIT 1)""",
        new_content, session_id
    )


# --- ЭНДПОИНТЫ ---

@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if not db_pool:
        return {"session_id": session_id_str, "history": [], "settings": None}

    async with db_pool.acquire() as conn:
        settings_row = await conn.fetchrow(
            "SELECT target_language_code, target_language_name, language_locale, proficiency_min, "
            "proficiency_max, teacher_bias FROM user_settings WHERE session_id = $1", session_id
        )
        rows = await conn.fetch(
            "SELECT role, content, feedback FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
            session_id
        )

    history = []
    for row in rows:
        item = {"role": row["role"], "content": row["content"]}
        if row["feedback"]:
            try:
                item["feedback"] = json.loads(row["feedback"])
            except (TypeError, json.JSONDecodeError):
                pass
        history.append(item)

    settings = None
    if settings_row and settings_row["target_language_code"]:
        settings = {
            "target_language_code": settings_row["target_language_code"],
            "target_language_name": settings_row["target_language_name"],
            "language_locale": settings_row["language_locale"],
            "proficiency_min": settings_row["proficiency_min"],
            "proficiency_max": settings_row["proficiency_max"],
            "teacher_bias": settings_row["teacher_bias"],
        }

    return {"session_id": session_id_str, "history": history, "settings": settings}


@app.post("/api/select_language")
async def select_language(request: SelectLanguageRequest, req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    system_content = get_first_question_prompt(request.name)
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Начнём."}
    ]

    try:
        data = await call_openrouter(messages)
        usage = data.get("usage")
        raw_text = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)
    except Exception as e:
        handle_llm_error(e, "Select Language Error")
        return

    question = parsed.get("question", "Расскажи что-нибудь о себе?")

    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_settings (session_id, target_language_code, target_language_name, language_locale, "
                "proficiency_min, proficiency_max, teacher_bias, user_profile) "
                f"VALUES ($1, $2, $3, $4, 0, 100, {DEFAULT_TEACHER_BIAS}, '') "
                "ON CONFLICT (session_id) DO UPDATE SET target_language_code = $2, target_language_name = $3, "
                f"language_locale = $4, proficiency_min = 0, proficiency_max = 100, teacher_bias = {DEFAULT_TEACHER_BIAS}, user_profile = ''",
                session_id, request.code, request.name, request.locale
            )
            await log_api_usage(conn, session_id, "select_language", usage)
            await conn.execute(
                "INSERT INTO chat_history (session_id, role, content) VALUES ($1, 'assistant', $2)",
                session_id, question
            )

    return {
        "session_id": session_id_str,
        "target_language_code": request.code,
        "target_language_name": request.name,
        "language_locale": request.locale,
        "question": question,
        "question_language": "ru",
        "proficiency_min": 0,
        "proficiency_max": 100,
        "teacher_bias": DEFAULT_TEACHER_BIAS,
    }


@app.post("/api/message")
async def message(request: MessageRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    settings = await get_settings(session_id)
    if not settings or not settings["target_language_code"]:
        raise HTTPException(status_code=400, detail="Язык ещё не выбран.")

    if settings["total_cost"] is not None and settings["total_cost"] >= COST_LIMIT:
        spent = round(settings["total_cost"], 2)
        return {
            "session_id": session_id_str, "mode": "answer",
            "reaction": f"Вы исчерпали лимит бесплатных запросов, потратив ${spent}. Чтобы продолжить, купите подписку через техподдержку.",
            "next_question": "", "question_language": "ru", "translation_package": None,
            "user_feedback": None,
            "proficiency_min": settings["proficiency_min"], "proficiency_max": settings["proficiency_max"],
            "teacher_bias": settings["teacher_bias"],
        }

    target_lang_name = settings["target_language_name"]
    level_min = settings["proficiency_min"] if settings["proficiency_min"] is not None else 0
    level_max = settings["proficiency_max"] if settings["proficiency_max"] is not None else 100
    teacher_bias = settings["teacher_bias"] if settings["teacher_bias"] is not None else DEFAULT_TEACHER_BIAS
    user_profile = settings["user_profile"] or ""

    recent_summary = await build_recent_summary(session_id)

    system_content = get_conversation_prompt(
        target_lang_name, level_min, level_max, teacher_bias,
        user_profile, recent_summary, request.current_question
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": request.message}
    ]

    try:
        data = await call_openrouter(messages)
        usage = data.get("usage")
        raw_text = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)
    except Exception as e:
        handle_llm_error(e, "Message Analysis Error")
        return

    mode = parsed.get("mode", "answer")
    message_language = parsed.get("message_language", "target")
    translation_package = parsed.get("translation_package") or {}
    has_significant_error = parsed.get("has_significant_error", False)
    correction = parsed.get("correction", "") or ""
    reaction = parsed.get("reaction", "") or ""
    next_question = parsed.get("next_question", "") or ""
    question_language = parsed.get("question_language", "ru")

    try:
        new_min = clamp(int(parsed.get("proficiency_min", level_min)), 0, 100)
        new_max = clamp(int(parsed.get("proficiency_max", level_max)), 0, 100)
    except (TypeError, ValueError):
        new_min, new_max = level_min, level_max
    if new_min > new_max:
        new_min, new_max = new_max, new_min

    try:
        bias_delta = clamp(int(parsed.get("teacher_bias_delta", 0)), -10, 10)
    except (TypeError, ValueError):
        bias_delta = 0
    new_teacher_bias = clamp(teacher_bias + bias_delta, 0, 100)

    user_feedback = None
    assistant_translation_feedback = None

    if mode == "isolated":
        user_feedback = None
        assistant_translation_feedback = {
            "type": "translation_package",
            "direction": translation_package.get("direction", ""),
            "target_text": translation_package.get("target_text", ""),
            "pronunciation_hint": translation_package.get("pronunciation_hint", ""),
            "literal_translation": translation_package.get("literal_translation", ""),
            "meaning_translation": translation_package.get("meaning_translation", ""),
        }
    else:
        if has_significant_error and correction:
            user_feedback = {"type": "correction", "correction": correction}
        if message_language == "ru":
            new_min, new_max = 0, 0

    updated_profile = (user_profile + "\n" + request.message).strip()[-USER_PROFILE_MAX_CHARS:]

    if mode == "isolated":
        assistant_content = "Перевод"
    else:
        assistant_content = f"{reaction}\n\n{next_question}".strip() if reaction else next_question

    user_feedback_json = json.dumps(user_feedback, ensure_ascii=False) if user_feedback else None
    assistant_feedback_json = json.dumps(assistant_translation_feedback, ensure_ascii=False) if assistant_translation_feedback else None

    if db_pool:
        async with db_pool.acquire() as conn:
            await log_api_usage(conn, session_id, "message", usage)
            await conn.execute(
                "UPDATE user_settings SET proficiency_min = $1, proficiency_max = $2, teacher_bias = $3, user_profile = $4 WHERE session_id = $5",
                new_min, new_max, new_teacher_bias, updated_profile, session_id
            )
            await conn.execute(
                "INSERT INTO chat_history (session_id, role, content, feedback) VALUES ($1, 'user', $2, $3)",
                session_id, request.message, user_feedback_json
            )
            await conn.execute(
                "INSERT INTO chat_history (session_id, role, content, feedback) VALUES ($1, 'assistant', $2, $3)",
                session_id, assistant_content, assistant_feedback_json
            )

    return {
        "session_id": session_id_str,
        "mode": mode,
        "message_language": message_language,
        "translation_package": assistant_translation_feedback,
        "reaction": reaction,
        "next_question": next_question,
        "question_language": question_language,
        "user_feedback": user_feedback,
        "proficiency_min": new_min,
        "proficiency_max": new_max,
        "teacher_bias": new_teacher_bias,
    }


@app.post("/api/replace_question")
async def replace_question(request: ReplaceQuestionRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    settings = await get_settings(session_id)
    if not settings or not settings["target_language_code"]:
        raise HTTPException(status_code=400, detail="Язык ещё не выбран.")

    target_lang_name = settings["target_language_name"]
    level_min = settings["proficiency_min"] if settings["proficiency_min"] is not None else 0
    level_max = settings["proficiency_max"] if settings["proficiency_max"] is not None else 100
    teacher_bias = settings["teacher_bias"] if settings["teacher_bias"] is not None else DEFAULT_TEACHER_BIAS
    user_profile = settings["user_profile"] or ""
    recent_summary = await build_recent_summary(session_id)

    system_content = get_replace_question_prompt(
        target_lang_name, level_min, level_max, teacher_bias,
        user_profile, recent_summary, request.current_question
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Замени вопрос."}
    ]

    try:
        data = await call_openrouter(messages)
        usage = data.get("usage")
        raw_text = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)
    except Exception as e:
        handle_llm_error(e, "Replace Question Error")
        return

    new_question = parsed.get("question", "")
    question_language = parsed.get("question_language", "ru")
    try:
        bias_delta = clamp(int(parsed.get("teacher_bias_delta", 10)), 0, 20)
    except (TypeError, ValueError):
        bias_delta = 10
    new_teacher_bias = clamp(teacher_bias + bias_delta, 0, 100)

    if db_pool:
        async with db_pool.acquire() as conn:
            await log_api_usage(conn, session_id, "replace_question", usage)
            await conn.execute(
                "UPDATE user_settings SET teacher_bias = $1 WHERE session_id = $2",
                new_teacher_bias, session_id
            )
            await update_last_assistant_message(conn, session_id, new_question)

    return {
        "session_id": session_id_str,
        "question": new_question,
        "question_language": question_language,
        "teacher_bias": new_teacher_bias,
    }


@app.post("/api/hint")
async def hint(request: HintRequest, req: Request):
    """Ленивая генерация подсказки (произношение/дословный/смысловой перевод) по клику 💡 —
    считается один раз по требованию, а не заранее для каждого сообщения."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    settings = await get_settings(session_id)
    target_lang_name = settings["target_language_name"] if settings else "иностранный язык"

    system_content = get_hint_prompt(target_lang_name)
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": request.text}
    ]

    try:
        data = await call_openrouter(messages)
        usage = data.get("usage")
        raw_text = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)
    except Exception as e:
        handle_llm_error(e, "Hint Error")
        return

    if db_pool:
        async with db_pool.acquire() as conn:
            await log_api_usage(conn, session_id, "hint", usage)

    return {
        "pronunciation_hint": parsed.get("pronunciation_hint", ""),
        "literal_translation": parsed.get("literal_translation", ""),
        "meaning_translation": parsed.get("meaning_translation", ""),
    }


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
                system_prompt = """You are a professional translator helping a language learner understand a document.
                Translate the following part of the document to Russian, clearly and naturally.
                Output only the translated text without any markdown or comments."""
                payload = {
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": chunk}
                    ]
                }
                try:
                    response = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
                    response.raise_for_status()
                    data = response.json()
                    translated_chunk = data["choices"][0]["message"]["content"].strip()
                    full_translation += translated_chunk + "\n"
                    yield translated_chunk + "\n"
                except Exception:
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
                if row and row["total_cost"] is not None and row["total_cost"] >= COST_LIMIT:
                    return {"reply": "Вы достигли лимита бесплатных запросов (1$). Пожалуйста, купите подписку через техподдержку.", "source_language": "Система"}
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

    data_uri = f"data:image/jpeg;base64,{base64_image}"
    prompt_text = """Проанализируй изображение. Определи, что на нём: текст для перевода, документ, или что-то другое.
Переведи весь текст на изображении на русский язык.
Объедини описание и переведённый текст в одно поле "reply", используй Markdown.
Определи язык текста (на русском, например "Английский"). Если текста нет — "Нет текста".
Верни СТРОГО JSON без markdown:
{
  "source_language_name": "Название языка на русском",
  "reply": "Описание изображения и переведённый текст"
}"""

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": data_uri}}
            ]}
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
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
            async with db_pool.acquire() as conn:
                await log_api_usage(conn, session_id, "image_translate", usage)
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "user", "📷 Фото для перевода"
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_reply
                )

        return {"reply": ai_reply, "source_language": source_lang}
    except Exception as e:
        handle_llm_error(e, "Image Translate Error")


@app.get("/")
def read_root():
    return {"status": "Backend is running"}