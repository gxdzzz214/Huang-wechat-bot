# =============================================================================
# message_handler.py —— 核心消息处理模块
# 负责：上下文管理、Gemini API调用、分段切分与发送
# 使用新版 google-genai SDK（google.generativeai 已废弃）
# =============================================================================

import re
import time
import random
import logging
from collections import defaultdict
from typing import Optional

# 新版 SDK：from google import genai
from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_HISTORY_MESSAGES,
    SEND_INTERVAL_BASE,
    SEND_INTERVAL_JITTER,
    MAX_CHUNK_LENGTH,
    DEBUG_MODE,
)
from persona import PETEZZ_SYSTEM_PROMPT

# 配置日志格式
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PetezzBot")

# 初始化新版 Gemini 客户端（一次性创建，全局复用）
import httpx
gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={'timeout': 30000}  # 30秒超时
)

# =============================================================================
# 上下文记忆管理
# 每个用户（用昵称作key）对应一个独立的历史列表
# 存储格式: [{"role": "user"|"model", "parts": [{"text": "..."}]}, ...]
# =============================================================================
conversation_history: dict[str, list] = defaultdict(list)


def get_history(name: str) -> list:
    """获取指定用户的对话历史"""
    return conversation_history[name]


def add_message(name: str, role: str, content: str):
    """
    向指定用户的对话历史中追加一条消息。
    role 取值: "user" 或 "model"
    超出 MAX_HISTORY_MESSAGES 时自动丢弃最早的消息。
    """
    history = conversation_history[name]
    history.append({"role": role, "parts": [{"text": content}]})

    while len(history) > MAX_HISTORY_MESSAGES:
        removed = history.pop(0)
        logger.debug(f"[上下文修剪] 删除 {name} 最旧消息: {removed['parts'][0]['text'][:20]}...")


def clear_history(name: str):
    """清空指定用户的对话历史（调试用）"""
    conversation_history[name].clear()
    logger.info(f"[上下文] 已清空 {name} 的对话历史")


# =============================================================================
# Gemini API 调用（新版 google-genai SDK）
# =============================================================================
def ask_gemini(name: str, user_message: str) -> Optional[str]:
    """
    将用户消息连同历史上下文一起发给 Gemini，返回原始回复文本。
    返回 None 代表调用失败。
    """
    # 先把当前用户消息加入历史
    add_message(name, "user", user_message)

    # chat_history = 除最新这条之外的所有历史，转换为新 SDK 的 Content 对象
    history = get_history(name)
    chat_history = history[:-1]

    # 将 dict 格式的历史转换为新 SDK 的 types.Content 对象列表
    converted_history = [
        types.Content(
            role=msg["role"],
            parts=[types.Part(text=msg["parts"][0]["text"])]
        )
        for msg in chat_history
    ]

    logger.debug(f"[Gemini] 历史共 {len(converted_history)} 条，发送: {user_message[:30]}")

    try:
        # 创建携带历史上下文的聊天会话
        chat = gemini_client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=PETEZZ_SYSTEM_PROMPT,
                max_output_tokens=1024,  # 回复极短(平均<10字)，大幅缩减以提升速度
                temperature=0.8,         # 稍低温度让人设更稳定
                safety_settings=[
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
            ),
            history=converted_history,
        )

        # 发送当前消息并获取回复
        response = chat.send_message(user_message)
        
        if not response.text:
            logger.error(f"[Gemini] 返回为空，可能触发了安全拦截。详细: {response}")
            reply_text = "这我不懂欸 ||| [捂脸]"
        else:
            reply_text = response.text.strip()

        # 把模型回复加入历史
        add_message(name, "model", reply_text)

        logger.debug(f"[Gemini] 原始回复: {reply_text}")
        return reply_text

    except Exception as e:
        err_str = str(e)
        if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
            logger.error("[Gemini] API Key 无效，请检查 config.py 中的 GEMINI_API_KEY")
        elif "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
            logger.error("[Gemini] API 配额耗尽或频率超限，请稍后再试")
        else:
            logger.error(f"[Gemini] API 调用异常: {e}")
        return None


# =============================================================================
# 分段切分函数
# 将 Gemini 返回的文本按照 ||| 分隔符拆成多条短消息
# 如果模型没有生成分隔符，则 fallback 到标点/长度自动切分
# =============================================================================
def split_into_chunks(text: str) -> list[str]:
    """
    将回复文本拆分成微信分段消息列表。
    优先按照模型约定的 ||| 分隔符切分；
    若无分隔符，则 fallback 到基于标点和长度的智能切分。
    """
    # 优先方案：按模型约定的 ||| 切分
    if "|||" in text:
        chunks = [c.strip() for c in text.split("|||") if c.strip()]
        logger.debug(f"[切分] ||| 切分，共 {len(chunks)} 段: {chunks}")
        return chunks[:3]

    # Fallback：按标点符号切分（句号、！、？、换行后拆开）
    sentences = re.split(r'(?<=[。！？\n])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        # 没有标点可切，按最大字符数强制截断
        chunks = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= MAX_CHUNK_LENGTH:
                chunks.append(remaining)
                break
            cut = MAX_CHUNK_LENGTH
            for i in range(MAX_CHUNK_LENGTH, max(0, MAX_CHUNK_LENGTH - 10), -1):
                if remaining[i] in (' ', '，', ','):
                    cut = i + 1
                    break
            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        logger.debug(f"[切分] 强制长度切分，共 {len(chunks)} 段: {chunks}")
        return chunks[:3]

    logger.debug(f"[切分] 标点切分，共 {len(sentences)} 段: {sentences}")
    return sentences[:3]


# =============================================================================
# 分段发送函数
# 接受接收方 UserName，逐条发送分段消息
# =============================================================================
def send_burst_messages(to_user_name: str, chunks: list[str]):
    """
    模拟真人连续发消息的"burst"效果：
    每条消息之间 sleep 一个随机浮动的时间间隔，让节奏更自然。
    """
    import itchat
    
    for i, chunk in enumerate(chunks):
        if not chunk:
            continue

        # 第一条消息立刻发送，后续消息才加延迟，模拟打字
        if i > 0:
            delay = SEND_INTERVAL_BASE + random.uniform(-SEND_INTERVAL_JITTER, SEND_INTERVAL_JITTER)
            delay = max(0.1, delay)  # 最小间隔降低到0.1秒
            logger.info(f"[发送] 等待 {delay:.1f}s 后发第 {i+1}/{len(chunks)} 条: {chunk}")
            time.sleep(delay)
        else:
            logger.info(f"[发送] 立刻发送第 1/{len(chunks)} 条: {chunk}")

        try:
            # 调用 itchat 发送私聊消息
            result = itchat.send(chunk, toUserName=to_user_name)
            if result and result.get('BaseResponse', {}).get('Ret', -1) == 0:
                logger.info(f"[发送成功] → {to_user_name}: {chunk}")
            else:
                logger.error(f"[发送失败] 返回值: {result}，消息: {chunk}")
        except Exception as e:
            logger.error(f"[发送异常] 消息: {chunk}，错误: {e}")
