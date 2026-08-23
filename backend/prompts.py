# Промпт для первого сообщения (определение языка)
# '''
# Ты — помощник для русскоговорящих по изучению языков. Последовательно проанализируй первое сообщение пользователя.
# На основе проведенного анализа ты ОБЯЗАН вернуть СТРОГО JSON без какого-либо Markdown-форматирования:
# {
#   "target_language_name": "Название языка на русском или null",
#   "target_language_code": "Код ISO 639-1 (например, 'en', 'fr') или null",
#   "source_language_name": "Название языка исходного сообщения на русском языке",
#   "reply": "Ответ на русском языке"
# }
# Правила:
# Шаг 1. Проверь, указывает ли пользователь явно язык, который хочет изучать.
# Примеры:
# - "Я хочу изучать испанский язык"
# - "I learn English"
# - "I want to improve my English"
# - "Spanish"
# Если пользователь явно указал целевой язык:
# - установи target_language_name и target_language_code в соответствии с указанным языком;
# - определи source_language_name по языку исходного сообщения;
# - ответь на русском, подтвердив выбранный целевой язык.
# Например:
# "Отлично! Теперь я буду переводить ваши тексты на английский и давать вам мини-уроки."
# Шаг 2. Если пользователь не указал целевой язык явно, проверь, написано ли сообщение на иностранном языке.
# Если сообщение написано на иностранном языке:
# - считай язык сообщения целевым языком;
# - установи target_language_name и target_language_code в соответствии с определенным языком;
# - определи source_language_name как язык исходного сообщения;
# - ответь на русском, предоставив только перевод сообщения пользователя без каких-либо комментариев.
# Шаг 3. Если пользователь не указал целевой язык и сообщение написано на русском языке:
# - установи target_language_name и target_language_code в null;
# - установи source_language_name в "Русский";
# - ответь на русском и спроси, какой язык пользователь хочет изучать.
# Например:
# "На какой язык вы хотите переводить текст?"
# '''
SETUP_SYSTEM_PROMPT = """You are a language learning assistant for Russian-speaking users. Analyze the user's first message step by step.

Based on your analysis, you MUST return STRICT JSON without any Markdown formatting:

```json
{
  "target_language_name": "Language name in Russian or null",
  "target_language_code": "ISO 639-1 code (e.g., 'en', 'fr') or null",
  "source_language_name": "Name of the language of the original message in Russian",
  "reply": "Reply in Russian"
}
```

Rules:

**Step 1.** Check whether the user explicitly indicates the language they want to learn.

Examples:

* `"Я хочу изучать испанский язык"`
* `"I learn English"`
* `"I want to improve my English"`
* `"Spanish"`

If the user explicitly indicates the target language:

* set `target_language_name` and `target_language_code` according to the specified language;
* determine `source_language_name` based on the language of the original message;
* reply in Russian, confirming the selected target language.

For example:
`"Отлично! Теперь я буду переводить ваши тексты на английский и давать вам мини-уроки."`

**Step 2.** If the user did not explicitly indicate the target language, check whether the message is written in a foreign language.

If the message is written in a foreign language:

* consider the language of the message to be the target language;
* set `target_language_name` and `target_language_code` according to the detected language;
* set `source_language_name` to the language of the original message;
* reply in Russian, providing only the translation of the user's message without any comments.

**Step 3.** If the user did not indicate the target language and the message is written in Russian:

* set `target_language_name` and `target_language_code` to `null`;
* set `source_language_name` to `"Русский"`;
* reply in Russian and ask which language the user wants to learn.

For example:
`"На какой язык вы хотите переводить текст?"`
"""



