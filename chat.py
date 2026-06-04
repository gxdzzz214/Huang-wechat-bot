# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版，含 Google 联网搜索）
# =============================================================================
from collections import defaultdict
import concurrent.futures
import logging

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT

logger = logging.getLogger("WechatBot")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 每个用户独立的对话历史（key = openid）
# 格式: [{"role": "user"|"model", "text": str}, ...]
conversation_history: dict[str, list] = defaultdict(list)

WECHAT_OFFICIAL_ADDON = """

【公众号模式专属规则】
- 禁止使用 ||| 分隔符，改用换行符分隔多句话
- 保持原有的简短风格
- 如果需要查实时信息（赛事、价格、新闻等），联网搜索后用自己的语气简短转述
- 【强制】无论搜到什么内容，回复必须100%使用中文，绝对禁止英文出现
- 【强制】不要把搜索结果原文粘贴进回复，用自己的话说
"""

SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]


def add_message(openid: str, role: str, text: str):
    history = conversation_history[openid]
    history.append({"role": role, "text": text})
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


def _build_contents(openid: str, user_message: str) -> list:
    """把历史记录 + 当前消息转换成 Gemini Content 列表"""
    history = conversation_history[openid]
    contents = []
    for msg in history:
        contents.append(
            types.Content(
                role=msg["role"],
                parts=[types.Part(text=msg["text"])],
            )
        )
    # 追加当前用户消息
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        )
    )
    return contents


def _call_gemini(contents: list) -> str:
    """直接调用 generate_content（带 Google Search grounding，单次 HTTP 请求）"""
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=PETEZZ_SYSTEM_PROMPT + WECHAT_OFFICIAL_ADDON,
            max_output_tokens=512,
            temperature=0.8,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            safety_settings=SAFETY_SETTINGS,
        ),
    )
    return response.text.strip() if response.text else "这我不懂欸"


def ask_gemini(openid: str, user_message: str, timeout: float = 4.5) -> str:
    contents = _build_contents(openid, user_message)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_gemini, contents)
        try:
            reply = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.warning(f"Gemini 超时 (>{timeout}s)，返回提示")
            return "在查呢，你再问一遍"
        except Exception as e:
            logger.error(f"Gemini API 调用失败: {e}")
            return "这我不懂欸"

    reply = reply.replace(" ||| ", "\n").replace("|||", "\n")

    # 成功后才写入历史
    add_message(openid, "user", user_message)
    add_message(openid, "model", reply)
    logger.info(f"回复: {reply}")
    return reply
