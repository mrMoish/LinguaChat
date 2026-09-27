import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from backend.db.database import (
    get_session_id,
    save_message,
    get_user_settings,
    get_chat_memory,
    get_recent_history,
    get_recent_exercises,
)

@pytest.mark.asyncio
async def test_get_session_id():
    # Test with request object
    req = MagicMock()
    req.headers.get.return_value = None
    req.query_params.get.return_value = None
    session_id = get_session_id(req)
    assert isinstance(session_id, str)

    # Test with fallback session ID
    session_id = get_session_id(req, "fallback_id")
    assert session_id == "fallback_id"

@pytest.mark.asyncio
async def test_save_message(mock_db_pool):
    mock_conn = AsyncMock()
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetchval.return_value = 1

    user_id, assistant_id = await save_message(
        mock_conn,
        uuid.uuid4(),
        "user text",
        "assistant reply",
        "text",
        None,
        {"type": "yes_no", "question": "test", "correct_answer": "yes", "explanation": "test"}
    )
    assert user_id == 1
    assert assistant_id == 1

@pytest.mark.asyncio
async def test_get_user_settings(mock_db_pool):
    mock_conn = AsyncMock()
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetchrow.return_value = {
        "target_language_name": "Chinese",
        "conversation_mode": "translator"
    }

    language, mode = await get_user_settings(uuid.uuid4())
    assert language == "Chinese"
    assert mode == "translator"

@pytest.mark.asyncio
async def test_get_chat_memory(mock_db_pool):
    mock_conn = AsyncMock()
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetchrow.return_value = {
        "chat_summary": "Test summary",
        "summary_message_count": 10
    }

    summary, count = await get_chat_memory(mock_conn, uuid.uuid4())
    assert summary == "Test summary"
    assert count == 10

@pytest.mark.asyncio
async def test_get_recent_history(mock_db_pool):
    mock_conn = AsyncMock()
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetch.return_value = [
        {"role": "assistant", "content": "test reply"},
        {"role": "user", "content": "test"}
    ]

    history = await get_recent_history(mock_conn, uuid.uuid4())
    assert len(history) == 2
    assert history[0]["role"] == "user"

@pytest.mark.asyncio
async def test_get_recent_exercises(mock_db_pool):
    mock_conn = AsyncMock()
    mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetch.return_value = [
        {"exercise_data": "{\"question\": \"test question\"}"}
    ]

    exercises = await get_recent_exercises(mock_conn, uuid.uuid4())
    assert exercises == ["test question"]