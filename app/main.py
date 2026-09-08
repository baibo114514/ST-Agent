"""
应用主入口模块 (Main Entry Point).

本模块负责：
1. 加载环境变量和初始化外部服务（Langfuse 可观测性）。
2. 创建和配置 FastAPI 应用实例，包括中间件、路由、异常处理器。
3. 定义应用生命周期（启动/关闭时的日志记录）。
4. 提供根路径、健康检查等基础端点。

架构说明：
- 使用 lifespan 异步上下文管理器管理启动/关闭逻辑。
- 中间件按顺序添加：日志上下文 → 指标采集 → CORS 跨域。
- API 路由通过 api_router 统一挂载到 /api/v1 前缀下。
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    Any,
    Dict,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    Request,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langfuse import Langfuse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.middleware import LoggingContextMiddleware
from app.core.langgraph.graph import chatbot
from app.services.database import database_service

# ============================================================================
# 环境初始化
# ============================================================================

# 加载 .env 文件中的环境变量到 os.environ
# dotenv 会按优先级查找：.env.{environment}.local > .env.{environment} > .env.local > .env
load_dotenv()

# 初始化 Langfuse 可观测性客户端
# Langfuse 用于追踪 LLM 调用链路、记录 Token 消耗、监控性能指标
# 如果环境变量未配置，Langfuse 会以无操作模式运行（不会崩溃）
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

# ============================================================================
# 应用生命周期管理
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理 FastAPI 应用的启动和关闭事件。

    启动时（yield 之前）：记录启动日志（项目名、版本、API 前缀）。
    关闭时（yield 之后）：记录关闭日志。

    注意：数据库表的创建由 database_service 在别处负责，
    这里仅做生命周期日志记录，保持入口简洁。
    """
    logger.info(
        "application_startup",
        project_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        api_prefix=settings.API_V1_STR,
    )
    await asyncio.to_thread(database_service.create_db_and_tables)
    logger.info("database_tables_ready")
    # 预热 LangGraph 图：预建连接池 + Checkpointer，避免首次请求冷启动卡顿
    await chatbot.initialize()
    logger.info("langgraph_ready")
    # yield 将控制权交给 FastAPI，应用开始接受请求
    yield
    logger.info("application_shutdown")


# ============================================================================
# FastAPI 应用实例创建
# ============================================================================

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# ============================================================================
# 监控和中间件配置
# ============================================================================

# 日志上下文中间件（必须最先添加，确保后续中间件和路由都能使用绑定的上下文字段）
# 功能：从 JWT Token 中提取 session_id 和 user_id，绑定到 structlog 上下文
app.add_middleware(LoggingContextMiddleware)

# 限流器配置
# 将 slowapi Limiter 实例绑定到 app.state，供路由装饰器 @limiter.limit() 使用
app.state.limiter = limiter
# 注册限流超限时的异常处理器（返回 429 Too Many Requests）
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ============================================================================
# 异常处理器
# ============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理请求数据校验失败（422 Unprocessable Entity）。

    当请求体、查询参数、路径参数不符合 Pydantic Schema 定义时，
    FastAPI 会抛出 RequestValidationError，由此处理器统一格式化错误响应。

    Args:
        request: 触发校验失败的 HTTP 请求对象。
        exc: 包含校验错误详情的异常对象（errors() 返回错误列表）。

    Returns:
        JSONResponse: 包含 "detail" 和 "errors" 字段的 JSON 响应，状态码为 422。
    """
    # 记录校验错误的详细信息（客户端IP、请求路径、具体错误内容）
    logger.error(
        "validation_error",
        client_host=request.client.host if request.client else "unknown",
        path=request.url.path,
        errors=str(exc.errors()),
    )

    # 将 Pydantic 的 loc（错误位置）格式化为更友好的字符串
    # 例如：("body", "email") → "email"
    formatted_errors = []
    for error in exc.errors():
        loc = " -> ".join([str(loc_part) for loc_part in error["loc"] if loc_part != "body"])
        formatted_errors.append({"field": loc, "message": error["msg"]})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": formatted_errors},
    )


# ============================================================================
# CORS 跨域配置
# ============================================================================

# CORS（跨域资源共享）中间件：允许前端（如本地开发的 React/Vue 应用）跨域访问 API
# allow_origins: 从配置读取允许的来源域名列表
# allow_credentials: 允许携带 Cookie 和 Authorization 头
# allow_methods: 允许所有 HTTP 方法（GET, POST, PUT, DELETE 等）
# allow_headers: 允许所有请求头
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 v1 版本 API 路由器，所有路由自动添加 /api/v1 前缀
# 例如：auth_router 的 /login → /api/v1/auth/login
app.include_router(api_router, prefix=settings.API_V1_STR)


# ============================================================================
# 基础端点
# ============================================================================

@app.get("/")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["root"][0])
async def root(request: Request):
    """
    根路径端点，返回 API 的基本信息。

    这是访问 API 的第一个入口，常用于：
    - 快速验证服务是否正常运行。
    - 向开发者展示可用的文档链接（Swagger/ReDoc）。
    - 负载均衡器的健康探测。

    Returns:
        dict: 包含项目名称、版本、状态、环境、文档链接等信息。
    """
    logger.info("root_endpoint_called")
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "healthy",
        "environment": settings.ENVIRONMENT.value,
        "swagger_url": "/docs",
        "redoc_url": "/redoc",
    }


@app.get("/health")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["health"][0])
async def health_check(request: Request) -> Dict[str, Any]:
    """
    健康检查端点，提供各组件的详细健康状态。

    检查项：
    - API 服务本身：始终为 "healthy"。
    - 数据库连接：通过执行 SELECT 1 验证数据库可达性。

    返回值根据数据库状态动态调整：
    - 数据库健康 → 200 OK，status = "healthy"。
    - 数据库不可达 → 503 Service Unavailable，status = "degraded"。

    该端点可用于 Kubernetes 的 liveness/readiness probe 或负载均衡器的健康检查。

    Returns:
        JSONResponse: 包含 status、version、environment、components、timestamp 的响应。
    """
    logger.info("health_check_called")

    # 检查数据库连接是否正常
    db_healthy = await database_service.health_check()

    response = {
        "status": "healthy" if db_healthy else "degraded",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT.value,
        "components": {"api": "healthy", "database": "healthy" if db_healthy else "unhealthy"},
        "timestamp": datetime.now().isoformat(),
    }

    # 根据数据库状态返回不同的 HTTP 状态码
    # 健康 → 200，降级 → 503（帮助负载均衡器自动摘除不健康节点）
    status_code = status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(content=response, status_code=status_code)
