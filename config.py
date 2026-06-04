import os

# ---- 微信公众号配置 ----
# 在公众号后台「开发 → 基本配置」中自己填写的 Token
# 生产环境从 Render 环境变量读取，本地调试可改为默认值
WECHAT_TOKEN = os.environ.get("WECHAT_TOKEN", "YOUR_WECHAT_TOKEN_HERE")

# ---- Gemini API 配置 ----
# 申请地址: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

# 模型版本
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# ---- 对话上下文配置 ----
MAX_HISTORY_MESSAGES = 20

