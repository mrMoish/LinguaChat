import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

import os


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_key")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test_key")
    monkeypatch.setenv("DATABASE_URL", "test_db_url")


@pytest.fixture
def mock_http_client():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "{\"translation\": \"test\"}"}}]
    }
    mock_client.post.return_value = mock_response
    return mock_client


@pytest.fixture
def mock_db_pool():
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    return mock_pool


@pytest.fixture
def test_client(mock_db_pool, mock_http_client, monkeypatch):
    from backend.main import app
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_key")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test_key")
    monkeypatch.setenv("DATABASE_URL", "test_db_url")
    app.state.db_pool = mock_db_pool
    # Replace the client manager's client
    from backend.services.http_client import client_manager
    client_manager.client = mock_http_client
    return MagicMock()


@pytest.fixture
def mock_openrouter_response():
    return {
        "choices": [
            {
                "message": {
                    "content": "{\"translation\": \"test translation\", \"exercise\": {\"type\": \"yes_no\", \"question\": \"test question\", \"correct_answer\": \"yes\", \"explanation\": \"test explanation\"}}"
                }
            }
        ]
    }