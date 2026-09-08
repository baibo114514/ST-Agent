"""
应用日志配置模块 - 使用 structlog 提供结构化日志。

本模块实现了完整的日志系统，支持：

1. 请求级上下文绑定：
   - 每个 HTTP 请求可以有独立的日志上下文（session_id、user_id）。
   - 使用 Python ContextVar 实现协程安全的上下文隔离。

2. 多输出目标：
   - 控制台输出：开发环境使用彩色格式化输出，便于阅读。
   - JSONL 文件输出：按天滚动的 JSON 行文件，便于日志收集和分析。

3. 环境自适应：
   - 开发/测试环境：控制台彩色输出 + 详细文件信息（模块、函数、行号）。
   - 预发布/生产环境：JSON 格式输出 + 精简文件信息。

4. 结构化日志：
   - 所有日志都是结构化的键值对，便于 ELK/Loki 等日志系统解析。
   - 自动附加时间戳、环境、模块、函数、行号等元信息。

日志文件命名格式：
    logs/{environment}-{YYYY-MM-DD}.jsonl
    例如：logs/development-2026-07-11.jsonl
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import structlog

from app.core.config import (
    Environment,
    settings,
)

# ============================================================================
# 日志目录初始化
# ============================================================================

# 确保日志目录存在（程序启动时执行一次）
# parents=True: 自动创建所有父目录
# exist_ok=True: 目录已存在时不报错
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# 请求级日志上下文管理
# ============================================================================

# ContextVar 是 Python 的上下文变量，用于在异步任务中安全地存储请求级别数据
# 每个请求有独立的上下文副本，不会相互干扰
# 默认值为空字典
_request_context: ContextVar[Dict[str, Any]] = ContextVar("request_context", default={})


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                continue


def _silence_noisy_loggers() -> None:
    for logger_name in (
        "httpx",
        "httpcore",
        "openai",
        "openai._base_client",
        "langchain_openai",
        "multipart",
        "python_multipart",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "urllib3",
        "watchfiles",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


def _resolve_log_level() -> int:
    configured = getattr(logging, settings.LOG_LEVEL.upper(), None)
    if isinstance(configured, int):
        return configured
    return logging.DEBUG if settings.DEBUG else logging.INFO


def bind_context(**kwargs: Any) -> None:
    """
    将键值对绑定到当前请求的日志上下文中。

    绑定后，该请求的所有后续 structlog 日志都会自动包含这些字段。
    常用于在中间件中绑定 session_id 和 user_id。

    Args:
        **kwargs: 要绑定的键值对（如 session_id="abc123"）。

    示例：
        bind_context(session_id="abc123", user_id="42")
        # 之后的所有日志都会自动包含 session_id 和 user_id 字段
    """
    current = _request_context.get()
    _request_context.set({**current, **kwargs})


def clear_context() -> None:
    """
    清空当前请求的日志上下文。

    必须在一个请求结束时调用，防止请求间的数据泄露。
    例如：请求 A 的 session_id 不应该出现在请求 B 的日志中。
    """
    _request_context.set({})


def get_context() -> Dict[str, Any]:
    """
    获取当前请求的日志上下文字典。

    Returns:
        Dict[str, Any]: 当前请求绑定的上下文字段。
    """
    return _request_context.get()


def add_context_to_event_dict(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    structlog 处理器：将请求上下文合并到每条日志事件中。

    这是一个 structlog processor 函数，在每条日志记录时被调用，
    自动将当前请求绑定的上下文（如 session_id）添加到日志字典中。

    Args:
        logger: structlog logger 实例。
        method_name: 日志方法名（如 "info", "error"）。
        event_dict: 当前的日志事件字典。

    Returns:
        Dict[str, Any]: 增强后的日志事件字典（包含请求上下文字段）。
    """
    context = get_context()
    if context:
        event_dict.update(context)
    return event_dict


# ============================================================================
# JSONL 文件处理器
# ============================================================================

def get_log_file_path() -> Path:
    """
    根据当前日期和环境生成日志文件路径。

    每天生成一个新的日志文件，文件名包含环境前缀和日期：
    格式：{环境}-{YYYY-MM-DD}.jsonl

    例如：
        development-2026-07-11.jsonl
        production-2026-07-11.jsonl

    Returns:
        Path: 当日日志文件的完整路径。
    """
    env_prefix = settings.ENVIRONMENT.value
    return settings.LOG_DIR / f"{env_prefix}-{datetime.now().strftime('%Y-%m-%d')}.jsonl"


