# =============================================================================
# app.py —— 微信公众号 Webhook 服务（异步版：解决5秒超时问题）
# =============================================================================
import hashlib
import xml.etree.ElementTree as ET
import time
import logging
import threading
import requests as http_requests
import json

from flask import Flask, request, abort

from config import WECHAT_TOKEN, WECHAT_APPID, WECHAT_APPSECRET
from chat import ask_gemini

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WechatBot")

app = Flask(__name__)

# ---- 微信 Access Token 管理 ----
_access_token = None
_token_expire_at = 0
_token_lock = threading.Lock()


def get_access_token():
    global _access_token, _token_expire_at
    with _token_lock:
        if _access_token and time.time() < _token_expire_at - 60:
            return _access_token
        url = (
            f"https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={WECHAT_APPID}"
            f"&secret={WECHAT_APPSECRET}"
        )
        resp = http_requests.get(url, timeout=10).json()
        _access_token = resp.get("access_token")
        _token_expire_at = time.time() + resp.get("expires_in", 7200)
        logger.info(f"Access Token 已刷新")
        return _access_token


def send_customer_service_msg(openid: str, content: str):
    """通过客服消息接口主动推送消息（异步调用，绕过5秒限制）"""
    try:
        token = get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        payload = {
            "touser": openid,
            "msgtype": "text",
            "text": {"content": content}
        }
        resp = http_requests.post(url, json=payload, timeout=10).json()
        if resp.get("errcode", 0) != 0:
            logger.error(f"客服消息发送失败: {resp}")
        else:
            logger.info(f"客服消息发送成功 -> {openid}")
    except Exception as e:
        logger.error(f"客服消息发送异常: {e}")


def process_and_reply(openid: str, content: str):
    """后台线程：调用 Gemini 并通过客服接口推送回复"""
    reply = ask_gemini(openid, content)
    send_customer_service_msg(openid, reply)


def verify_signature(token, signature, timestamp, nonce):
    tmp = sorted([token, timestamp, nonce])
    tmp_str = "".join(tmp).encode("utf-8")
    return hashlib.sha1(tmp_str).hexdigest() == signature


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
        xml_data  = ET.fromstring(request.data)
        msg_type  = xml_data.findtext("MsgType", "")
        from_user = xml_data.findtext("FromUserName", "")
        content   = xml_data.findtext("Content", "").strip()

        if msg_type != "text" or not content:
            return "success"

        logger.info(f"收到消息 from {from_user}: {content}")

        # 立刻返回 "success"（微信收到后不会再等待），后台线程处理
        t = threading.Thread(target=process_and_reply, args=(from_user, content), daemon=True)
        t.start()

        return "success"

    except Exception as e:
        logger.error(f"消息处理异常: {e}")
        return "success"


@app.route("/")
def index():
    return "Petezz Bot is running! 🤖"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
