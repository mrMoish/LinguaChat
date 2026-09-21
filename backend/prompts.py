def get_text_prompt(target_lang_name):
    return f"""If the input is Russian, translate it into {target_lang_name}.
If the input is not Russian, translate it into Russian.
Always translate.

After the translation, add an empty line followed by a natural, relevant Russian question.

Return STRICT JSON without markdown wrapping:
{{
"translation": "your response"
}}
"""

# Explain in Russian what is shown in the image
def get_image_prompt(target_language):
    return f"""Translate it into Russian.

Always end your response with a natural, contextually relevant question.
Put the question after an empty line.

Return STRICT JSON without markdown wrapping:
{{
  "translation": "your response"
}}
"""