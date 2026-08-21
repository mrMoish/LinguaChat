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

# Убираем allow_credentials, так как куки больше не используем
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trachat.vercel.app",
                   "https://linguachat-x26d.onrender.com",
                   "http://localhost:5173",
                   "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*", "X-Session-Id"], # Разрешаем наш кастомный заголовок
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

# Вспомогательная функция для получения UUID из заголовка 
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
            rows = await conn.fetch(
                "SELECT role, content FROM chat_history WHERE session_id = $1 ORDER BY created_at ASC",
                session_id
            )
            history = [{"role": row["role"], "content": row["content"]} for row in rows]
            return {"session_id": session_id_str, "history": history}
    
    return {"session_id": session_id_str, "history": []}

@app.post("/api/chat")
async def chat(request: ChatRequest, req: Request):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key not configured")

    session_id_str = get_session_id(req)
    session_id = uuid.UUID(session_id_str)

    messages = [
        {"role": "system", "content": "You are a professional translator. Your task is to translate any provided text into Spain. Output only the translated text. Do not add any comments."},
        {"role": "user", "content": request.message}
    ]

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL_NAME, "messages": messages}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            
            choices = data.get("choices", [])
            replies = [choice.get("message", {}).get("content", "").strip() for choice in choices if choice.get("message", {}).get("content", "").strip()]
            ai_message = "\n\n".join(replies) if replies else "ИИ не сгенерировал ответ."

        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)", session_id, "user", request.message)
                await conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)", session_id, "assistant", ai_message)

        return {"session_id": session_id_str, "reply": ai_message}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
