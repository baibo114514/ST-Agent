"""
应用限流配置模块。

本模块使用 slowapi 库实现 API 限流，防止恶意请求或过度使用：
- 基于客户端 IP 地址进行限流识别。
- 默认限流规则从 settings.RATE_LIMIT_DEFAULT 读取（环境可配置）。
- 各端点可通过 @limiter.limit() 装饰器单独配置限流规则。

限流策略：
    当客户端在时间窗口内超过限制次数时，
    slowapi 返回 HTTP 429 Too Many Requests 响应。

使用方式：
    from app.core.limiter import limiter

    @router.get("/my-endpoint")
    @limiter.limit("10 per minute")  # 每分钟最多 10 次
    async def my_endpoint(request: Request):
        ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# 创建 Limiter 实例
# - key_func=get_remote_address: 使用客户端 IP 地址作为限流键
#   每个不同的 IP 地址独立计数
# - default_limits: 没有显式设置限流的端点使用此默认规则
#   例如 ["200 per day", "50 per hour"] 表示每天 200 次 + 每小时 50 次
limiter = Limiter(key_func=get_remote_address, default_limits=settings.RATE_LIMIT_DEFAULT)
