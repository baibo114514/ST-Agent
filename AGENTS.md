AI Agent 二次开发规范指南 (Developer Guide)

本文档旨在为二次开发本项目的开发者（包括人类开发者和 AI 编码助手，如 Cursor、Copilot 等）提供严格的架构与代码规范指南。

🎯 核心架构原则

本项目是一个生产就绪的 AI Agent 服务，技术栈组合如下：

核心大脑: LangGraph (支持状态图、记忆回溯、检查点机制)

Web 框架: FastAPI (异步处理，极高并发)

可观测性: Langfuse (链路追踪) + structlog (结构化日志)

持久化: PostgreSQL + pgvector (向量搜索) + SQLModel (ORM)

LLM 网关: 深度对接 DeepSeek 官方 API 及自研的 Failover 高可用路由。

📌 项目架构约定 (Architecture Conventions)

> 以下为本次会话确定的关键约定，新会话继续任务时务必遵守，避免回退。

1. **三层架构边界**
   - 前端控制台 `frontend/`（端口 5174）只访问主后端 API，不直连 knowledge-service。
   - 主后端 `app/`（端口 8000）是 control-plane：认证、Agent 配置、知识库代理、运行时编排。
   - 知识库微服务 `services/knowledge_service/`（端口 8010）只暴露 `/internal/v1/kb/*`，由主后端代理。
   - 服务间认证用 `X-KB-Service-Token`，透传操作人（`X-Actor-User-Id`/`X-Actor-Email`）。

2. **知识库检索方式（关键）**
   - 知识库知识通过「工具调用」`knowledge_base_search` 进入 Agent，**绝不预检索改写用户消息**。
   - 检索参数经 LangGraph 的 `InjectedState` 注入：`topK/scoreThreshold` 对 LLM 不可见；`kb_ids` 作为「绑定范围」注入，但 `kb_id` 是 LLM 可选参数——模型可从「绑定知识库列表」（由 `agent_config._agent_instructions` 注入）中自选一个，越权未绑定 id 时回退绑定全集。
   - `rag_tool.py` 是 **async 工具**，不要改回「同步 + 线程池新事件循环」，否则与持久连接跨事件循环冲突。

3. **检索算法策略层（关键）**
   - 检索算法拆分为独立子包 `services/knowledge_service/retrieval/`，**每算法一文件**（base/helpers + vector/weighted/hybrid/keyword/fulltext/keyword_rank），单向依赖 `base ← helpers ← 策略 ← __init__`。
   - 新增算法只需实现 `SearchStrategy` 协议（`name` + `async search`）并在 `__init__.py` 注册，`search()` 是薄分发器。
   - 策略列表：向量类 `vector`/`weighted`/`hybrid` 各分「无后缀=不重排」与「`_reranker` 后缀=重排」两个变体；`keyword`/`fulltext`/`keyword_rank` 无 rerank 变体（收益低）。策略实例 `__init__(rerank=...)` 决定 `ctx.rerank`，算法名优先覆盖请求级 rerank 布尔。
   - **所有策略的 `score` 必须统一到 0~1 量纲**：向量类天然 0~1；keyword_rank（位置加权分）与 fulltext（ts_rank）用 `helpers.normalize_score(value, scale)` sigmoid 压缩（scale 分别 100 / 1），保持单调不改变排序。否则 min_score 过滤、兜底阈值、评估判分都会失效。
   - 知识库级配置存 `KnowledgeBase.search_policy_json`：`strategy`（检索算法名）、`allowWebFallback`（是否允许联网兜底）。检索未显式传 `strategy` 时按单 kb 配置解析、兜底全局默认（`retrieval/__init__.py::_resolve_strategy_name`）。

4. **LLM 约定**
   - 主 LLM 统一 DeepSeek 官方 API，模型名 `deepseek-v4-pro`（默认）/ `deepseek-chat` / `deepseek-reasoner`。

