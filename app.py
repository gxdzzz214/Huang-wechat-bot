# =============================================================================
# app.py —— 微信公众号 Webhook 服务（同步被动回复版）
# =============================================================================
import hashlib
import xml.etree.ElementTree as ET
import time
import logging

from flask import Flask, request, abort

from config import WECHAT_TOKEN
from chat import ask_gemini

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WechatBot")

app = Flask(__name__)


def verify_signature(token, signature, timestamp, nonce):
    tmp = sorted([token, timestamp, nonce])
    tmp_str = "".join(tmp).encode("utf-8")
    return hashlib.sha1(tmp_str).hexdigest() == signature


def make_reply(to_user, from_user, content):
    return (
        f"<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
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

    if not verify_signature(WECHAT_TOKEN, signature, timestamp, nonce):
        logger.warning("签名验证失败！")
        abort(403)

    if request.method == "GET":
        return echostr

    try:
        xml_data   = ET.fromstring(request.data)
        msg_type   = xml_data.findtext("MsgType", "")
        from_user  = xml_data.findtext("FromUserName", "")
        to_user    = xml_data.findtext("ToUserName", "")
        content    = xml_data.findtext("Content", "").strip()

        if msg_type != "text" or not content:
            return "success"

        logger.info(f"收到消息 from {from_user}: {content}")
        reply = ask_gemini(from_user, content)
        logger.info(f"回复: {reply}")

        return make_reply(from_user, to_user, reply), 200, {"Content-Type": "application/xml"}

    except Exception as e:
        logger.error(f"消息处理异常: {e}")
        return "success"


@app.route("/")
def index():
    return "Petezz Bot is running! 🤖"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
