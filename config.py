import os

# ---- 微信公众号配置 ----
WECHAT_TOKEN     = os.environ.get("WECHAT_TOKEN",     "YOUR_WECHAT_TOKEN_HERE")
WECHAT_APPID     = os.environ.get("WECHAT_APPID",     "YOUR_APPID_HERE")
WECHAT_APPSECRET = os.environ.get("WECHAT_APPSECRET", "YOUR_APPSECRET_HERE")

# ---- Gemini API 配置 ----
# 申请地址: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

# 模型版本
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# ---- 对话上下文配置 ----
MAX_HISTORY_MESSAGES = 20

