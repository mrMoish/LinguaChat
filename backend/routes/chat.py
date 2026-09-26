import uuid
import json
import base64
import io
import asyncio
from typing import Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from PIL import Image, ImageOps
import pillow_heif

from backend.core.config import (
    OPENROUTER_API_KEY,
    MAX_IMAGE_SIZE,
    JPEG_QUALITY,
    TEXT_MODEL,
    TRANSLATOR_TEMPERATURE,
)
from backend.services.ai import (
    call_openrouter,
    normalize_exercise,
    process_message,
    process_text,
    detect_preferred_exercise_type,
    normalize_learner_level_hint,
)
from backend.services.storage import upload_to_supabase
from backend.services.audio import (
    is_audio_file,
    get_audio_format,
    get_audio_storage_content_type,
    transcribe_audio,
)
from backend.db import database as db_module
from backend.db.database import (
    get_session_id,
    get_welcome_exercise,
    save_welcome_exercise,
    clear_welcome_exercise,
    attach_welcome_exercises_to_message,
    update_message_media_url,
    get_user_settings,
    get_recent_history,
    get_chat_memory,
    get_recent_exercises,
)
from backend.prompts import get_exercise_prompt

router = APIRouter()
pillow_heif.register_heif_opener()

async def upload_image_and_update_history(
    image_bytes: bytes,
    message_id: int,
):
    try:
        media_url = await upload_to_supabase(
            image_bytes,
            "image/jpeg",
            "jpg",
        )
        await update_message_media_url(
            message_id,
            media_url,
        )
        print(f"Background image upload completed for message {message_id}")
    except Exception as e:
        print(f"Background image upload failed for message {message_id}: {e}")

@router.post("/welcome-exercise")
async def generate_welcome_exercise(
    req: Request,
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form("unknown"),
    preferred_exercise_type: Optional[str] = Form(None),
):
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    existing = await get_welcome_exercise(session_id)
    existing_question = str(
        (existing or {}).get("question") or ""
    ).lower()

    generic_greeting = any(
        marker in existing_question
        for marker in (
            "你好",
            "nǐ hǎo",
            "ни хао",
            "hola",
            "привет",
        )
    )

    if existing and not generic_greeting:
        await save_welcome_exercise(
            session_id,
            existing,
        )
        return {
            "exercise": existing,
            "session_id": session_id_str,
        }

    target_lang, _ = await get_user_settings(session_id)

    async with db_module.db_pool.acquire() as conn:
        recent_rows = await get_recent_history(
            conn,
            session_id,
            20,
        )
        chat_summary, _ = await get_chat_memory(
            conn,
            session_id,
        )
        used_exercises = await get_recent_exercises(
            conn,
            session_id,
        )

    context_parts = []
    if chat_summary:
        context_parts.append(
            f"Сохранённое обобщение:\n{chat_summary}"
        )

    if recent_rows:
        context_parts.append(
            "История сообщений:\n" + "\n".join(
                f"{row['role']}: {str(row['content'] or '')[:500]}"
                for row in recent_rows
                if str(row['content'] or '').strip()
            )
        )

    prompt = get_exercise_prompt(
        target_lang,
        normalize_learner_level_hint(
            learner_level_hint
        ),
        learning_context="\n\n".join(context_parts),
        used_exercises="\n".join(
            f"- {question}"
            for question in used_exercises
        ),
        preferred_exercise_type=(
            preferred_exercise_type
            if preferred_exercise_type in (
                "matching_pairs",
                "yes_no",
            )
            else detect_preferred_exercise_type(
                chat_summary
            )
        ),
    )

    result = await call_openrouter(
        [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": (
                    "Создай welcome-упражнение для нового шага. "
                    "Не привязывай его к последнему переводу: "
                    "выбери простую интересную тему или частотное "
                    "выражение, подходящее уровню пользователя. "
                    "Не используй стандартный пример «你好 (nǐ hǎo) "
                    "означает «привет»» и не начинай всегда с приветствия. "
                    "Выбери другую тему: еда, покупки, транспорт, "
                    "время, числа, повседневные действия или интересы "
                    "пользователя."
                ),
            },
        ],
        model=TEXT_MODEL,
        temperature=TRANSLATOR_TEMPERATURE,
    )

    exercise = normalize_exercise(
        result.get("exercise"),
        "translator",
        "",
    )

    await save_welcome_exercise(
        session_id,
        exercise,
    )

    return {
        "exercise": exercise,
        "session_id": session_id_str,
    }

