# =============================================================================
# chat.py —— Gemini API 调用模块（公众号版，含 Google 联网搜索 + 结果缓存）
# =============================================================================
from collections import defaultdict
import concurrent.futures
import threading
import time
import logging

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT

logger = logging.getLogger("WechatBot")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 每个用户独立的对话历史（key = openid）
conversation_history: dict[str, list] = defaultdict(list)

# 搜索结果缓存：openid → {"result": str, "ts": float}
# 当搜索超时时，后台线程继续运行并把结果存进来，用户再问一次就能拿到
_pending_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 结果保留 5 分钟

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


def _call_gemini(contents: list) -> str:
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


def _background_search(openid: str, user_message: str, contents: list):
    """超时后后台继续搜索，完成后写入缓存"""
    try:
        reply = _call_gemini(contents)
        reply = reply.replace(" ||| ", "\n").replace("|||", "\n")
        with _cache_lock:
            _pending_cache[openid] = {"result": reply, "ts": time.time()}
        # 同时写入对话历史，下次对话有上下文
        add_message(openid, "user", user_message)
        add_message(openid, "model", reply)
        logger.info(f"后台搜索完成 [{openid}]: {reply}")
    except Exception as e:
        logger.error(f"后台搜索失败: {e}")


def _pop_cache(openid: str) -> str | None:
    """取出缓存结果（取一次即删除，过期也删除）"""
    with _cache_lock:
        entry = _pending_cache.get(openid)
        if entry:
            del _pending_cache[openid]
            if time.time() - entry["ts"] < CACHE_TTL:
                return entry["result"]
    return None


def ask_gemini(openid: str, user_message: str, timeout: float = 4.5) -> str:
    # ① 优先检查有没有上一次搜索的缓存结果
    cached = _pop_cache(openid)
    if cached:
        logger.info(f"命中缓存 [{openid}]: {cached}")
        return cached

    contents = _build_contents(openid, user_message)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_gemini, contents)
        try:
            reply = future.result(timeout=timeout)
            reply = reply.replace(" ||| ", "\n").replace("|||", "\n")
            add_message(openid, "user", user_message)
            add_message(openid, "model", reply)
            logger.info(f"回复: {reply}")
            return reply

        except concurrent.futures.TimeoutError:
            # ② 超时：后台继续搜索，结果存入缓存，告诉用户再问一遍
            logger.warning(f"Gemini 超时 (>{timeout}s)，启动后台搜索")
            t = threading.Thread(
                target=_background_search,
                args=(openid, user_message, contents),
                daemon=True,
            )
            t.start()
            return "搜索中，稍等一下再问一遍呗"

        except Exception as e:
            logger.error(f"Gemini API 调用失败: {e}")
            return "这我不懂欸"
