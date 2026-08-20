import os
import uuid
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ВАЖНО: Для работы с куками в CORS обязательно нужно allow_credentials=True
# И вместо "*" нужно явно указать домен вашего фронтенда!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trachat.vercel.app",
                   "https://linguachat-x26d.onrender.com",
                   "http://localhost:5173",
                   "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "deepseek/deepseek-chat"
DATABASE_URL = os.getenv("DATABASE_URL")

# Пул соединений с БД
db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        # Подключаемся к базе
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        # Создаем таблицу, если её не существует
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
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан, история работать не будет!")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(request: ChatRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    # 1. Работа с кукой и UUID
    session_id_str = req.cookies.get("session_id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    
    session_id = uuid.UUID(session_id_str)

    # 2. Достаем историю из БД
    db_history = []
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id
            )
            db_history = [{"role": row["role"], "content": row["content"]} for row in rows]

    # 3. Формируем запрос в OpenRouter
    messages = [
        {
            "role": "system", 
            "content": "Ты профессиональный переводчик. Твоя задача — переводить любой предоставленный текст на русский язык. Выводи только переведенный текст."
        }
    ]
    # Добавляем историю из базы
    messages.extend(db_history)
    # Добавляем новое сообщение пользователя
    messages.append({"role": "user", "content": request.message})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
    }

    try:
        # 4. Отправляем запрос в ИИ
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            
            choices = data.get("choices", [])
            replies = []
            for idx, choice in enumerate(choices):
                content = choice.get("message", {}).get("content", "").strip()
                if content:
                    replies.append(content)
            
            ai_message = "\n\n".join(replies) if replies else "ИИ не сгенерировал никакого ответа."

        # 5. Сохраняем историю в БД
        if db_pool:
            async with db_pool.acquire() as conn:
                # Сохраняем сообщение пользователя
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "user", request.message
                )
                # Сохраняем ответ ИИ
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_message
                )

        # 6. Возвращаем ответ и обновляем куку
        response_obj = Response(content='{"reply": "%s"}' % ai_message.replace('"', '\\"'), media_type="application/json")
        response_obj.set_cookie(
            key="session_id", 
            value=session_id_str, 
            httponly=True, 
            max_age=30*24*60*60, # 30 дней
            samesite="none",     # ВАЖНО для кросс-доменных запросов (Vercel -> Render)
            secure=True          # ВАЖНО для samesite=none (требует HTTPS на Render и Vercel)
        )
        return response_obj

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"OpenRouter error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"status": "Backend is running"}
