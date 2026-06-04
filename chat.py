# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版，快速联网搜索）
# =============================================================================
from collections import defaultdict
import logging
import urllib.request
import urllib.parse
import json
import re

from google import genai
from google.genai import types

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
    "新闻", "发生", "事件", "热搜", "直播",
]

WECHAT_OFFICIAL_ADDON = """

【公众号模式专属规则】
- 禁止使用 ||| 分隔符，改用换行符分隔多句话
- 保持原有的简短风格
- 如果消息里有 [实时搜索结果]，必须基于这些内容回答，用自己的语气简短说
- 【强制】回复必须100%使用中文，绝对禁止英文出现
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
    return any(kw in text for kw in SEARCH_TRIGGERS)


def quick_search(query: str) -> str:
    """用 DuckDuckGo Instant Answer API + HTML 搜索获取结果摘要"""
    try:
        # 优先用 Instant Answer API（无需 key，极快）
        q = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())

        snippets = []
        if data.get("AbstractText"):
            snippets.append(data["AbstractText"])
        for r in data.get("RelatedTopics", [])[:5]:
            if isinstance(r, dict) and r.get("Text"):
                snippets.append(r["Text"])

        if snippets:
            result = "\n".join(snippets)[:800]
            logger.info(f"DDG Instant Answer ({len(result)} chars)")
            return result

        # 如果 Instant Answer 没内容，用搜索结果摘要
        url2 = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=2) as resp2:
            data2 = json.loads(resp2.read().decode())

        snippets2 = []
        for r in data2.get("Results", [])[:3]:
            text = r.get("Text", "")
            if text:
                snippets2.append(text)

        if snippets2:
            result2 = "\n".join(snippets2)[:800]
            logger.info(f"DDG Results ({len(result2)} chars)")
            return result2

        logger.info("DDG 返回空结果")
        return ""

    except Exception as e:
        logger.warning(f"DDG 搜索失败: {e}")
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
    search_context = ""
    if needs_search(user_message):
        logger.info(f"触发联网搜索: {user_message}")
        search_context = quick_search(user_message)

    if search_context:
        prompt = (
            f"[实时搜索结果]\n{search_context}\n\n"
            f"[用户问题] {user_message}\n\n"
            f"请基于以上搜索结果，用你自己的语气简短回答用户问题，全程中文。"
        )
    else:
        prompt = user_message

    contents = _build_contents(openid, prompt)

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=PETEZZ_SYSTEM_PROMPT + WECHAT_OFFICIAL_ADDON,
                max_output_tokens=512,
                temperature=0.8,
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        reply = response.text.strip() if response.text else "这我不懂欸"
        reply = reply.replace(" ||| ", "\n").replace("|||", "\n")

        add_message(openid, "user", user_message)
        add_message(openid, "model", reply)
        logger.info(f"回复: {reply}")
        return reply

    except Exception as e:
        logger.error(f"Gemini API 调用失败: {e}")
        return "这我不懂欸"
