import os
import uuid
import json
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv
from prompts import SETUP_SYSTEM_PROMPT, get_translation_prompt, get_lesson_prompt, get_assessment_prompt, get_single_word_prompt, get_lesson_evaluation_prompt, get_lesson_from_history_prompt, get_translation_pdf_prompt
import random
from fastapi import UploadFile, File
from pypdf import PdfReader
import io

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trachat.vercel.app",
                   "https://linguachat-x26d.onrender.com",
                   "http://localhost:5173",
                   "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*", "X-Session-Id"],
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "deepseek/deepseek-chat"
DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        try:
            # Обновленная строка создания пула
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                timeout=30,
                command_timeout=60,
                max_inactive_connection_lifetime=60 # FIX: это сделано так как render sql бесплатный тариф, при платном тарифе для оптимизации наверное нужно убрать; Закрываем простаивающие соединения до того, как это сделает Render
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
                # НОВАЯ ТАБЛИЦА ДЛЯ ОРИГИНАЛЬНЫХ ТЕКСТОВ PDF
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
                    CREATE TABLE IF NOT EXISTS user_settings (
                        session_id UUID PRIMARY KEY,
                        target_language_code VARCHAR(10),
                        target_language_name VARCHAR(100)
                    )
                ''')
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_level INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS is_lesson BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS source_language VARCHAR(50)")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_level INTEGER")
                await conn.execute("ALTER TABLE user_settings ALTER COLUMN proficiency_level DROP NOT NULL")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS is_evaluation BOOLEAN DEFAULT FALSE")


                # НОВАЯ ТАБЛИЦА ДЛЯ ЛОГОВ УРОКОВ
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS lesson_logs (
                        id SERIAL PRIMARY KEY,
                        session_id UUID NOT NULL,
                        content TEXT NOT NULL,
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

class ChatRequest(BaseModel):
    message: str

class LessonRequest(BaseModel):
    user_text: str
    ai_text: str
    use_history: bool = False

def get_session_id(req: Request):
    session_id_str = req.headers.get("X-Session-Id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    return session_id_str


@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_code = None
    if db_pool:
        async with db_pool.acquire() as conn:
            # Проверяем, выбран ли язык
            row_settings = await conn.fetchrow("SELECT target_language_code FROM user_settings WHERE session_id = $1",
                                               session_id)
            if row_settings:
                target_lang_code = row_settings["target_language_code"]

            # 1. Проверяем последнее сообщение в истории
            last_row = await conn.fetchrow(
                "SELECT id, is_lesson, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
                session_id
            )

            # Если последнее сообщение — это урок, значит пользователь на него не ответил (урок "висит").
            # Удаляем его из чата, чтобы он пропал при обновлении страницы.
            if last_row and last_row["is_lesson"]:
                await conn.execute("DELETE FROM chat_history WHERE id = $1", last_row["id"])
                # СОХРАНЯЕМ В ЛОГИ УРОКОВ (для статистики)
                await conn.execute(
                    "INSERT INTO lesson_logs (session_id, content) VALUES ($1, $2)",
                    session_id, last_row["content"]
                )

            # 2. Достаем очищенную историю
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
                "SELECT target_language_code, target_language_name FROM user_settings WHERE session_id = $1",
                session_id)
            if row:
                target_lang_code = row["target_language_code"]
                target_lang_name = row["target_language_name"]

    if not target_lang_code:
        messages = [
            {"role": "system", "content": SETUP_SYSTEM_PROMPT},
            {"role": "user", "content": request.message}
        ]
    else:
        # --- РЕЖИМ 2: Строгий перевод ---
        # Проверяем, состоит ли сообщение из одного слова (убираем пробелы и знаки препинания)
        cleaned_message = request.message.strip().replace('.', '').replace(',', '').replace('!', '').replace('?', '')
        is_single_word = len(cleaned_message.split()) == 1

        if is_single_word:
            # Промпт для одного слова (словарь)
            system_content = get_single_word_prompt(target_lang_name, target_lang_code)
        else:
            # Обычный промпт для предложений
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

            raw_text = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw_text)

            source_lang_name = parsed.get("source_language_name", "")

            if not target_lang_code:
                ai_reply = parsed.get("reply", "Ошибка обработки.")
                detected_lang_code = parsed.get("target_language_code")
                detected_lang_name = parsed.get("target_language_name")

                if detected_lang_code and db_pool:
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO user_settings (session_id, target_language_code, target_language_name, proficiency_level) VALUES ($1, $2, $3, NULL) ON CONFLICT (session_id) DO UPDATE SET target_language_code = $2, target_language_name = $3, proficiency_level = NULL",
                            session_id, detected_lang_code, detected_lang_name
                        )
                    # Обновляем переменную, чтобы передать на фронтенд, что язык теперь выбран
                    target_lang_code = detected_lang_code
            else:
                ai_reply = parsed.get("translation", "Ошибка перевода.")

        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, source_language) VALUES ($1, $2, $3, $4)",
                    session_id, "user", request.message, source_lang_name
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_reply
                )

        # Возвращаем target_lang_code (он будет null, если бот спросил про язык)
        return {"session_id": session_id_str, "reply": ai_reply, "source_language": source_lang_name,
                "target_language_code": target_lang_code}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/lesson")
async def mini_lesson(request: LessonRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_name = "иностранный"
    proficiency_level = None

    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT target_language_name, proficiency_level FROM user_settings WHERE session_id = $1", session_id)
            if row:
                target_lang_name = row["target_language_name"]
                proficiency_level = row["proficiency_level"]

    # Заголовки вынесены наверх, чтобы они были доступны в обоих режимах
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    # --- РЕЖИМ 1: Уровень еще не определен (Генерация проверочного текста) ---
    if proficiency_level is None:
        system_prompt = get_assessment_prompt(target_lang_name, request.user_text, request.ai_text)
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "system", "content": system_prompt}],
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers,
                                             json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                parsed = json.loads(data["choices"][0]["message"]["content"].strip())
                texts = parsed.get("texts", ["", "Ошибка генерации.", "", "", "", "", ""])
                # Возвращаем массив текстов на фронтенд
                return {"action": "assess", "texts": texts}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- РЕЖИМ 2: Обычный мини-урок ---
    question_or_phrase = [('Ответь', 'Question'),('Переведи', 'Phrase')][random.choice([0, 1])]
    # НОВОЕ: Если пришел флаг use_history, берем историю из БД
    if request.use_history and db_pool:
        async with db_pool.acquire() as conn:
            # Берем последние 12 сообщений ВКЛЮЧАЯ уроки и оценки
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 12",
                session_id
            )
            # Формируем текст истории
            history_log = "\n".join([f"{r['role']}: {r['content']}" for r in reversed(rows)])

        system_prompt = get_lesson_from_history_prompt(target_lang_name, proficiency_level, history_log,
                                                       question_or_phrase)
    else:
        system_prompt = get_lesson_prompt(target_lang_name, proficiency_level, request.user_text, request.ai_text,
                                          question_or_phrase)

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
            parsed = json.loads(data["choices"][0]["message"]["content"].strip())
            lesson_text = parsed.get("lesson_text", "Не удалось создать урок.")

            if db_pool:
                async with db_pool.acquire() as conn:
                    # 1. Сохраняем урок в историю чата, чтобы пользователь его видел
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, is_lesson) VALUES ($1, $2, $3, TRUE)",
                        session_id, "assistant", lesson_text
                    )
                    new_level = min(100, proficiency_level + 5)
                    await conn.execute("UPDATE user_settings SET proficiency_level = $1 WHERE session_id = $2",
                                       new_level, session_id)

            return {"action": "lesson", "lesson": lesson_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SetLevelRequest(BaseModel):
    level: str  # "0", "A1", "A2", "B1", "B2", "C1", "C2"


class CheckLessonRequest(BaseModel):
    lesson_text: str
    user_answer: str


@app.post("/api/check_lesson")
async def check_lesson(request: CheckLessonRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

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
            parsed = json.loads(data["choices"][0]["message"]["content"].strip())

            grade = parsed.get("grade", "Ошибка")
            explanation = parsed.get("explanation", "")
            evaluation_text = f"{grade}\n\n{explanation}"

        # Сохраняем ответ пользователя и оценку в историю чата
        # Теперь последним сообщением станет оценка, поэтому "висящий" урок больше не удалится при перезагрузке
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "user", request.user_answer
                )
                # Сохраняем оценку с флагом is_evaluation = TRUE
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, is_evaluation) VALUES ($1, $2, $3, TRUE)",
                    session_id, "assistant", evaluation_text
                )

        return {"evaluation": evaluation_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload_pdf")
async def upload_pdf(file: UploadFile = File(...), req: Request = None):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    # 1. Читаем PDF
    contents = await file.read()
    reader = PdfReader(io.BytesIO(contents))

    extracted_text = ""
    for page in reader.pages:
        extracted_text += page.extract_text() + "\n"

    extracted_text = extracted_text.strip()
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Не удалось извлечь текст или файл пуст.")

    # 2. Сохраняем ОРИГИНАЛЬНЫЙ текст в базу данных
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO documents (session_id, filename, original_text) VALUES ($1, $2, $3)",
                session_id, file.filename, extracted_text
            )

    # 3. Разбиваем текст на части (по 2000 символов)
    chunk_size = 2000
    chunks = [extracted_text[i:i + chunk_size] for i in range(0, len(extracted_text), chunk_size)]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    # 4. Создаем генератор для потоковой передачи
    async def translate_stream():
        full_translation = ""
        # Используем один клиент для всех запросов
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

                    # Отправляем часть перевода на фронтенд
                    yield translated_chunk + "\n"
                except Exception as e:
                    yield f"\n[Ошибка перевода части {i + 1}]\n"

        # 5. После завершения перевода сохраняем весь перевод в историю чата
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

    # Возвращаем потоковый ответ
    return StreamingResponse(translate_stream(), media_type="text/plain")

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


@app.post("/api/abandon_lesson")
async def abandon_lesson(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    if db_pool:
        async with db_pool.acquire() as conn:
            # Находим последнее сообщение
            last_row = await conn.fetchrow(
                "SELECT id, is_lesson, content FROM chat_history WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
                session_id
            )
            # Если это урок, удаляем его из чата и сохраняем в логи
            if last_row and last_row["is_lesson"]:
                await conn.execute("DELETE FROM chat_history WHERE id = $1", last_row["id"])
                await conn.execute(
                    "INSERT INTO lesson_logs (session_id, content) VALUES ($1, $2)",
                    session_id, last_row["content"]
                )

    return {"status": "ok"}

@app.get("/")
def read_root():
    return {"status": "Backend is running"}

