# =============================================================================
# config.py —— 公众号版配置文件
# 把下面的占位符替换成你自己的真实值
# =============================================================================

# ---- 微信公众号配置 ----
# 在公众号后台「开发 → 基本配置」中自己填写的 Token（随便取，比如 mybot123）
WECHAT_TOKEN = "YOUR_WECHAT_TOKEN_HERE"

# ---- Gemini API 配置 ----
# 申请地址: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"

# 模型版本: gemini-2.5-flash（速度快）或 gemini-2.5-pro（效果好）
GEMINI_MODEL = "gemini-2.5-flash"

# ---- 对话上下文配置 ----
# 每个用户保留的最大历史消息条数
MAX_HISTORY_MESSAGES = 20
