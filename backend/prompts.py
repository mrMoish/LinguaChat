def get_translation_prompt(target_lang_name, user_level, recent_summary):
    return f"""
Определи язык входного текста.

- Если входной текст НЕ на русском языке, переведи его НА РУССКИЙ.
- Если входной текст НА РУССКОМ языке, переведи его НА {target_lang_name}.

Верни СТРОГИЙ JSON без markdown-обёртки:
{{
  "translation": "результат"
}}
"""