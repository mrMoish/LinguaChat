def get_translation_prompt(target_lang_name, user_level, recent_summary):
    return f"""Translate non-Russian text into Russian; Translate Russian text into {target_lang_name}.

Return STRICT JSON without markdown wrapping:
{{
"translation": "your response"
}}
"""

# Explain in Russian what is shown in the image
def get_image_analysis_prompt(target_language):
    return f"""Translate it into Russian.

Return STRICT JSON without markdown wrapping:
{{
  "translation": "your response"
}}
"""