@router.post("/message")
async def message(
    req: Request,
    text: Optional[str] = Form(None),
    file: UploadFile = File(None),
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form(
        "unknown"
    ),
    welcome_exercises: Optional[str] = Form(
        None
    ),
):
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    if not db_module.db_pool:
        raise HTTPException(
            status_code=503,
            detail="База данных не подключена.",
        )

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:
        session_id = uuid.UUID(
            session_id_str
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    saved_welcome_exercises = []

    if welcome_exercises:
        try:
            parsed_welcome = json.loads(welcome_exercises)
            if isinstance(parsed_welcome, dict):
                parsed_welcome = [parsed_welcome]
            if isinstance(parsed_welcome, list):
                saved_welcome_exercises = [
                    item
                    for item in parsed_welcome
                    if isinstance(item, dict)
                ]
        except Exception:
            saved_welcome_exercises = []

    if not saved_welcome_exercises:
        pending_welcome = await get_welcome_exercise(
            session_id
        )
        if pending_welcome:
            saved_welcome_exercises = [
                pending_welcome
            ]

    async def finalize_welcome_exercises(result):
        if saved_welcome_exercises:
            await attach_welcome_exercises_to_message(
                session_id,
                result.get("assistant_message_id"),
                saved_welcome_exercises,
            )
        await clear_welcome_exercise(session_id)

    # --------------------------------------------------------
    # FILE
    # --------------------------------------------------------
    if file:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Файл слишком большой.",
            )

        content_type = (
            file.content_type or ""
        ).lower()
        filename = file.filename or ""

        print(
            "Received file: "
            f"name={filename}, "
            f"type={content_type}, "
            f"size={len(contents)}"
        )

        # IMAGE
        if content_type.startswith("image/"):
            try:
                img = Image.open(io.BytesIO(contents))
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                img.thumbnail(
                    (MAX_IMAGE_SIZE, MAX_IMAGE_SIZE),
                    Image.LANCZOS,
                )
                buffer = io.BytesIO()
                img.save(
                    buffer,
                    format="JPEG",
                    quality=JPEG_QUALITY,
                )
                jpeg_bytes = buffer.getvalue()
            except Exception as e:
                print(f"Image processing error: {e}")
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image file",
                )

            image_base64 = base64.b64encode(jpeg_bytes).decode("utf-8")
            user_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "User sent an image. "
                        "Extract any text and "
                        "translate it. Do not "
                        "start a discussion about "
                        "the photo."
                    ),
                },
            ]

            result = await process_message(
                user_content,
                session_id,
                msg_type="image",
                media_url=None,
                user_text_for_history="",
                learner_level_hint=learner_level_hint,
            )

            asyncio.create_task(
                upload_image_and_update_history(
                    jpeg_bytes,
                    result["user_message_id"],
                )
            )

            await finalize_welcome_exercises(result)

            return {
                "translation": result["translation"],
                "exercise": result.get("exercise"),
                "media_url": None,
                "assistant_message_id": result["assistant_message_id"],
                "session_id": session_id_str,
            }

        # AUDIO
        elif is_audio_file(content_type, filename):
            audio_format = get_audio_format(content_type, filename)
            storage_content_type = get_audio_storage_content_type(audio_format)

            transcription = await transcribe_audio(
                contents,
                content_type,
                filename,
            )

            result = await process_message(
                [
                    {
                        "type": "text",
                        "text": (
                            "User sent an audio message.\n\n"
                            f"Transcription:\n{transcription}"
                        ),
                    }
                ],
                session_id,
                msg_type="audio",
                media_url=None,
                user_text_for_history=transcription,
                learner_level_hint=learner_level_hint,
            )

            async def upload_audio():
                try:
                    url = await upload_to_supabase(
                        contents,
                        storage_content_type,
                        audio_format,
                    )
                    await update_message_media_url(
                        result["user_message_id"],
                        url,
                    )
                    print("Background audio upload completed:", url)
                except Exception as e:
                    print(f"Background audio upload failed: {e}")

            asyncio.create_task(upload_audio())
            await finalize_welcome_exercises(result)

            return {
                "translation": result["translation"],
                "exercise": result.get("exercise"),
                "media_url": None,
                "assistant_message_id": result["assistant_message_id"],
                "transcription": transcription,
                "session_id": session_id_str,
            }

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type.",
            )

    # TEXT
    elif text and text.strip():
        result = await process_text(
            text.strip(),
            session_id,
            learner_level_hint=learner_level_hint,
        )
        await finalize_welcome_exercises(result)

        return {
            "translation": result["translation"],
            "exercise": result.get("exercise"),
            "media_url": None,
            "assistant_message_id": result["assistant_message_id"],
            "session_id": session_id_str,
        }

    else:
        raise HTTPException(
            status_code=400,
            detail="Message is empty.",
        )