5. **联网搜索约定**
   - 联网搜索统一用 **AnySearch**（`app/services/anysearch.py` 客户端 + `app/core/langgraph/tools/anysearch_search.py` 工具），已移除 Tavily。API Key 经 `ANYSEARCH_API_KEY` 环境变量读取，无 Key 时工具自动降级 DuckDuckGo。
   - 知识库检索联网兜底由知识库级开关 `search_policy_json.allowWebFallback` 控制（默认关闭）：开启时 `rag_tool` 无条件联网补充，并把联网结果追加在知识库结果之后。`search()` 返回 `allowWebFallback` 标志，`rag_tool` 据此决定是否联网。敏感知识库不应开启联网兜底。

6. **性能约定（已优化，勿回退）**
   - `knowledge_client` 复用持久 `httpx.AsyncClient`，**禁止每次请求新建**（否则单请求 +400ms）。
   - 文档列表关键词搜索**不搜 `content_text` 正文**（`ilike` 全文扫描慢），正文语义检索用 `search`（pgvector）。
   - 服务启动时预热：主后端预热 `chatbot.initialize()`，knowledge-service 预热 embedding。

7. **服务管理约定**
   - 本地混合开发：Docker 跑基础设施（PostgreSQL/pgvector），三层代码跑宿主机；embedding 默认走外部 API（SiliconFlow），无需本地 Ollama。
   - `scripts/manage-local.cmd` 管理本地服务；停止进程用 `taskkill /F /T`（进程树杀法，处理 uvicorn reload worker 残留）。

8. **目录 README 约定**
   - `app/` 与 `services/` 下的目录级 README 是「本地阅读用」注释，已加入 `.gitignore`，**不上传 GitHub**。
   - 根目录 `README.md` 是架构说明（上传）。

9. **角色约定**
   - 管理员/普通用户由 `PLATFORM_ADMIN_EMAILS` 白名单判定，`is_admin` 经 `/api/v1/auth/me` 返回。
   - 普通用户前端只显示会话页，管理员显示完整控制台（Agent 配置 + 知识库 + 用户调用）。

⚠️ 绝对禁忌 (Common Pitfalls to Avoid)

在修改本项目代码时，必须严格遵守以下红线：

❌ 禁止在 structlog 中使用 f-string：日志事件必须是固定的英文字符串（如 "user_login_success"），动态变量必须作为 kwargs 参数传递（如 user_id=123）。

❌ 禁止在函数或类内部 import：所有模块引用必须放置在文件顶部。

❌ 禁止遗漏 API 限流器：所有新增的 FastAPI 路由必须添加 @limiter.limit 装饰器以防 DDoS。

❌ 禁止绕过 Langfuse 追踪：所有对大模型（LLM）的调用必须挂载 Langfuse 回调，不得产生“隐形消耗”。

❌ 禁止使用 logger.error() 记录捕获的异常：在 except 块中捕获异常时，必须使用 logger.exception() 以保留完整的报错堆栈。

❌ 禁止同步阻塞代码：所有数据库访问、网络请求和文件 I/O 操作必须使用 async/await 异步语法。

❌ 禁止代码中硬编码 (Hardcode) 密钥：所有 API Keys 和敏感配置必须通过 app/core/config.py 从环境变量中读取。

🔧 编码最佳实践

依赖注入 (Dependency Injection): 充分利用 FastAPI 的 Depends 机制处理当前用户 (get_current_user) 和数据库会话。

模型容灾 (LLM Failover): 如果新增 LLM 调用逻辑，请优先使用 app.services.llm 中的 llm_service 单例，它内置了自动重试和模型崩溃切换功能。

工具开发 (Tool Building):

新增 Agent 工具必须继承 BaseTool 或使用 @tool 装饰器。

必须提供清晰、完整的 description（因为这是 LLM 决定是否调用该工具的唯一依据）。

必须定义强类型的 args_schema (Pydantic Model)。

防御性编程: 在函数开头优先校验参数、处理边缘异常，尽早 return 或 raise HTTPException。

📖 参考文档

LangGraph 官方文档

FastAPI 官方文档

SQLModel 官方文档

DeepSeek 官方 API 文档