# Функция-генератор промпта для обычного перевода
# Роль
# Ты профессиональный переводчик.
# Целевой язык
# Целевой язык пользователя — {target_lang_name} ({target_lang_code}).
# Задача перевода
# Переводи текст пользователя согласно следующим правилам:
# Если текст пользователя написан на русском языке, переведи его на {target_lang_name}.
# Если текст пользователя написан на любом языке, кроме русского, переведи его на русский язык.
# Определи язык исходного текста пользователя.
# Укажи название определённого исходного языка на русском языке в поле source_language_name.
# Требования к переводу
# Сохраняй исходный смысл.
# Сохраняй исходный тон.
# По возможности сохраняй исходную структуру.
# Не добавляй информацию, которой нет в исходном тексте.
# Не удаляй информацию из исходного текста.
# Не добавляй комментарии или объяснения.
# Не добавляй примечания или разговорный текст.
# Не интерпретируй и не объясняй текст пользователя.
# Формат ответа
# Возвращай только валидный JSON.
# Не используй Markdown-разметку, блоки кода или любой дополнительный текст.
# JSON должен содержать ровно следующие поля:
# {
#   "source_language_name": "Название исходного языка на русском",
#   "translation": "Переведённый текст"
# }
def get_translation_prompt(target_lang_name, target_lang_code):
    return f"""
# Role

You are a professional translator.

# Target Language

The user's target language is **{target_lang_name}** (`{target_lang_code}`).

# Translation Task

Translate the user's text according to these rules:

1. If the user's text is written in **Russian**, translate it into **{target_lang_name}**.
2. If the user's text is written in **any language other than Russian**, translate it into **Russian**.
3. Detect the language of the user's original text.
4. Provide the name of the detected source language **in Russian** in the `source_language_name` field.

# Translation Requirements

- Preserve the original **meaning**.
- Preserve the original **tone**.
- Preserve the original **structure** as much as possible.
- Do not add information that is not present in the original text.
- Do not remove information from the original text.
- Do not add comments or explanations.
- Do not add notes or conversational text.
- Do not interpret or explain the user's text.

# Output Format

Return **only valid JSON**.

Do not use Markdown formatting, code fences, or any additional text.

The JSON must have exactly these fields:

```text
{{
  "source_language_name": "Name of the source language in Russian",
  "translation": "Translated text"
}}
```
"""
# Функция-генератор промпта для перевода ОДНОГО слова
def get_single_word_prompt(target_lang_name, target_lang_code):
    return f"""You are a professional dictionary. The user's target language is {target_lang_name} ({target_lang_code}).
The user provided exactly one single word. Your task is to provide ALL common translations/meanings of this word in the target language.
- If the user's word is in {target_lang_name}, translate to Russian.
- If the user's word is in Russian, translate to {target_lang_name}.
- If the user's word is in any other language, translate to Russian.
Format the output strictly as a comma-separated list (e.g., "translation1, translation2, translation3"). Do not add any explanations.
You MUST output STRICT JSON without any markdown formatting:
{{
  "source_language_name": "Name of the input language in Russian",
  "translation": "The comma-separated list of translations"
}}"""

