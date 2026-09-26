import sys
import os
# Ensure parent directory is in sys.path so 'backend' module is always resolvable
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.db.database import init_db, close_db
from backend.services.http_client import client_manager
from backend.routes.chat import router as chat_router
from backend.admin import router as admin_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db(app)
    yield
    # Shutdown
    await close_db()
    await client_manager.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(
    admin_router,
    prefix="/api/admin",
)

app.include_router(
    chat_router,
    prefix="/api",
)

@app.get("/")
def read_root():
    return {
        "status": "Backend is running"
    }
