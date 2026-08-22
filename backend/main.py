import os
import uuid
import json
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv

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
            db_pool = await asyncpg.create_pool(DATABASE_URL)
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
                # ДОБАВЛЯЕМ КОЛОНКУ УРОВНЯ ВЛАДЕНИЯ (0-100)
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS proficiency_level INTEGER DEFAULT 0")
                # НОВЫЕ КОЛОНКИ (добавляются, если их еще нет)
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS is_lesson BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS source_language VARCHAR(50)")
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

def get_session_id(req: Request):
    session_id_str = req.headers.get("X-Session-Id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    return session_id_str

@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)
    
    if db_pool:
        async with db_pool.acquire() as conn:
            # ДОБАВЛЯЕМ is_lesson и source_language в выборку
            rows = await conn.fetch(
                "SELECT role, content, is_lesson, source_language FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id
            )
            # Преобразуем snake_case из БД в camelCase для фронтенда
            history = [{
                "role": row["role"], 
                "content": row["content"], 
                "isLesson": row["is_lesson"], 
                "source_language": row["source_language"]
            } for row in rows]
            return {"session_id": session_id_str, "history": history}
    
    return {"session_id": session_id_str, "history": []}

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
            row = await conn.fetchrow("SELECT target_language_code, target_language_name FROM user_settings WHERE session_id = $1", session_id)
            if row:
                target_lang_code = row["target_language_code"]
                target_lang_name = row["target_language_name"]

    if not target_lang_code:
        system_prompt = """You are a language learning setup assistant. Evaluate the user's first message step by step.
        
        Step 1: Is the message a phrase indicating the language they want to learn? (e.g., "I learn English", "У меня B2 немецкий", "Spanish").
        Step 2: If Step 1 is false, is the message written in Russian?
        Step 3: If Step 2 is false, the message is written in a foreign language.

        Based on the evaluation, you MUST output STRICT JSON without any markdown formatting:
        {
          "target_language_name": "Name in Russian or null",
          "target_language_code": "ISO 639-1 code (e.g., 'en', 'fr') or null",
          "source_language_name": "Name in Russian of the user's input language",
          "reply": "Your reply in Russian"
        }

        Rules for the reply:
        - If Step 1 is true: Set target_language_code and target_language_name. Reply in Russian confirming the target language (e.g., "Отлично! Теперь я буду переводить ваши тексты на английский и давать вам мини уроки.").
        - If Step 2 is true (user writes in Russian): Set target_language_code to null. Reply in Russian asking which language they want to learn (e.g., "На какой язык вы хотите переводить текст?").
        - If Step 3 is true (the user writes in a foreign language): set target_language_code and target_language_name to the detected language. Reply in Russian, providing only the translation of the user's message without comments.
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message}
        ]
    else:
        # --- РЕЖИМ 2: Строгий перевод ---
        system_prompt = f"""You are a professional translator. The user's target language is {target_lang_name} ({target_lang_code}).
        Strictly translate the user's text. Do not add any comments, notes, or conversational text.
        If the user writes in {target_lang_name}, translate to Russian.
        If the user writes in Russian, translate to {target_lang_name}.
        If the user writes in any other language, translate to Russian.
        You MUST output STRICT JSON without any markdown formatting:
        {{
          "source_language_name": "Name of the input language in Russian",
          "translation": "The translated text"
        }}"""
        messages = [
            {"role": "system", "content": system_prompt},
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
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            
            raw_text = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw_text)
            
            # Извлекаем исходный язык из ответа ИИ
            source_lang_name = parsed.get("source_language_name", "")
            
            if not target_lang_code:
                ai_reply = parsed.get("reply", "Ошибка обработки.")
                detected_lang_code = parsed.get("target_language_code")
                detected_lang_name = parsed.get("target_language_name")
                
                if detected_lang_code and db_pool:
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO user_settings (session_id, target_language_code, target_language_name) VALUES ($1, $2, $3) ON CONFLICT (session_id) DO UPDATE SET target_language_code = $2, target_language_name = $3",
                            session_id, detected_lang_code, detected_lang_name
                        )
            else:
                ai_reply = parsed.get("translation", "Ошибка перевода.")

        if db_pool:
            async with db_pool.acquire() as conn:
                # СОХРАНЯЕМ source_language для сообщения пользователя
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content, source_language) VALUES ($1, $2, $3, $4)",
                    session_id, "user", request.message, source_lang_name
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_reply
                )

        return {"session_id": session_id_str, "reply": ai_reply, "source_language": source_lang_name}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/lesson")
async def mini_lesson(request: LessonRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    target_lang_name = "иностранный"
    proficiency_level = 0
    
    # Получаем язык и текущий уровень из БД
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT target_language_name, proficiency_level FROM user_settings WHERE session_id = $1", session_id)
            if row:
                target_lang_name = row["target_language_name"]
                proficiency_level = row["proficiency_level"] if row["proficiency_level"] is not None else 0

    # Используем уровень в промпте
    system_prompt = f"""You are a friendly and encouraging language tutor. The user's target language is {target_lang_name}.
    The user's current proficiency level is {proficiency_level}% (on a scale of 0 to 100).
    
    The user originally wrote: "{request.user_text}"
    The translation was: "{request.ai_text}"

Create one short and engaging exercise based on these texts.

The exercise must be one of the following:

1. Ask the user a question in Russian that contains at least 7 words.
2. Ask the user a question in `{target_lang_name}` that contains at least 7 words.
3. Create a sentence in `{target_lang_name}` containing at least 7 words for the user to translate.
4. Create a sentence in Russian containing at least 7 words for the user to translate.

Do not provide the correct answer immediately. Do not add explanations or comments.

    Return STRICT JSON without markdown:
    {{
      "lesson_text": "🎓 Мини-урок! ['Ответь' or 'Переведи']\\n\\n[Question or phrase]"
    }}"""

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME, 
        "messages": [{"role": "system", "content": system_prompt}],
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            
            raw_text = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw_text)
            lesson_text = parsed.get("lesson_text", "Не удалось создать урок.")
            
            if db_pool:
                async with db_pool.acquire() as conn:
                    # Сохраняем урок в историю
                    await conn.execute(
                        "INSERT INTO chat_history (session_id, role, content, is_lesson) VALUES ($1, $2, $3, TRUE)",
                        session_id, "assistant", lesson_text
                    )
                    
                    # УВЕЛИЧИВАЕМ УРОВЕНЬ ВЛАДЕНИЯ НА 5% (максимум 100)
                    new_level = min(100, proficiency_level + 5)
                    await conn.execute(
                        "UPDATE user_settings SET proficiency_level = $1 WHERE session_id = $2",
                        new_level, session_id
                    )

            return {"lesson": lesson_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/")
def read_root():
    return {"status": "Backend is running"}

