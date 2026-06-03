# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版）
# =============================================================================
from collections import defaultdict
from typing import Optional
import logging

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT

logger = logging.getLogger("WechatBot")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 每个用户独立的对话历史（key = openid）
conversation_history: dict[str, list] = defaultdict(list)


def add_message(openid: str, role: str, content: str):
    history = conversation_history[openid]
    history.append({"role": role, "parts": [{"text": content}]})
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


def ask_gemini(openid: str, user_message: str) -> str:
    add_message(openid, "user", user_message)
    history = conversation_history[openid]
    chat_history = history[:-1]

    converted_history = [
        types.Content(
            role=msg["role"],
            parts=[types.Part(text=msg["parts"][0]["text"])]
        )
        for msg in chat_history
    ]

    try:
        chat = gemini_client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=PETEZZ_SYSTEM_PROMPT,
                max_output_tokens=1024,
                temperature=0.8,
                safety_settings=[
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                ]
            ),
            history=converted_history,
        )
        response = chat.send_message(user_message)
        reply = response.text.strip() if response.text else "这我不懂欸"
        add_message(openid, "model", reply)
        return reply

    except Exception as e:
        logger.error(f"Gemini API 调用失败: {e}")
        return "这我不懂欸"