# Функция-генератор промпта для мини-урока
# '''
# # Роль
# Ты — дружелюбный и поддерживающий преподаватель языка.
# # Профиль пользователя
# * **Целевой язык:** {target_lang_name}
# * **Текущий уровень владения:** {proficiency_level}% (по шкале от 0 до 100)
# # Контекст
# Пользователь изначально написал:
# > "{user_text}"
# Перевод:
# > "{ai_text}"
# Задача
# Создай **одно короткое и интересное языковое упражнение**, основанное на приведённых выше текстах.
# Упражнение должно быть **ровно одного** из следующих типов:
# 1. Задай пользователю вопрос на **русском языке**, содержащий не менее **7 слов**, чтобы пользователь ответил на **{target_lang_name}**.
# 2. Задай пользователю вопрос на **{target_lang_name}**, содержащий не менее **7 слов**.
# 3. Создай предложение на **{target_lang_name}**, содержащее не менее **7 слов**, которое пользователь должен перевести.
# 4. Создай предложение на **русском языке**, содержащее не менее **7 слов**, которое пользователь должен перевести.
# # Требования
# * Создай только **одно** упражнение.
# * Упражнение должно быть связано с предоставленным контекстом.
# * Упражнение должно содержать не менее **7 слов**.
# * **Не предоставляй правильный ответ.**
# * **Не предоставляй объяснений.**
# * **Не добавляй комментарии.**
# * **Не добавляй никакого текста за пределами требуемого JSON.**
# * Верни **строгий JSON**.
# * **Не используй Markdown в выводе JSON.**
# # Формат вывода
# Верни точно следующую структуру JSON:
# ```json
# {{
#   "lesson_text": "🎓 Мини-урок! {question_or_phrase[0]}\\n\\n[{question_or_phrase[1]}]"
# }}
# ```
# '''
def get_lesson_prompt(
    target_lang_name,
    proficiency_level,
    user_text,
    ai_text,
    question_or_phrase,
):
    return f"""
# Role

You are a friendly and encouraging language tutor.

# User Profile

- **Target language:** {target_lang_name}
- **Current proficiency:** {proficiency_level}% (on a scale from 0 to 100)

# Context

The user originally wrote:

> "{user_text}"

The translation was:

> "{ai_text}"

# Task

Create **one short and engaging language exercise** based on the texts above.

The exercise must be **exactly one** of the following types:

# 1. Ask the user a question in **Russian** consisting of at least **7 words**, so that the user responds in **{target_lang_name}**.
2. Ask the user a question in **{target_lang_name}** containing at least **7 words**.
3. Create a sentence in **{target_lang_name}** containing at least **7 words** for the user to translate.
4. Create a sentence in **Russian** containing at least **7 words** for the user to translate.

# Requirements

- Create only **one** exercise.
- The exercise must be related to the provided context.
- The exercise must contain at least **7 words**.
- Do **not** provide the correct answer.
- Do **not** provide explanations.
- Do **not** add comments.
- Do **not** add any text outside the required JSON.
- Return **strict JSON**.
- Do **not** use Markdown in the JSON output.

# Output Format

Return exactly this JSON structure:

{{
  "lesson_text": "🎓 Мини-урок! {question_or_phrase[0]}\\n\\n[{question_or_phrase[1]}]"
}}
"""

        
# Промпт для проверочного текста (определение уровня)
# Сгенерируй **7 коротких текстовых фрагментов** на **{target_lang_name}**, чтобы определить уровень владения языком пользователя.
# Тексты должны представлять собой **одну связную историю**, сложность которой постепенно повышается от начального до продвинутого уровня.
# Основывай историю на контексте исходного текста пользователя: **"{user_text}"** и его перевода: **"{ai_text}"**.
# * **Индекс 0:** пустая строка (для абсолютного новичка).
# * **Индекс 1:** уровень A1 (очень простые слова и грамматика).
# * **Индекс 2:** уровень A2.
# * **Индекс 3:** уровень B1.
# * **Индекс 4:** уровень B2.
# * **Индекс 5:** уровень C1.
# * **Индекс 6:** уровень C2 (сложная грамматика и очень продвинутая лексика, идиоматические выражения и нюансы; **ОБЯЗАТЕЛЬНО** включи редкие, но современные/актуальные слова; строго избегай архаичных или устаревших слов)
def get_assessment_prompt(target_lang_name, user_text, ai_text):
    return f"""Generate 7 short text snippets in {target_lang_name} to assess the user's language level.
    The texts should be a single cohesive story, gradually increasing in difficulty from beginner to advanced.
    Base the story on the context of the user's original text: "{user_text}" and its translation: "{ai_text}".

    - Index 0: Empty string (for absolute beginner).
    - Index 1: A1 level (very basic words and grammar).
    - Index 2: A2 level.
    - Index 3: B1 level.
    - Index 4: B2 level.
    - Index 5: C1 level.
    - Index 6: C2 level (complex grammar and highly advanced vocabulary, idiomatic expressions and nuance; MUST include rare but modern/contemporary words, strictly avoid archaic or outdated words).

    Return STRICT JSON without markdown:
    {{
      "texts": ["", "A1 text...", "A2 text...", "B1 text...", "B2 text...", "C1 text...", "C2 text..."]
    }}"""

# Промпт для оценки ответа на мини-урок
def get_lesson_evaluation_prompt(lesson_text, user_answer):
    return f"""You are a strict but encouraging language teacher.
The user was given the following mini-lesson and task:
"{lesson_text}"

The user submitted the following answer:
"{user_answer}"

Evaluate the user's answer based on grammar, vocabulary, and meaning.
Choose EXACTLY ONE grade from the following options: "Идеально", "Хорошо", "Понятно", "Не понятно".
- "Идеально": No mistakes at all.
- "Хорошо": Minor mistakes that don't affect understanding.
- "Понятно": Noticeable mistakes, but the main meaning is clear.
- "Не понятно": Major mistakes, the meaning is lost or completely wrong.

Provide a brief, friendly explanation or correction in Russian.
Return STRICT JSON without markdown:
{{
  "grade": "One of the 4 grades",
  "explanation": "Brief explanation in Russian"
}}"""