class JsonlFileHandler(logging.Handler):
    """
    自定义 logging 处理器 - 将日志以 JSON Lines 格式写入每日文件。

    JSON Lines (JSONL) 格式：
        每行一个完整的 JSON 对象，便于按行解析和流式处理。
        适合被 Filebeat、Fluentd、Logstash 等日志采集器收集。
    """

    def __init__(self, file_path: Path):
        """
        初始化 JSONL 文件处理器。

        Args:
            file_path: 日志文件路径。
        """
        super().__init__()
        self.file_path = file_path

    def emit(self, record: logging.LogRecord) -> None:
        """
        将单条日志记录写入 JSONL 文件。

        每条记录包含：
        - timestamp: ISO 格式时间戳。
        - level: 日志级别（DEBUG/INFO/WARNING/ERROR）。
        - message: 日志消息文本。
        - module: 产生日志的模块名。
        - function: 产生日志的函数名。
        - filename: 源文件路径。
        - line: 源代码行号。
        - environment: 当前运行环境。
        - extra: 任意额外字段（通过 record.extra 传递）。

        Args:
            record: Python logging 的日志记录对象。
        """
        try:
            # 构建标准日志条目
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "filename": record.pathname,
                "line": record.lineno,
                "environment": settings.ENVIRONMENT.value,
            }
            # 合并额外字段（如 structlog 绑定的上下文字段）
            if hasattr(record, "extra"):
                log_entry.update(record.extra)
            # 追加写入文件（JSON 对象 + 换行符）
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """关闭处理器（由 logging 框架调用）。"""
        super().close()


# ============================================================================
# structlog 处理器链
# ============================================================================

def get_structlog_processors(include_file_info: bool = True) -> List[Any]:
    """
    获取 structlog 处理器链的配置。

    处理器按顺序执行，每个处理器对日志事件字典进行增强或格式化：

    1. filter_by_level: 根据日志级别过滤。
    2. add_logger_name: 添加 logger 名称。
    3. add_log_level: 添加日志级别字符串。
    4. PositionalArgumentsFormatter: 格式化位置参数。
    5. TimeStamper: 添加 ISO 格式时间戳。
    6. StackInfoRenderer: 渲染堆栈信息。
    7. format_exc_info: 格式化异常信息。
    8. UnicodeDecoder: 确保字符串为 Unicode。
    9. add_context_to_event_dict: 合并请求上下文。
    10. CallsiteParameterAdder: 添加调用位置信息（可选）。
    11. 环境信息添加器: 添加当前环境名称。

    Args:
        include_file_info: 是否包含详细的文件信息（文件名、函数名、行号等）。
                           开发/测试环境建议开启，生产环境可关闭以减少开销。

    Returns:
        List[Any]: structlog 处理器列表。
    """
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # 自动将请求上下文（session_id, user_id 等）添加到每条日志
        add_context_to_event_dict,
    ]

    # 仅在需要时添加详细的调用位置信息
    if include_file_info:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.PATHNAME,
                }
            )
        )

    # 添加当前环境信息到每条日志
    processors.append(
        lambda _, __, event_dict: {**event_dict, "environment": settings.ENVIRONMENT.value}
    )

    return processors


# ============================================================================
# 日志系统初始化
# ============================================================================

def setup_logging() -> None:
    """
    配置 structlog 和标准 logging。

    初始化策略：
    1. 根据 DEBUG 设置确定日志级别。
    2. 创建两个输出目标：JSONL 文件 + 控制台。
    3. 根据 LOG_FORMAT 配置 structlog 的最终渲染器：
       - "console"（开发环境）→ ConsoleRenderer（彩色可读输出）。
       - "json"（生产环境）→ JSONRenderer（结构化 JSON 输出）。
    4. 根据环境决定是否包含详细的文件信息。
    """
    _configure_stdio()

    # 根据 DEBUG 配置确定日志级别
    log_level = _resolve_log_level()

    # 创建 JSONL 文件处理器（写入每日日志文件）
    file_handler = JsonlFileHandler(get_log_file_path())
    file_handler.setLevel(log_level)

    # 创建控制台处理器（输出到 stdout）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # 获取共享的处理器链
    # 开发/测试环境包含详细文件信息，生产环境精简
    shared_processors = get_structlog_processors(
        include_file_info=settings.ENVIRONMENT in [Environment.DEVELOPMENT, Environment.TEST]
    )

    # 配置标准 logging（作为 structlog 的底层输出）
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=[file_handler, console_handler],
        force=True,
    )
    _silence_noisy_loggers()

    # 根据日志格式配置 structlog 的最终渲染器
    if settings.LOG_FORMAT == "console":
        # 开发环境：彩色可读的控制台输出
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # 生产环境：结构化 JSON 输出（便于日志系统解析）
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


# ============================================================================
# 模块初始化
# ============================================================================

# 在模块导入时立即执行日志系统初始化
setup_logging()

# 创建全局 logger 实例
# 整个应用通过 `from app.core.logging import logger` 使用同一个 logger
logger = structlog.get_logger()

# 初始化后记录一条确认日志
log_level_name = logging.getLevelName(_resolve_log_level())
logger.info(
    "logging_initialized",
    environment=settings.ENVIRONMENT.value,
    log_level=log_level_name,
    log_format=settings.LOG_FORMAT,
    debug=settings.DEBUG,
)