@router.post("/exercise")
async def generate_next_exercise(
    req: Request,
    translation: str = Form(""),
    source_text: str = Form(""),
    assistant_message_id: Optional[int] = Form(None),
    answered_exercise: str = Form(""),
    session_id_form: Optional[str] = Form(
        None,
        alias="session_id",
    ),
    learner_level_hint: Optional[str] = Form("unknown"),
):
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="API Key not configured",
        )

    session_id_str = get_session_id(
        req,
        session_id_form,
    )

    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    target_lang, conversation_mode = await get_user_settings(session_id)

    async with db_module.db_pool.acquire() as conn:
        recent_rows = await get_recent_history(
            conn,
            session_id,
            20,
        )
        chat_summary, _ = await get_chat_memory(
            conn,
            session_id,
        )
        used_exercises = await get_recent_exercises(
            conn,
            session_id,
        )

    learning_context_parts = []
    if chat_summary:
        learning_context_parts.append(
            f"Сохранённое обобщение:\n{chat_summary}"
        )

    if recent_rows:
        recent_text = []
        for row in recent_rows:
            content = str(row["content"] or "").strip()
            if content:
                recent_text.append(
                    f"{row['role']}: {content[:500]}"
                )
        if recent_text:
            learning_context_parts.append(
                "Последние сообщения для выявления повторяющихся "
                "тем:\n" + "\n".join(recent_text)
            )

    learning_context = "\n\n".join(learning_context_parts)

    if assistant_message_id and answered_exercise:
        try:
            answered = json.loads(answered_exercise)
            if isinstance(answered, dict):
                async with db_module.db_pool.acquire() as conn:
                    raw = await conn.fetchval(
                        """
                        SELECT exercise_data
                        FROM chat_history
                        WHERE id = $1
                          AND session_id = $2
                          AND role = 'assistant'
                        """,
                        assistant_message_id,
                        session_id,
                    )
                    saved = []
                    if raw:
                        saved = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(saved, dict):
                        saved = [saved]
                    if not isinstance(saved, list):
                        saved = []

                    saved.append(answered)
                    await conn.execute(
                        """
                        UPDATE chat_history
                        SET exercise_data = $1
                        WHERE id = $2
                          AND session_id = $3
                          AND role = 'assistant'
                        """,
                        json.dumps(saved, ensure_ascii=False),
                        assistant_message_id,
                        session_id,
                    )
        except Exception as error:
            print(f"Exercise history save failed: {error}")

    prompt = get_exercise_prompt(
        target_lang,
        normalize_learner_level_hint(learner_level_hint),
        learning_context=learning_context,
        used_exercises="\n".join(f"- {q}" for q in used_exercises),
        preferred_exercise_type=detect_preferred_exercise_type(chat_summary),
    )

    context = (
        f"Исходная фраза пользователя:\n{source_text}\n\n"
        f"Перевод:\n{translation}"
    )

    result = await call_openrouter(
        [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": context,
                    }
                ],
            },
        ],
        model=TEXT_MODEL,
        temperature=TRANSLATOR_TEMPERATURE,
    )

    return {
        "exercise": normalize_exercise(
            result.get("exercise"),
            "translator",
            translation,
        )
    }

@router.get("/history")
async def get_history(
    req: Request,
    session_id: Optional[str] = None,
):
    session_id_str = get_session_id(req, session_id)
    try:
        session_uuid = uuid.UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    if db_pool:
        async with db_module.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    role,
                    content,
                    message_type,
                    media_url,
                    exercise_data
                FROM chat_history
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                session_uuid,
            )

            history = []
            for r in rows:
                exercise = None
                raw_exercise = r["exercise_data"]
                if raw_exercise:
                    try:
                        if isinstance(raw_exercise, str):
                            exercise = json.loads(raw_exercise)
                        elif isinstance(raw_exercise, dict):
                            exercise = raw_exercise
                    except Exception:
                        exercise = None

                if not isinstance(exercise, (dict, list)):
                    exercise = None

                history.append(
                    {
                        "id": r["id"],
                        "role": r["role"],
                        "content": r["content"],
                        "message_type": r["message_type"] or "text",
                        "media_url": r["media_url"],
                        "exercise": exercise,
                    }
                )

            return {
                "session_id": session_id_str,
                "history": history,
                "messages": history,
            }

    return {
        "session_id": session_id_str,
        "history": [],
        "messages": [],
    }