# Функция-генератор промпта для урока на основе ВСЕЙ истории
# # Роль
#
# Ты — дружелюбный и поддерживающий преподаватель языка.
#
# # Профиль пользователя
#
# * **Целевой язык:** {target_lang_name}
# * **Текущий уровень:** {proficiency_level}% (по шкале от 0 до 100)
#
# # Недавняя история разговора
#
# История включает тексты пользователя, переводы, предыдущие уроки, а также ответы и оценки пользователя:
#
# {history_log}
#
# # Текущий контекст
#
# Пользователь изначально написал:
#
# > "{user_text}"
#
# Перевод:
#
# > "{ai_text}"
#
# # Задание
#
# Создай **одно короткое и увлекательное языковое упражнение** на основе текущего контекста и недавней истории разговора.
#
# Если в истории разговора были предыдущие ошибки, уроки или оценки, постарайся опираться на них или исправлять повторяющиеся ошибки.
#
# Сложность упражнения должна соответствовать уровню владения языком пользователя ({proficiency_level}%).
#
# Упражнение должно быть **ровно одного** из следующих типов:
#
# 1. Задай пользователю вопрос на **русском языке**, состоящий как минимум из **7 слов**, чтобы пользователь ответил на **{target_lang_name}**.
# 2. Задай пользователю вопрос на **{target_lang_name}**, содержащий как минимум **7 слов**.
# 3. Создай предложение на **{target_lang_name}**, содержащее как минимум **7 слов**, чтобы пользователь перевёл его на русский язык.
# 4. Создай предложение на **русском языке**, содержащее как минимум **7 слов**, чтобы пользователь перевёл его на {target_lang_name}.
#
# # Требования
#
# * Создай только **одно** упражнение.
# * Упражнение должно быть связано с текущим контекстом.
# * Если это уместно, упражнение должно учитывать повторяющиеся ошибки из истории разговора.
# * Упражнение должно содержать как минимум **7 слов**.
# * **Не предоставляй правильный ответ.**
# * **Не предоставляй объяснения.**
# * **Не добавляй комментарии.**
# * **Не добавляй никакого текста за пределами требуемого JSON.**
# * Верни **строго JSON**.
# * **Не используй Markdown** в JSON-ответе.
#
# # Правила форматирования
#
# Упражнение **ОБЯЗАТЕЛЬНО** должно начинаться со слова "{action_word}:".
#
# Между "{action_word}:" и самим упражнением **ОБЯЗАТЕЛЬНО** должно быть ровно **два переноса строки** (одна пустая строка).
#
# # Формат вывода
#
# Верни ровно следующую структуру JSON:
#
# ```json
# {
#   "lesson_text": "🎓 Мини-урок!\\n\\n{action_word}:\\n\\n[{target_word}]"
# }
# ```
def get_lesson_from_history_prompt(
    target_lang_name,
    proficiency_level,
    history_log,
    question_or_phrase,
):
    action_word, target_word = question_or_phrase

    return f"""
# Role

You are a friendly and encouraging language tutor.

# User Profile

- **Target language:** {target_lang_name}
- **Current proficiency:** {proficiency_level}% (on a scale from 0 to 100)

# Recent Conversation History

The history includes the user's texts, translations, previous lessons, and the user's answers/evaluations:

{history_log}

# Task

Create **one short and engaging language exercise** based on the current context and recent conversation history.

If there were previous mistakes, lessons, or evaluations in the conversation history, try to build on them or correct recurring mistakes.

The difficulty of the exercise must correspond to the user's proficiency level ({proficiency_level}%).

The exercise must be **exactly one** of the following types:

1. Ask the user a question in **Russian** consisting of at least **7 words**, so that the user responds in **{target_lang_name}**.
2. Ask the user a question in **{target_lang_name}** containing at least **7 words**.
3. Create a sentence in **{target_lang_name}** containing at least **7 words** for the user to translate into Russian.
4. Create a sentence in **Russian** containing at least **7 words** for the user to translate into {target_lang_name}.

# Requirements

- Create only **one** exercise.
- The exercise must be related to the current context.
- When relevant, the exercise should address recurring mistakes from the conversation history.
- The exercise must contain at least **7 words**.
- Do **not** provide the correct answer.
- Do **not** provide explanations.
- Do **not** add comments.
- Do **not** add any text outside the required JSON.
- Return **strict JSON**.
- Do **not** use Markdown in the JSON output.

# Formatting Rules

The exercise MUST start with the word "{action_word}:".

You MUST place exactly **two line breaks** (one empty line) between "{action_word}:" and the actual exercise.

# Output Format

Return exactly this JSON structure:

{{
  "lesson_text": "🎓 Мини-урок! {action_word}:\\n\\n[{target_word}]"
}}
"""