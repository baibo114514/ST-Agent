"""
全局配置模块 - 应用所有配置项的集中管理中心。

本模块负责：
1. 环境识别：根据 APP_ENV 自动判断当前运行环境（开发/测试/预发布/生产）。
2. 环境变量加载：按优先级链加载 .env 文件（环境特定 → 本地覆盖 → 默认）。
3. 配置类 (Settings)：将所有配置项集中在一个类中，提供类型安全和默认值。
4. 环境覆盖：根据当前环境自动调整部分配置（如开发环境启用 DEBUG、放宽限流）。

配置优先级（从高到低）：
    1. 系统环境变量 (os.environ) — 最高优先级
    2. .env.{environment}.local — 本地环境特定覆盖（不提交到 Git）
    3. .env.{environment} — 环境特定配置
    4. .env.local — 本地通用覆盖（不提交到 Git）
    5. .env — 默认配置
    6. Settings 类中的硬编码默认值 — 最低优先级

使用方式：
    from app.core.config import settings
    print(settings.PROJECT_NAME)
"""

import os
from enum import Enum
from pathlib import Path
from typing import List

from dotenv import load_dotenv


class Environment(str, Enum):
    """
    应用运行环境枚举。

    定义了四种标准环境，用于在不同部署场景下自动调整配置行为：
    - DEVELOPMENT: 本地开发，启用 DEBUG、详细日志、宽松限流。
    - STAGING: 预发布/灰度环境，模拟生产配置但保留更多日志。
    - PRODUCTION: 生产环境，最严格的限流和安全配置。
    - TEST: 自动化测试环境，类似开发环境但专门用于单元测试。
    """
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


