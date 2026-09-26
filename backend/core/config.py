import os
from dotenv import load_dotenv
import httpx
from random import SystemRandom

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

DATABASE_URL = os.getenv("DATABASE_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

STORAGE_BUCKET = "chat-images"

TEXT_MODEL = "openai/gpt-5.6-luna"
VISION_MODEL = "openai/gpt-5.6-luna"
TRANSCRIPTION_MODEL = "openai/whisper-large-v3"

RANDOMIZER = SystemRandom()

DEFAULT_TEMPERATURE = 0.7
TRANSLATOR_TEMPERATURE = 0.82

MAX_IMAGE_SIZE = 1600
JPEG_QUALITY = 80

OPENROUTER_TIMEOUT = httpx.Timeout(
    connect=20,
    read=90,
    write=90,
    pool=20,
)

DEFAULT_LANGUAGE = "Chinese"
WELCOME_MESSAGE_CONTENT = (
    "Я AI-переводчик, который также поможет тебе учить язык"
)
DEFAULT_CONVERSATION_MODE = "translator"
RECENT_HISTORY_LIMIT = 20
SUMMARY_REBUILD_EVERY_MESSAGES = 200
