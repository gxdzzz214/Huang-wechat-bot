# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版）
# =============================================================================
from collections import defaultdict
import logging

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT

logger = logging.getLogger("WechatBot")

genai.configure(api_key=GEMINI_API_KEY)

# 每个用户独立的对话历史（key = openid）
conversation_history: dict[str, list] = defaultdict(list)

WECHAT_OFFICIAL_ADDON = """

【公众号模式专属规则】
- 禁止使用 ||| 分隔符，改用换行符分隔多句话
- 保持原有的简短风格
"""


def add_message(openid: str, role: str, content: str):
    history = conversation_history[openid]
    history.append({"role": role, "parts": content})
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


def ask_gemini(openid: str, user_message: str) -> str:
    add_message(openid, "user", user_message)
    history = conversation_history[openid]

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=PETEZZ_SYSTEM_PROMPT + WECHAT_OFFICIAL_ADDON,
            generation_config=genai.GenerationConfig(
                max_output_tokens=512,
                temperature=0.8,
            ),
            safety_settings={
                "HARASSMENT": "BLOCK_NONE",
                "HATE_SPEECH": "BLOCK_NONE",
                "SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "DANGEROUS_CONTENT": "BLOCK_NONE",
            }
        )

        # 构建历史，排除最后一条（当前用户消息）
        chat_history = history[:-1]
        chat = model.start_chat(history=chat_history)
        response = chat.send_message(user_message)

        reply = response.text.strip() if response.text else "这我不懂欸"
        reply = reply.replace(" ||| ", "\n").replace("|||", "\n")
        add_message(openid, "model", reply)
        logger.info(f"回复: {reply}")
        return reply

    except Exception as e:
        logger.error(f"Gemini API 调用失败: {e}")
        return "这我不懂欸"
