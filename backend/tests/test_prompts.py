import pytest

from backend.prompts import (
    get_unified_prompt,
    get_exercise_prompt,
    get_text_prompt,
)

def test_get_unified_prompt():
    # Test translator mode
    prompt = get_unified_prompt(
        "Spanish",
        "Test summary",
        "translator",
        "unknown",
        "",
        "auto"
    )
    assert "Сейчас активен режим TRANSLATOR" in prompt
    assert "Spanish" in prompt

    # Test teacher mode
    prompt = get_unified_prompt(
        "Spanish",
        "Test summary",
        "teacher",
        "unknown",
        "",
        "auto"
    )
    assert "Сейчас активен режим TEACHER" in prompt

    # Test with empty summary
    prompt = get_unified_prompt(
        "Spanish",
        "",
        "translator",
        "unknown",
        "",
        "auto"
    )
    assert "Пока нет сохранённой памяти о пользователе" in prompt

def test_get_exercise_prompt():
    prompt = get_exercise_prompt(
        "Spanish",
        "unknown",
        "Test context",
        "",
        "auto"
    )
    assert "Создай welcome-упражнение" not in prompt
    assert "Ты создаёшь одно короткое упражнение" in prompt

def test_get_text_prompt():
    prompt = get_text_prompt("Spanish")
    assert "Сейчас активен режим TRANSLATOR" in prompt
    assert "Spanish" in prompt