def get_environment() -> Environment:
    """
    从 APP_ENV 环境变量解析当前运行环境。

    支持别名：
    - "production" / "prod" → Environment.PRODUCTION
    - "staging" / "stage" → Environment.STAGING
    - "test" → Environment.TEST
    - 其他任何值（包括未设置）→ Environment.DEVELOPMENT（默认安全值）

    Returns:
        Environment: 当前环境枚举值。
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT


def load_env_file():
    """
    按优先级链加载 .env 环境变量文件。

    加载顺序（先加载的会被后加载的覆盖）：
        1. .env.{environment}.local  （如 .env.development.local，最高优先级）
        2. .env.{environment}         （如 .env.development）
        3. .env.local                  （本地通用覆盖）
        4. .env                        （默认配置，最低优先级）

    文件不存在时会静默跳过，不会报错。
    这意味着你可以只创建需要的文件，其他使用代码中的默认值。

    Returns:
        str | None: 最终成功加载的文件路径，如果没有任何文件存在则返回 None。
    """
    env = get_environment()
    print(f"Loading environment: {env}")
    # 计算项目根目录（本文件的父目录的父目录的父目录）
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env_files = [
        os.path.join(base_dir, f".env.{env.value}.local"),
        os.path.join(base_dir, f".env.{env.value}"),
        os.path.join(base_dir, ".env.local"),
        os.path.join(base_dir, ".env"),
    ]
    for env_file in env_files:
        if os.path.isfile(env_file):
            load_dotenv(dotenv_path=env_file)
            print(f"Loaded environment from {env_file}")
            return env_file
    return None


# 模块加载时立即执行环境变量加载
# 确保在 Settings 实例化之前，环境变量已经可用
ENV_FILE = load_env_file()


def parse_list_from_env(env_key, default=None):
    """
    从环境变量解析逗号分隔的列表值。

    环境变量中的值通常以逗号分隔，但也支持：
    - 未设置或空字符串 → 返回默认值（默认为空列表）。
    - 单个值（无逗号）→ 返回包含该值的单元素列表。
    - 双引号或单引号包裹 → 自动去除首尾引号。

    使用示例：
        # .env 文件：ALLOWED_ORIGINS="http://localhost:3000,https://app.example.com"
        parse_list_from_env("ALLOWED_ORIGINS", ["*"])
        # → ["http://localhost:3000", "https://app.example.com"]

    Args:
        env_key: 环境变量名。
        default: 环境变量未设置时的默认值（默认为空列表）。

    Returns:
        list: 解析后的字符串列表，每个元素已去除首尾空白。
    """
    value = os.getenv(env_key)
    if not value:
        return default or []
    # 去除环境变量值首尾的引号（某些 .env 文件会使用引号包裹值）
    value = value.strip("\"'")
    if "," not in value:
        return [value]
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    """
    全局配置类 - 所有应用配置的单一数据源。

    设计原则：
    1. 每个配置项都有合理的默认值，确保不配置 .env 也能启动。
    2. 敏感信息（密钥、密码）默认值为空字符串，强制用户显式配置。
    3. 配置项通过 os.getenv() 读取，可通过 .env 文件或系统环境变量覆盖。
    4. apply_environment_settings() 方法根据当前环境自动调整部分配置。

    配置分类：
    - 基础信息：项目名、版本、描述、API 前缀、DEBUG 开关。
    - CORS 跨域：允许的来源域名列表。
    - Langfuse 监控：可观测性服务的公钥、私钥、服务地址。
    - LLM 配置：API Key、Base URL、默认模型、温度、最大 Token 数、重试次数。
    - AnySearch 搜索：联网搜索的 API Key。
    - 短期记忆：滚动摘要触发的消息数量阈值。
    - 邮件 SMTP：发件服务器、端口、认证信息（支持 QQ 邮箱）。
    - 独立知识库微服务：服务地址、服务令牌、调用超时。
    - JWT 认证：密钥、算法、令牌过期天数。
    - 日志：输出目录、级别、格式（JSON/Console）。
    - PostgreSQL：主机、端口、库名、用户、密码、连接池配置。
    - 限流：默认限流规则、各端点的限流规则。
    - 评估模块：评估专用 LLM、API 地址、请求间隔。
    """

    def __init__(self):
        # 第一步：确定当前运行环境
        self.ENVIRONMENT = get_environment()

        # ====================================================================
        # 基础信息
        # ====================================================================
        self.PROJECT_NAME = os.getenv("PROJECT_NAME", "FastAPI LangGraph Template")
        self.VERSION = os.getenv("VERSION", "1.0.0")
        self.DESCRIPTION = os.getenv("DESCRIPTION", "A production-ready FastAPI template with LangGraph")
        self.API_V1_STR = os.getenv("API_V1_STR", "/api/v1")
        # DEBUG 开关：支持多种 true 值表示（"true", "1", "t", "yes"，不区分大小写）
        self.DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")

        # ====================================================================
        # CORS 跨域配置
        # ====================================================================
        # 允许的跨域来源域名，开发环境通常设为 ["*"]（允许所有来源）
        self.ALLOWED_ORIGINS = parse_list_from_env("ALLOWED_ORIGINS", ["*"])

        # ====================================================================
        # 平台控制面配置
        # ====================================================================
        # 用于本地阶段的平台管理员白名单。生产环境可替换为 SSO/租户权限系统。
        self.PLATFORM_ADMIN_EMAILS = parse_list_from_env("PLATFORM_ADMIN_EMAILS", [])

        # ====================================================================
        # Langfuse 可观测性监控
        # ====================================================================
        self.LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
        self.LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        # ====================================================================
        # 独立知识库微服务
        # ====================================================================
        self.KNOWLEDGE_SERVICE_BASE_URL = os.getenv(
            "KNOWLEDGE_SERVICE_BASE_URL",
            "http://127.0.0.1:8010",
        )
        self.KNOWLEDGE_SERVICE_TOKEN = os.getenv("KNOWLEDGE_SERVICE_TOKEN", "")
        self.KNOWLEDGE_SERVICE_CONNECT_TIMEOUT_SECONDS = float(
            os.getenv("KNOWLEDGE_SERVICE_CONNECT_TIMEOUT_SECONDS", "5")
        )
        self.KNOWLEDGE_SERVICE_REQUEST_TIMEOUT_SECONDS = float(
            os.getenv("KNOWLEDGE_SERVICE_REQUEST_TIMEOUT_SECONDS", "120")
        )

        # ====================================================================
        # LLM（OpenAI 兼容协议提供商）
        # ====================================================================
        # 默认使用 DeepSeek 官方 OpenAI 兼容接口
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
        self.DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "deepseek-v4-pro")
        self.DEFAULT_LLM_TEMPERATURE = float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.2"))
        self.MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))
        # 输入上下文预算（用于消息裁剪），与 MAX_TOKENS（生成上限）区分。
        # 裁剪时若用 MAX_TOKENS(4000) 会把工具检索结果等长消息整条丢弃，导致 LLM 拿不到结果。
        self.MAX_INPUT_TOKENS = int(os.getenv("MAX_INPUT_TOKENS", "30000"))
        self.MAX_LLM_CALL_RETRIES = int(os.getenv("MAX_LLM_CALL_RETRIES", "3"))

        # ====================================================================
        # AnySearch 联网搜索（Bearer auth）
        # ====================================================================
        self.ANYSEARCH_API_URL = os.getenv("ANYSEARCH_API_URL", "https://api.anysearch.com/v1/search")
        self.ANYSEARCH_API_KEY = os.getenv("ANYSEARCH_API_KEY", "")
        self.ANYSEARCH_ZONE = os.getenv("ANYSEARCH_ZONE", "cn")
        self.ANYSEARCH_LANGUAGE = os.getenv("ANYSEARCH_LANGUAGE", "zh-CN")

        # ====================================================================
        # 知识库检索兜底阈值
        # ====================================================================
        # 知识库检索 top1 分数低于此值时，自动用联网搜索兜底（针对向量类 0~1 量纲）。
        self.KNOWLEDGE_FALLBACK_SCORE = float(os.getenv("KNOWLEDGE_FALLBACK_SCORE", "0.5"))

        # ====================================================================
        # 短期记忆滚动摘要阈值
        # ====================================================================
        # 当对话消息数量超过此阈值时，旧消息会被压缩为摘要文本，减少 Token 消耗
        self.SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "10"))

        # ====================================================================
        # 邮件 SMTP 配置（支持 QQ 邮箱）
        # ====================================================================
        # QQ邮箱设置方法：设置 → 账户 → 开启 POP3/SMTP 服务 → 获取授权码
        # EMAIL_SMTP_PASSWORD 填写的是授权码，不是 QQ 登录密码！
        self.EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.qq.com")
        self.EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
        self.EMAIL_SMTP_USER = os.getenv("EMAIL_SMTP_USER", "")          # 发件人 QQ 邮箱地址
        self.EMAIL_SMTP_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")  # QQ 邮箱授权码（非登录密码）
        self.EMAIL_SMTP_USE_SSL = os.getenv("EMAIL_SMTP_USE_SSL", "true").lower() in ("true", "1", "yes")
        self.EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "智能助手")

        # ====================================================================
        # JWT 认证配置
        # ====================================================================
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", "30"))

        # ====================================================================
        # 日志配置
        # ====================================================================
        self.LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        # 日志格式：json（生产环境，结构化日志）或 console（开发环境，彩色可读输出）
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")

        # ====================================================================
        # PostgreSQL 数据库配置
        # ====================================================================
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "mydb")
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        # 连接池配置：最大连接数和溢出连接数
        self.POSTGRES_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "20"))
        self.POSTGRES_MAX_OVERFLOW = int(os.getenv("POSTGRES_MAX_OVERFLOW", "10"))
        # LangGraph 检查点（Checkpoint）相关的表名
        self.CHECKPOINT_TABLES = ["checkpoint_blobs", "checkpoint_writes", "checkpoints"]

        # ====================================================================
        # 限流配置
        # ====================================================================
        # 默认限流规则应用于未单独配置限流的端点
        self.RATE_LIMIT_DEFAULT = parse_list_from_env("RATE_LIMIT_DEFAULT", ["200 per day", "50 per hour"])
        # 各端点的限流规则（可根据环境变量覆盖）
        default_endpoints = {
            "chat": ["30 per minute"],
            "chat_stream": ["20 per minute"],
            "messages": ["50 per minute"],
            "agent_catalog": ["60 per minute"],
            "agent_chat_stream": ["20 per minute"],
            "platform_admin": ["120 per minute"],
            "knowledge_proxy": ["60 per minute"],
            "knowledge_ingest": ["10000 per hour"],
            "register": ["10 per hour"],
            "login": ["20 per minute"],
            "root": ["10 per minute"],
            "health": ["20 per minute"],
            "rag_upload": ["20 per hour"],       # 知识库文档上传限流
            "email_resume": ["30 per minute"],   # 邮件审批恢复接口限流
        }
        self.RATE_LIMIT_ENDPOINTS = default_endpoints.copy()
        # 检查环境变量中的自定义限流值（如 RATE_LIMIT_CHAT），覆盖默认值
        for endpoint in default_endpoints:
            env_key = f"RATE_LIMIT_{endpoint.upper()}"
            value = parse_list_from_env(env_key)
            if value:
                self.RATE_LIMIT_ENDPOINTS[endpoint] = value

        # 最后一步：根据环境覆盖部分配置（如开发环境启用 DEBUG）
        self.apply_environment_settings()

    def apply_environment_settings(self):
        """
        根据当前运行环境覆盖部分配置默认值。

        不同环境的配置差异：
        ┌──────────────┬─────────┬──────────┬──────────┬────────┐
        │ 配置项        │ 开发     │ 预发布    │ 生产     │ 测试   │
        ├──────────────┼─────────┼──────────┼──────────┼────────┤
        │ DEBUG        │ True    │ False    │ False    │ True   │
        │ LOG_LEVEL    │ DEBUG   │ INFO     │ WARNING  │ DEBUG  │
        │ LOG_FORMAT   │ console │ json     │ json     │ console│
        │ 默认限流     │ 宽松    │ 中等      │ 严格     │ 极宽松 │
        └──────────────┴─────────┴──────────┴──────────┴────────┘

        注意：这些值仅在环境变量未显式设置时生效。
        如果 os.environ 中已有对应的值，则不会被覆盖。
        """
        env_settings = {
            Environment.DEVELOPMENT: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "200 per hour"],
            },
            Environment.STAGING: {
                "DEBUG": False,
                "LOG_LEVEL": "INFO",
                "RATE_LIMIT_DEFAULT": ["500 per day", "100 per hour"],
            },
            Environment.PRODUCTION: {
                "DEBUG": False,
                "LOG_LEVEL": "WARNING",
                "RATE_LIMIT_DEFAULT": ["200 per day", "50 per hour"],
            },
            Environment.TEST: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "1000 per hour"],
            },
        }
        current_env_settings = env_settings.get(self.ENVIRONMENT, {})
        for key, value in current_env_settings.items():
            # 仅当环境变量中不存在该键时才覆盖
            # 这样用户可以显式设置环境变量来覆盖环境默认值
            if key.upper() not in os.environ:
                setattr(self, key, value)


# ============================================================================
# 全局单例实例
# ============================================================================
# 在模块导入时创建唯一的 Settings 实例
# 整个应用通过 `from app.core.config import settings` 共享同一个配置对象
settings = Settings()
