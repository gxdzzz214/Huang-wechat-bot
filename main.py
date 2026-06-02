# =============================================================================
# main.py —— 黄邦亮微信机器人主程序入口（itchat-uos 网页版协议）
# 无需安装电脑版微信客户端，直接扫码后台运行
# =============================================================================

import time
import logging

import itchat
from itchat.content import TEXT

from config import (
    ALLOWED_FRIEND_NAMES,
    RESPONSE_MODE,
    DEBUG_MODE,
)
from message_handler import ask_gemini, split_into_chunks, send_burst_messages

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PetezzBot.Main")

# 记录自己登录的 UserName，避免自己回复自己
my_username = None

import threading

# 记录机器人启动的时间戳，丢弃启动之前的历史积压消息
START_TIME = time.time()

# --- 防抖缓冲池设置 ---
message_buffer = {}
timer_dict = {}

def calc_dynamic_delay(text: str) -> float:
    """根据消息内容智能判断需要等待的时间"""
    text = text.strip()
    if not text:
        return 0.1
        
    # 如果是打游戏暗号，立刻回复
    if text in ["1", "111", "1不1", "1不一", "cs", "csgo"]:
        return 0.1
        
    # 如果明确有完整的结束语气词，立刻回复
    if text.endswith(("吗", "呢", "吧", "啊", "了", "？", "?", "！", "!", "。", "~")):
        return 0.1
        
    # 如果只有纯表情（比如 [强]），通常代表一句话结束，不需要等
    if text.startswith("[") and text.endswith("]") and len(text) <= 5:
        return 0.1
        
    # 如果是逗号、省略号，或者明显的连词结尾，说明话没说完，多等一会
    if text.endswith((",", "，", "...", "…", "然后", "就是", "不过", "但是", "的话")):
        return 1.5
        
    # 默认普通的短句，稍微等一下，防连发
    return 0.6

def process_and_reply(display_name, sender_username):
    """定时器到期后，统一处理合并的消息"""
    if display_name not in message_buffer or not message_buffer[display_name]:
        return
        
    # 用空格把连续发送的多条消息合并
    content = " ".join(message_buffer.pop(display_name))
    
    # --- 调用 Gemini 生成回复 ---
    logger.info(f"[合并处理] 来自 {display_name} 的连续消息: {content}")
    logger.info(f"[Gemini] 正在为 {display_name} 生成回复...")
    
    raw_reply = ask_gemini(display_name, content)

    if raw_reply is None:
        logger.error("[Gemini] 回复生成失败，跳过发送")
        return

    # --- 切分成分段消息 ---
    chunks = split_into_chunks(raw_reply)
    logger.info(f"[切分] 共 {len(chunks)} 段: {chunks}")

    # --- 分段发送到微信 ---
    send_burst_messages(sender_username, chunks)


from itchat.content import TEXT, PICTURE, RECORDING, VIDEO, ATTACHMENT, MAP, SHARING, CARD

