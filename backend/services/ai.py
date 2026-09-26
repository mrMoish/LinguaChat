import json
import uuid
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from backend.core.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    TEXT_MODEL,
    VISION_MODEL,
    DEFAULT_TEMPERATURE,
    TRANSLATOR_TEMPERATURE,
    RANDOMIZER,
    RECENT_HISTORY_LIMIT,
    SUMMARY_REBUILD_EVERY_MESSAGES,
)
from backend.services.http_client import client_manager
from backend.prompts import (
    get_unified_prompt,
    get_exercise_prompt,
    get_summary_update_prompt,
    get_summary_rebuild_prompt,
)
from backend.db import database as db_module
from backend.db.database import (
    get_user_settings,
    get_recent_history,
    get_chat_memory,
    get_recent_exercises,
    get_all_history,
    get_message_count,
    save_chat_summary,
    save_conversation_mode,
    save_message,
    detect_preferred_exercise_type,
    normalize_learner_level_hint,
)

async def call_openrouter(
    messages: list,
    model: str,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict:
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }

    client = await client_manager.get_client()
    response = await client.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
    )

    if response.status_code != 200:
        print(f"OpenRouter Error {response.status_code}: {response.text}")
        if response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="ИИ перегружен.",
            )
        raise HTTPException(
            status_code=response.status_code,
            detail="Ошибка ИИ.",
        )

    data = response.json()
    if "choices" not in data or not data["choices"]:
        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул ответ.",
        )

    raw_content = data["choices"][0]["message"]["content"]
    if not raw_content:
        raise HTTPException(
            status_code=500,
            detail="ИИ вернул пустой ответ.",
        )

    raw_text = raw_content.strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        print("Invalid JSON returned by model:", raw_text)
        raise HTTPException(
            status_code=500,
            detail="Ошибка формата ИИ.",
        )

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=500,
            detail="Ошибка формата ИИ.",
        )

    return parsed

def fallback_exercise(translation: str) -> dict:
    snippet = (translation or "").strip()
    if "\n" in snippet:
        snippet = snippet.split("\n", 1)[0].strip()

    if len(snippet) > 80:
        snippet = snippet[:77].rstrip() + "…"

    if snippet:
        is_negative = (sum(ord(char) for char in snippet) % 2) == 1
        if is_negative:
            question = (
                "Означает ли этот перевод "
                "противоположное исходному смыслу: "
                f"«{snippet}»?"
            )
            correct_answer = "no"
            explanation = "Нет, перевод сохраняет исходный смысл."
        else:
            question = (
                "Передаёт ли этот перевод смысл "
                f"исходной фразы: «{snippet}»?"
            )
            correct_answer = "yes"
            explanation = "Да, перевод сохраняет исходный смысл."
    else:
        question = "Правильно ли вы поняли перевод?"
        correct_answer = "yes"
        explanation = "Это упражнение к текущему переводу."

    return {
        "type": "yes_no",
        "question": question,
        "correct_answer": correct_answer,
        "explanation": explanation,
    }

def normalize_exercise(
    exercise,
    conversation_mode: str,
    translation: str,
):
    question = ""
    correct_answer = ""
    explanation = ""

    if isinstance(exercise, dict):
        exercise_type = str(
            exercise.get("type") or "yes_no"
        ).strip().lower()

        if exercise_type in ("matching_pairs", "translation_choice"):
            pairs = exercise.get("pairs")
            if isinstance(pairs, list):
                normalized_pairs = []
                for pair in pairs:
                    if not isinstance(pair, dict):
                        continue
                    term = str(pair.get("term") or pair.get("word") or "").strip()
                    translation_value = str(pair.get("translation") or "").strip()
                    if term and translation_value:
                        normalized_pairs.append({
                            "term": term,
                            "translation": translation_value,
                        })
            else:
                normalized_pairs = []

            if 2 <= len(normalized_pairs) <= 5:
                RANDOMIZER.shuffle(normalized_pairs)
                translations = [pair["translation"] for pair in normalized_pairs]
                RANDOMIZER.shuffle(translations)

                first_pair = normalized_pairs[0]
                distractors = [
                    val for val in translations if val != first_pair["translation"]
                ]
                initial_options = [first_pair["translation"]]
                if distractors:
                    initial_options.append(RANDOMIZER.choice(distractors))
                RANDOMIZER.shuffle(initial_options)

                return {
                    "type": "matching_pairs",
                    "question": "Найди пары",
                    "pairs": normalized_pairs,
                    "translations": translations,
                    "initial_options": initial_options,
                    "explanation": str(exercise.get("explanation") or "").strip(),
                }

        question = str(exercise.get("question") or exercise.get("text") or "").strip()
        correct_answer = str(exercise.get("correct_answer") or exercise.get("answer") or "").strip().lower()

        if correct_answer in ("да", "true", "1"):
            correct_answer = "yes"
        if correct_answer in ("нет", "false", "0"):
            correct_answer = "no"

        explanation = str(exercise.get("explanation") or "").strip()

        for prefix in ("Мини-упражнение:", "Упражнение:"):
            if question.startswith(prefix):
                question = question[len(prefix):].strip()

    if question and correct_answer in ("yes", "no"):
        return {
            "type": "yes_no",
            "question": question,
            "correct_answer": correct_answer,
            "explanation": explanation,
        }

    return fallback_exercise(translation)

