# =============================================================================
# app.py —— 微信公众号 Webhook 服务主入口
# =============================================================================
import hashlib
import xml.etree.ElementTree as ET
import time
import logging
import threading
from flask import Flask, request, abort

from config import WECHAT_TOKEN, GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY_MESSAGES
from persona import PETEZZ_SYSTEM_PROMPT
from chat import ask_gemini

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WechatBot")

app = Flask(__name__)


def verify_signature(token, signature, timestamp, nonce):
    """验证微信服务器签名"""
    tmp = sorted([token, timestamp, nonce])
    tmp_str = "".join(tmp).encode("utf-8")
    return hashlib.sha1(tmp_str).hexdigest() == signature


def build_text_response(to_user, from_user, content):
    """构造微信文本回复 XML"""
    ts = str(int(time.time()))
    return (
        f"<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{ts}</CreateTime>"
        f"<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"</xml>"
    )


@app.route("/wechat", methods=["GET", "POST"])
def wechat():
    signature = request.args.get("signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce     = request.args.get("nonce", "")
    echostr   = request.args.get("echostr", "")

    # 微信服务器验证
    if not verify_signature(WECHAT_TOKEN, signature, timestamp, nonce):
        logger.warning("签名验证失败！")
        abort(403)

    # GET 请求：微信在验证服务器时调用，原样返回 echostr
    if request.method == "GET":
        return echostr

    # POST 请求：用户发来了消息
    try:
        xml_data = ET.fromstring(request.data)
        msg_type    = xml_data.findtext("MsgType", "")
        from_user   = xml_data.findtext("FromUserName", "")
        to_user     = xml_data.findtext("ToUserName", "")  # 公众号 ID
        content     = xml_data.findtext("Content", "").strip()

        # 非文本消息（图片、语音等）给个固定回复
        if msg_type != "text":
            reply_content = "666"
        elif not content:
            return "success"
        else:
            logger.info(f"收到消息 from {from_user}: {content}")
            # 调用 Gemini 生成回复
            reply_content = ask_gemini(from_user, content)
            # 把 ||| 分隔符替换成换行（公众号不支持多条分发）
            reply_content = reply_content.replace(" ||| ", "\n").replace("|||", "\n")
            logger.info(f"回复: {reply_content}")

        return build_text_response(from_user, to_user, reply_content)

    except Exception as e:
        logger.error(f"消息处理异常: {e}")
        return "success"


@app.route("/")
def index():
    return "Petezz Bot is running! 🤖"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
