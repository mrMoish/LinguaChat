import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from backend.services.ai import (
    call_openrouter,
    normalize_exercise,
    normalize_memory_updates,
)
from backend.services.storage import upload_to_supabase
from backend.services.audio import transcribe_audio
from backend.services.http_client import client_manager

@pytest.mark.asyncio
async def test_call_openrouter(mock_http_client, mock_openrouter_response):
    client_manager.client = mock_http_client
    mock_http_client.post.return_value.json.return_value = mock_openrouter_response

    result = await call_openrouter([], "test_model")
    assert result == {
        "translation": "test translation",
        "exercise": {
            "type": "yes_no",
            "question": "test question",
            "correct_answer": "yes",
            "explanation": "test explanation"
        }
    }

@pytest.mark.asyncio
async def test_upload_to_supabase(mock_http_client):
    client_manager.client = mock_http_client
    mock_http_client.post.return_value.status_code = 200
    mock_http_client.post.return_value.json.return_value = {
        "path": "test.jpg"
    }

    result = await upload_to_supabase(b"test", "image/jpeg", "jpg")
    # The function returns the full URL path
    assert "supabase.co" in result

@pytest.mark.asyncio
async def test_transcribe_audio(mock_http_client):
    client_manager.client = mock_http_client
    mock_http_client.post.return_value.json.return_value = {
        "text": "test transcription"
    }

    result = await transcribe_audio(b"test", "audio/wav", "test.wav")
    assert result == "test transcription"

def test_normalize_exercise():
    # Test yes/no exercise
    exercise = {
        "type": "yes_no",
        "question": "Test question",
        "correct_answer": "yes",
        "explanation": "Test explanation"
    }
    normalized = normalize_exercise(exercise, "translator", "Test translation")
    assert normalized == exercise

    # Test matching pairs
    exercise = {
        "type": "matching_pairs",
        "pairs": [
            {"term": "word1", "translation": "translation1"},
            {"term": "word2", "translation": "translation2"}
        ],
        "explanation": "Test explanation"
    }
    normalized = normalize_exercise(exercise, "translator", "Test translation")
    assert normalized["type"] == "matching_pairs"
    assert len(normalized["pairs"]) == 2

    # Test fallback exercise
    normalized = normalize_exercise({}, "translator", "Test translation")
    assert normalized["type"] == "yes_no"
    assert "Test translation" in normalized["question"]

def test_normalize_memory_updates():
    # Test string input
    result = normalize_memory_updates("Test update")
    assert result == ["Test update"]

    # Test list input
    result = normalize_memory_updates(["Update 1", "Update 2"])
    assert result == ["Update 1", "Update 2"]

    # Test invalid input
    result = normalize_memory_updates(123)
    assert result == []