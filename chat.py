# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版，DuckDuckGo 快速联网搜索）
# =============================================================================
from collections import defaultdict
import logging
import re

from google import genai
from google.genai import types

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT

logger = logging.getLogger("WechatBot")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 每个用户独立的对话历史（key = openid）
conversation_history: dict[str, list] = defaultdict(list)

# 需要实时搜索的关键词
SEARCH_TRIGGERS = [
    "今天", "现在", "最新", "最近", "昨天", "今晚", "明天",
    "比赛", "赛事", "结果", "比分", "排名", "战队", "选手",
    "价格", "行情", "多少钱", "大盘", "皮肤", "刀",
    "新闻", "发生", "事件", "热搜",
]

WECHAT_OFFICIAL_ADDON = """

【公众号模式专属规则】
- 禁止使用 ||| 分隔符，改用换行符分隔多句话
- 保持原有的简短风格
- 如果收到 [搜索结果] 标记，请基于搜索内容用自己的语气简短回答
- 【强制】回复必须100%使用中文，绝对禁止英文出现在回复中
- 【强制】不要把原文粘贴进回复，用自己的话说
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


def needs_search(text: str) -> bool:
    """判断这条消息是否需要实时搜索"""
    return any(kw in text for kw in SEARCH_TRIGGERS)


def quick_search(query: str, max_results: int = 3) -> str:
    """用 DuckDuckGo 快速搜索，返回摘要文本"""
    if not DDGS_AVAILABLE:
        return ""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return ""
        snippets = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            if body:
                snippets.append(f"{title}: {body}")
        combined = "\n".join(snippets)
        # 限制长度，避免太长影响速度
        return combined[:800]
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}")
        return ""


def add_message(openid: str, role: str, text: str):
    history = conversation_history[openid]
    history.append({"role": role, "text": text})
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


def _build_contents(openid: str, user_message: str) -> list:
    history = conversation_history[openid]
    contents = []
    for msg in history:
        contents.append(
            types.Content(
                role=msg["role"],
                parts=[types.Part(text=msg["text"])],
            )
        )
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        )
    )
    return contents


def ask_gemini(openid: str, user_message: str) -> str:
    # 判断是否需要搜索
    search_context = ""
    if needs_search(user_message) and DDGS_AVAILABLE:
        logger.info(f"触发联网搜索: {user_message}")
        search_context = quick_search(user_message)
        if search_context:
            logger.info(f"搜索到内容 ({len(search_context)} chars)")

    # 如果有搜索结果，拼接到用户消息里
    if search_context:
        enhanced = f"[搜索结果]\n{search_context}\n\n[用户问题]\n{user_message}"
    else:
        enhanced = user_message

    contents = _build_contents(openid, enhanced)

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=PETEZZ_SYSTEM_PROMPT + WECHAT_OFFICIAL_ADDON,
                max_output_tokens=512,
                temperature=0.8,
                safety_settings=SAFETY_SETTINGS,
                # 不使用 google_search Tool，避免 AFC 超时
            ),
        )
        reply = response.text.strip() if response.text else "这我不懂欸"
        reply = reply.replace(" ||| ", "\n").replace("|||", "\n")

        # 历史记录存原始用户消息（不含搜索结果）
        add_message(openid, "user", user_message)
        add_message(openid, "model", reply)
        logger.info(f"回复: {reply}")
        return reply

    except Exception as e:
        logger.error(f"Gemini API 调用失败: {e}")
        return "这我不懂欸"
