"""
API v1 路由聚合中心。

本模块是 API v1 版本的"总路由器"，负责：
1. 创建 v1 版本的 APIRouter 实例。
2. 将各功能模块的路由器（auth、sessions、agents、admin）挂载到统一的路径前缀下。
3. 定义 v1 级别的健康检查端点。

路由挂载规则：
    - auth_router     → /api/v1/auth/*     （注册、登录、当前用户）
    - sessions_router → /api/v1/sessions/* （会话 CRUD、聊天记录、审批恢复）
    - agents_router   → /api/v1/agents/*   （Agent 目录、对话调用）
    - admin_router    → /api/v1/admin/platform/*（平台管理、知识库代理）

架构说明：
    main.py                        ← 应用主入口，挂载 api_router 到 /api/v1
      └── api_router (本模块)       ← v1 路由器
            ├── auth_router        ← /auth 前缀（注册、登录、当前用户）
            ├── sessions_router    ← /sessions 前缀（会话、历史、恢复）
            ├── agents_router      ← /agents 前缀（Agent 目录、对话）
            ├── admin_router       ← /admin/platform 前缀（管理、知识库）
            └── /health            ← v1 健康检查端点
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.sessions import router as sessions_router
from app.core.logging import logger

# 创建 v1 版本的路由器实例
# 这个路由器会被 main.py 挂载到 /api/v1 路径下
api_router = APIRouter()

# ============================================================================
# 挂载子路由器
# ============================================================================

# 认证路由：所有以 /auth 开头的请求都交给 auth_router 处理
# 例如：POST /api/v1/auth/login → auth_router 的 login 函数处理
# tags=["auth"] 让 Swagger 文档中所有认证接口归类在 "auth" 标签下
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])

# 会话路由：所有以 /sessions 开头的请求都交给 sessions_router 处理
# 例如：POST /api/v1/sessions → sessions_router 的 create_session 函数处理
# tags=["sessions"] 让 Swagger 文档中所有会话接口归类在 "sessions" 标签下
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])

# 平台管理员控制面：Agent 配置和 knowledge-service 代理
api_router.include_router(admin_router, prefix="/admin/platform", tags=["admin-platform"])

# 普通用户 Agent 目录和调用入口
api_router.include_router(agents_router, prefix="/agents", tags=["agents"])


# ============================================================================
# v1 级别健康检查
# ============================================================================

@api_router.get("/health")
async def health_check():
    """
    API v1 版本健康检查端点。

    这是 API 版本级别的健康检查（更轻量），访问路径为 /api/v1/health。
    与根路径的 /health 端点不同，此端点仅验证 v1 路由器本身是否正常工作，
    不进行数据库连接检查。

    Returns:
        dict: 包含状态和版本信息的简单响应。
    """
    logger.info("health_check_called")
    return {"status": "healthy", "version": "1.0.0"}