def normalize_memory_updates(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item:
            result.append(item)
    return result[:5]

async def update_summary_from_memory_updates(
    session_id: uuid.UUID,
    current_summary: str,
    memory_updates: list[str],
):
    if not memory_updates:
        return

    messages = [
        {
            "role": "system",
            "content": get_summary_update_prompt(current_summary),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(memory_updates, ensure_ascii=False),
                }
            ],
        },
    ]

    result = await call_openrouter(messages, model=TEXT_MODEL)
    new_summary = (result.get("chat_summary") or "").strip()

    if not new_summary:
        print("Summary update returned empty summary.")
        return

    await save_chat_summary(session_id, new_summary)

async def rebuild_chat_summary(
    session_id: uuid.UUID,
    current_summary: str,
):
    async with db_module.db_pool.acquire() as conn:
        history_rows = await get_all_history(conn, session_id)

    if not history_rows:
        return

    history_messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history_rows
        if row["content"]
    ]

    if not history_messages:
        return

    messages = [
        {
            "role": "system",
            "content": get_summary_rebuild_prompt(current_summary),
        },
        *history_messages,
    ]

    result = await call_openrouter(messages, model=TEXT_MODEL)
    new_summary = (result.get("chat_summary") or "").strip()

    if not new_summary:
        print("Full summary rebuild returned empty summary.")
        return

    await save_chat_summary(session_id, new_summary)

async def refresh_chat_memory(
    session_id: uuid.UUID,
    memory_updates: list[str],
):
    try:
        async with db_module.db_pool.acquire() as conn:
            (
                current_summary,
                summary_message_count,
            ) = await get_chat_memory(conn, session_id)
            total_message_count = await get_message_count(conn, session_id)

        if memory_updates:
            await update_summary_from_memory_updates(
                session_id,
                current_summary,
                memory_updates,
            )
            return

        messages_since_summary = total_message_count - summary_message_count
        if messages_since_summary >= SUMMARY_REBUILD_EVERY_MESSAGES:
            await rebuild_chat_summary(session_id, current_summary)

    except Exception as e:
        print(f"Chat memory update error: {e}")

async def process_message(
    user_content,
    session_id: uuid.UUID,
    msg_type="text",
    media_url=None,
    user_text_for_history="",
    learner_level_hint="unknown",
):
    (
        target_lang,
        conversation_mode,
    ) = await get_user_settings(session_id)

    async with db_module.db_pool.acquire() as conn:
        history_rows = await get_recent_history(
            conn,
            session_id,
            RECENT_HISTORY_LIMIT,
        )
        chat_summary, _ = await get_chat_memory(conn, session_id)
        used_exercises = await get_recent_exercises(conn, session_id)

    used_exercises_block = "\n".join(
        f"- {question}" for question in used_exercises
    )
    preferred_exercise_type = detect_preferred_exercise_type(chat_summary)

    history_messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history_rows
    ]

    messages = [
        {
            "role": "system",
            "content": get_unified_prompt(
                target_lang,
                chat_summary=chat_summary,
                conversation_mode=conversation_mode,
                learner_level_hint=normalize_learner_level_hint(learner_level_hint),
                used_exercises=used_exercises_block,
                preferred_exercise_type=preferred_exercise_type,
            ),
        },
        *history_messages,
        {
            "role": "user",
            "content": user_content,
        },
    ]

    model = VISION_MODEL if msg_type == "image" else TEXT_MODEL
    temperature = (
        TRANSLATOR_TEMPERATURE
        if conversation_mode == "translator"
        else DEFAULT_TEMPERATURE
    )

    result = await call_openrouter(
        messages,
        model=model,
        temperature=temperature,
    )

    translation = (result.get("translation") or "").strip()
    if not translation:
        raise HTTPException(
            status_code=500,
            detail="ИИ не вернул ответ.",
        )

    returned_mode = result.get("mode")
    if returned_mode in ("translator", "teacher") and returned_mode != conversation_mode:
        await save_conversation_mode(session_id, returned_mode)
        conversation_mode = returned_mode

    memory_updates = normalize_memory_updates(result.get("memory_updates"))
    exercise = normalize_exercise(
        result.get("exercise"),
        conversation_mode,
        translation,
    )

    async with db_module.db_pool.acquire() as conn:
        (
            user_message_id,
            assistant_message_id,
        ) = await save_message(
            conn,
            session_id,
            user_text_for_history,
            translation,
            msg_type=msg_type,
            media_url=media_url,
            exercise=None,
        )

    await refresh_chat_memory(session_id, memory_updates)

    return {
        "translation": translation,
        "exercise": exercise,
        "media_url": media_url,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "mode": conversation_mode,
    }

async def process_text(
    text: str,
    session_id: uuid.UUID,
    learner_level_hint="unknown",
) -> dict:
    user_content = [{"type": "text", "text": text}]
    return await process_message(
        user_content,
        session_id,
        msg_type="text",
        user_text_for_history=text,
        learner_level_hint=learner_level_hint,
    )
