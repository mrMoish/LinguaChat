
import os
import json
import httpx
from dotenv import load_dotenv
from prompts import get_text_prompt

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = "openai/gpt-5.6-luna"
TARGET_LANG = "Spanish (Argentina)"


TEST_CASES = [
    {
        "name": "Первое сообщение",
        "history": [],
        "input": "я не знаю испанский",
    },
    {
        "name": "Ответ на вопрос AI",
        "history": [
            {
                "role": "assistant",
                "content": "Какой у тебя уровень испанского?"
            }
        ],
        "input": "примерно B1",
    },
    {
        "name": "Перевод русского",
        "history": [
            {
                "role": "assistant",
                "content": "Какой у тебя уровень испанского?"
            },
            {
                "role": "user",
                "content": "примерно B1"
            },
            {
                "role": "assistant",
                "content": "Отлично! Что ты обычно делаешь на испанском?"
            }
        ],
        "input": "я обычно смотрю фильмы",
    },
    {
        "name": "Испанский текст",
        "history": [
            {
                "role": "assistant",
                "content": "Какой у тебя уровень испанского?"
            }
        ],
        "input": "no sé nada",
    },
    {
        "name": "Английский текст",
        "history": [
            {
                "role": "assistant",
                "content": "Какой у тебя уровень испанского?"
            }
        ],
        "input": "it is cool",
    },
]


def test_translation_prompt():
    """Ручной тест prompt с историей диалога."""

    assert OPENROUTER_API_KEY, "OPENROUTER_API_KEY не найден в .env"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    for test_case in TEST_CASES:
        history_messages = test_case["history"].copy()

        if not history_messages:
            history_messages = [
                {
                    "role": "assistant",
                    "content": "Какой у тебя уровень испанского?"
                }
            ]

        text = test_case["input"]

        messages = [
            {
                "role": "system",
                "content": get_text_prompt(TARGET_LANG),
            },
            *history_messages,
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            },
        ]

        print("\n" + "=" * 70)
        print(f"TEST: {test_case['name']}")
        print("=" * 70)

        print("\nHISTORY:")
        for message in history_messages:
            print(f"{message['role'].upper()}: {message['content']}")

        print("\nINPUT:")
        print(text)

        print("\nSYSTEM PROMPT:")
        print(get_text_prompt(TARGET_LANG))

        print("\nOUTPUT:")
        print("-" * 70)

        payload = {
            "model": MODEL_NAME,
            "messages": messages,
            "response_format": {
                "type": "json_object"
            },
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )

                response.raise_for_status()
                data = response.json()

            if "choices" not in data or not data["choices"]:
                print("Модель не вернула ответ.")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                continue

            raw_text = data["choices"][0]["message"]["content"].strip()

            print(raw_text)

            print("\nPARSED TRANSLATION:")
            print("-" * 70)

            try:
                parsed = json.loads(raw_text)

                translation = parsed.get("translation")

                if translation is None:
                    print("Поле 'translation' отсутствует.")
                elif isinstance(translation, str):
                    print(translation)
                else:
                    print(
                        f"Поле 'translation' имеет неправильный тип: "
                        f"{type(translation).__name__}"
                    )

            except json.JSONDecodeError:
                print("Ответ не является корректным JSON.")

        except httpx.HTTPStatusError as e:
            print(f"[HTTP ERROR] {e.response.status_code}")
            print(e.response.text)

        except Exception as e:
            print(f"[ERROR] Запрос не удался: {e}")

        print("=" * 70)


if __name__ == "__main__":
    test_translation_prompt()
