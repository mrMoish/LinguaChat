import os
import uuid
import json
import base64
import ssl
import io
import asyncio
from typing import Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
)

from fastapi.middleware.cors import CORSMiddleware

import httpx
import asyncpg
from dotenv import load_dotenv

from PIL import Image, ImageOps
import pillow_heif

from prompts import (
    get_unified_prompt,
    get_summary_update_prompt,
    get_summary_rebuild_prompt,
)

from admin import router as admin_router


load_dotenv()
pillow_heif.register_heif_opener()


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    admin_router,
    prefix="/api/admin",
)


DEFAULT_LANGUAGE = "Spanish (Argentina)"

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

TRANSCRIPTION_URL = (
    "https://openrouter.ai/api/v1/audio/transcriptions"
)

DATABASE_URL = os.getenv("DATABASE_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY"
)

STORAGE_BUCKET = "chat-images"

TEXT_MODEL = "openai/gpt-5.6-luna"
VISION_MODEL = "openai/gpt-5.6-luna"
TRANSCRIPTION_MODEL = "openai/whisper-large-v3"


db_pool = None


# ============================================================
# DATABASE
# ============================================================

@app.on_event("startup")
async def startup():
    global db_pool

    if not DATABASE_URL:
        print("DATABASE_URL is not configured.")
        return

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=60,
            command_timeout=60,
            max_inactive_connection_lifetime=60,
            ssl=ctx,
            statement_cache_size=0,
        )

        # Делаем существующий pool доступным
        # для admin.py
        app.state.db_pool = db_pool

        async with db_pool.acquire() as conn:

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    session_id UUID NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    session_id UUID PRIMARY KEY,
                    target_language_name VARCHAR(100)
                        DEFAULT 'Chinese'
                )
                """
            )

            await conn.execute(
                """
                ALTER TABLE chat_history
                ADD COLUMN IF NOT EXISTS
                message_type VARCHAR(20)
                DEFAULT 'text'
                """
            )

            await conn.execute(
                """
                ALTER TABLE chat_history
                ADD COLUMN IF NOT EXISTS
                media_url TEXT
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory (
                    session_id UUID PRIMARY KEY,

                    chat_summary TEXT NOT NULL DEFAULT '',

                    summary_message_count INTEGER NOT NULL
                        DEFAULT 0,

                    updated_at TIMESTAMP WITH TIME ZONE
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        print("База данных успешно подключена!")

    except Exception as e:
        print(f"DB Error: {e}")


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()