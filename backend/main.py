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

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
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
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан!")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

class ChatRequest(BaseModel):
    message: str

# 1. НОВЫЙ ЭНДПОИНТ ДЛЯ ЗАГРУЗКИ ИСТОРИИ ПРИ ВХОДЕ
@app.get("/api/history")
async def get_history(req: Request):
    session_id_str = req.cookies.get("session_id")
    
    # Если куки нет, генерируем новый UUID и сразу возвращаем пустую историю
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
        response_obj = Response(content='{"history": []}', media_type="application/json")
        response_obj.set_cookie(
            key="session_id", value=session_id_str, httponly=True, 
            max_age=30*24*60*60, samesite="none", secure=True
        )
        return response_obj

    session_id = uuid.UUID(session_id_str)
    
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id
            )
            history = [{"role": row["role"], "content": row["content"]} for row in rows]
            return {"history": history}
    
    return {"history": []}


# 2. ОСНОВНОЙ ЭНДПОИНТ ПЕРЕВОДА
@app.post("/api/chat")
async def chat(request: ChatRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = req.cookies.get("session_id")
    if not session_id_str:
        session_id_str = str(uuid.uuid4())
    session_id = uuid.UUID(session_id_str)

    # Формируем запрос ТОЛЬКО с текущим сообщением (без истории из БД)
    messages = [
        {
            "role": "system", 
            "content": "Ты профессиональный переводчик. Твоя задача — переводить любой предоставленный текст на русский язык. Выводи только переведенный текст. Не добавляй комментариев."
        },
        {
            "role": "user", 
            "content": request.message
        }
    ]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages, # Отправляем только текущий текст!
    }

    try:
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
            for choice in choices:
                content = choice.get("message", {}).get("content", "").strip()
                if content:
                    replies.append(content)
            
            ai_message = "\n\n".join(replies) if replies else "ИИ не сгенерировал ответ."

        # СОХРАНЯЕМ ИСТОРИЮ В БД (только для архива)
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "user", request.message
                )
                await conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)",
                    session_id, "assistant", ai_message
                )

        # Возвращаем ответ и обновляем куку
        response_obj = Response(content='{"reply": "%s"}' % ai_message.replace('"', '\\"').replace('\n', '\\n'), media_type="application/json")
        response_obj.set_cookie(
            key="session_id", value=session_id_str, httponly=True, 
            max_age=30*24*60*60, samesite="none", secure=True
        )
        return response_obj

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"OpenRouter error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"status": "Backend is running"}