# =============================================================================
# 消息分发处理流程
# =============================================================================
@itchat.msg_register([TEXT, PICTURE, RECORDING, VIDEO, ATTACHMENT, MAP, SHARING, CARD], isFriendChat=True, isGroupChat=False, isMpChat=False)
def text_reply(msg):
    """处理接收到的微信文本私聊消息"""
    global my_username
    
    # 丢弃在脚本启动之前收到的历史消息（防止重启时疯狂回复之前的聊天）
    if msg.CreateTime < START_TIME:
        logger.debug(f"忽略启动前的历史消息: {msg.Text[:10]}...")
        return
        
    sender_username = msg.User.UserName
    sender_nickname = msg.User.NickName
    sender_remarkname = msg.User.RemarkName
    
    # 转换非文本消息内容，让大模型能理解
    msg_type = msg.Type
    if msg_type == 'Text':
        content = msg.Text.strip()
    elif msg_type == 'Picture':
        content = "[用户发来了一张图片]"
    elif msg_type == 'Recording':
        content = "[用户发来了一段语音]"
    elif msg_type == 'Video':
        content = "[用户发来了一段视频]"
    elif msg_type == 'Attachment':
        content = f"[用户发送了一个文件: {msg.FileName}]"
    elif msg_type == 'Map':
        content = "[用户发送了一个位置信息]"
    elif msg_type == 'Card':
        content = "[用户发送了一张名片]"
    elif msg_type == 'Sharing':
        content = f"[用户分享了一个链接: {msg.Text}]"
    else: # 例如 Emote (动画表情)
        content = "[用户发来了一个表情包]"

    # 忽略自己发出的消息
    if sender_username == my_username:
        return

    if not content:
        return

    # 显示名称：优先显示备注名，如果没有备注则显示微信昵称
    display_name = sender_remarkname if sender_remarkname else sender_nickname
    
    logger.info(f"[收到消息] 来自: {display_name} | 内容: {content}")

    # --- 白名单过滤 ---
    if RESPONSE_MODE == "whitelist_friends":
        if display_name not in ALLOWED_FRIEND_NAMES:
            logger.debug(f"忽略非白名单好友消息: {display_name}")
            return

    # --- 调试指令：发送 /reset 清空上下文 ---
    if content == "/reset":
        from message_handler import clear_history
        clear_history(display_name)
        itchat.send("ok", toUserName=sender_username)
        logger.info(f"[调试] 已重置 {display_name} 的对话历史")
        # 清除缓冲区
        message_buffer.pop(display_name, None)
        if display_name in timer_dict:
            timer_dict[display_name].cancel()
        return

    # --- 防抖合并逻辑 ---
    if display_name not in message_buffer:
        message_buffer[display_name] = []
    message_buffer[display_name].append(content)
    
    # 如果已经有定时器，取消它（重新计时）
    if display_name in timer_dict:
        timer_dict[display_name].cancel()
        
    # 根据这一句话的内容，智能计算需要等待多长时间再回复
    delay = calc_dynamic_delay(content)
    
    # 启动新定时器
    timer = threading.Timer(delay, process_and_reply, args=(display_name, sender_username))
    timer_dict[display_name] = timer
    timer.start()

# =============================================================================
# 登录回调函数
# =============================================================================
def on_login():
    global my_username
    logger.info("=" * 60)
    logger.info("   🎮 黄邦亮 (Petezz) 微信机器人 已成功登录！ [itchat 版]")
    logger.info("=" * 60)
    
    # 获取登录账号的自身信息
    me = itchat.search_friends()
    if me:
        my_username = me.UserName
        logger.info(f"   当前登录账号: {me.NickName}")
        
    logger.info("-" * 60)
    logger.info(f"   机器人已就绪，当前监听模式：{RESPONSE_MODE}")
    logger.info("   白名单列表：" + ", ".join(ALLOWED_FRIEND_NAMES))
    logger.info("   (按 Ctrl+C 停止运行)")
    logger.info("-" * 60)

# 屏蔽底层库的无用调试日志
import logging
logging.getLogger("urllib3").setLevel(logging.WARNING)

def on_logout():
    logger.info("[关闭] 机器人已登出或掉线。")

# =============================================================================
# 机器人主循环
# =============================================================================
def main():
    logger.info("=" * 60)
    logger.info("   🚀 正在启动网页版微信协议，将自动弹出二维码图片...")
    logger.info("=" * 60)
    
    try:
        # hotReload=True: 保持登录状态（生成 itchat.pkl），下次启动无需扫码
        # enableCmdQR=2: 在控制台黑框里画二维码
        itchat.auto_login(
            hotReload=True, 
            enableCmdQR=2,
            loginCallback=on_login, 
            exitCallback=on_logout
        )
        
        # 阻塞启动，进入事件监听循环
        itchat.run()
        
    except KeyboardInterrupt:
        logger.info("\n[关闭] 收到 Ctrl+C，正在安全退出...")
        itchat.logout()
    except Exception as e:
        logger.error(f"[启动异常] {e}", exc_info=DEBUG_MODE)


if __name__ == "__main__":
    main()
