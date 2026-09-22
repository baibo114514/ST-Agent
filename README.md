# ST-Agent 智能体对话平台

该项目是一个基于 FastAPI、LangGraph 和 PostgreSQL/pgvector 的 AI Agent对话平台，提供用户认证、会话管理、Agent 配置与发布、知识库文档入库和检索等功能。

项目采用三层架构：前端只访问主后端，主后端负责认证、权限、Agent 管理和运行时编排，知识库微服务负责文档解析、切分、向量化和检索。

```text
浏览器
  │
  ▼
frontend/                         http://127.0.0.1:5174
  │
  ▼
app/ 主后端                       http://127.0.0.1:8000
  │  X-KB-Service-Token
  ▼
services/knowledge_service/       http://127.0.0.1:8010
  │
  ▼
PostgreSQL + pgvector             localhost:5432
```

## 项目结构

```text
ST-Agent/
├─ app/                              主后端
│  ├─ api/                           FastAPI 接口：认证、会话、Agent 和平台管理
│  ├─ core/langgraph/                LangGraph 状态图与 Agent 工具
│  ├─ models/                        SQLModel 数据模型
│  ├─ schemas/                       请求与响应数据结构
│  ├─ services/                      数据库、LLM、Agent 和知识库代理服务
│  └─ utils/                         JWT、数据清理等通用功能
├─ frontend/                         管理员控制台和普通用户调用页面
├─ services/
│  ├─ knowledge_service/             独立知识库微服务
│  └─ evaluation_service/            检索评估代码与示例文档数据
├─ scripts/                          本地服务管理、批量入库和辅助脚本
├─ test/                             模块一：非AI基础功能测试
│  ├─ scripts/                       三个成员的 pytest 自动化测试
│  ├─ requirements.txt               测试附加依赖
│  ├─ run_all.cmd                    一键运行模块一测试
│  └─ 测试用例_*.xlsx                小组成员测试用例清单
├─ test_ai/                          模块二：AI 测试
│  ├─ scripts/                       对已发布 Agent 的在线测试（conftest + 三份测试文件）
│  ├─ defects/                       典型缺陷的说明与修复方法
│  ├─ results/                       测试运行结果（latest.json，未入库）
│  ├─ requirements.txt               测试附加依赖
│  ├─ run_all.cmd                    一键运行模块二测试
│  ├─ .env.example                   测试账号与统一测试配置模板
│  └─ 测试用例_*.xlsx                小组成员测试用例清单
├─ docs/                             架构、部署等补充文档
├─ docker-compose.yml                PostgreSQL/pgvector 等基础设施
├─ pyproject.toml                    Python 项目与依赖配置
└─ .env.example                      环境变量模板
```

主要功能包括：

- 用户注册、登录、JWT 身份认证、管理员权限和会话管理；
- Agent 创建、修改、发布、下线、功能开关和知识库绑定；
- PDF、Markdown、TXT、CSV、JSON、HTML 等文档上传与目录入库；
- 文档解析、元数据提取、文本切分、Embedding 和 pgvector 检索；
- `vector`、`weighted`、`hybrid`、`keyword`、`fulltext`、`keyword_rank` 等检索策略；
- LangGraph 多轮对话。

## 环境要求

Docker 运行 PostgreSQL/pgvector，三个应用服务运行在宿主机。

- Python 3.13 或更高版本；
- [uv]；
- Docker Desktop，且 Docker Engine 已启动；
- 可用的 DeepSeek/OpenAI 兼容接口；
- 可用的 Embedding 接口，例如 SiliconFlow，或者本地 Ollama。

## 环境配置

###  安装项目依赖

在项目根目录打开 PowerShell：

```powershell
uv sync
```

该命令会根据 `pyproject.toml` 和 `uv.lock` 创建或更新 `.venv` 虚拟环境。

###  创建开发环境配置

```powershell
Copy-Item .env.example .env.development
```

然后编辑 `.env.development`。不要把真实密码、Token 或 API Key 提交到 Git。

至少要检查以下配置：

| 配置类别 | 关键变量 | 用途 |
| --- | --- | --- |
| 管理员 | `PLATFORM_ADMIN_EMAILS` | 白名单内邮箱登录后拥有平台管理权限 |
| 数据库 | `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` | 主后端连接 PostgreSQL |
| JWT | `JWT_SECRET_KEY`、`JWT_ALGORITHM` | 生成和校验登录令牌 |
| 知识库通信 | `KNOWLEDGE_SERVICE_BASE_URL`、`KNOWLEDGE_SERVICE_TOKEN` | 主后端访问知识库微服务；两端 Token 必须一致 |
| Embedding | `KNOWLEDGE_EMBEDDING_BASE_URL`、`KNOWLEDGE_EMBEDDING_API_KEY`、`KNOWLEDGE_EMBEDDING_MODEL` | 文档向量化和语义检索 |
| LLM | `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`DEFAULT_LLM_MODEL` | Agent 对话模型，项目使用 OpenAI 兼容接口 |
| 可选能力 | `LANGFUSE_*`、`ANYSEARCH_*`、`EMAIL_*`、`KNOWLEDGE_RERANKER_*` | 链路追踪、联网搜索、邮件和重排模型 |

本地默认服务地址建议保持为：

```env
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
KNOWLEDGE_SERVICE_BASE_URL=http://127.0.0.1:8010
ALLOWED_ORIGINS=http://localhost:5174,http://127.0.0.1:5174,http://localhost:8000
```

## 本地运行

###  启动数据库

确保 Docker Desktop 已经运行，然后在项目根目录执行：

```powershell
scripts\start-docker.cmd
```

该脚本启动 PostgreSQL/pgvector，数据库数据保存在 Docker 的 `postgres-data` 数据卷中。

###  启动三个本地服务

```powershell
scripts\start-local.cmd
```

脚本会依次启动：

| 服务 | 地址 |
| --- | --- |
| 前端控制台 | http://127.0.0.1:5174 |
| 主后端及 API 文档 | http://127.0.0.1:8000/docs |
| 知识库服务健康检查 | http://127.0.0.1:8010/health |

查看运行状态：

```powershell
scripts\manage-docker.cmd status
scripts\manage-local.cmd status
```

只重启一个服务：

```powershell
scripts\manage-local.cmd restart -Service backend
scripts\manage-local.cmd restart -Service knowledge-service
scripts\manage-local.cmd restart -Service frontend
```

停止项目：

```powershell
scripts\stop-local.cmd
scripts\stop-docker.cmd
```

本地服务的 PID 和日志保存在 `.runtime/local-services/`。

## 基本使用流程

1. 使用 `PLATFORM_ADMIN_EMAILS` 中配置的邮箱注册或登录。
2. 在“知识库”页面创建知识库并上传文档。
3. 在“入库任务”中确认任务状态为 `completed`，并在“搜索预览”中验证检索结果。
4. 在“Agent 配置”页面创建 Agent，设置模型、角色说明和功能开关。
5. 勾选“启用检索”，绑定处于 `active` 状态的知识库，配置 `Top K` 和最低分数。
6. 保存并发布 Agent。
7. 普通用户在“用户调用”页面选择已发布的 Agent，创建会话并进行对话。

项目中提供两组可用于知识库练习和检索评估的 Markdown 文档：

```text
services/evaluation_service/data/policies/          政策文档
services/evaluation_service/data/customer_service/ 客户服务文档
```

可以在知识库页面选择“文档上传 → 目录”，直接选择对应目录进行入库。全量导入前建议先上传一个文件，确认解析、Embedding 和检索链路正常。

## 测试工作说明

课程测试分两个模块：模块一测试非AI基础功能，模块二测试 AI 流水线的实际行为。两个模块的测试脚本、依赖和运行入口各自独立，互不影响。

### 模块一：非AI基础功能测试

课程模块一任务测试聚焦项目中的非AI基础功能，不评价模型回答的质量，也不会在测试中真实调用 LLM。外部数据库、网络和服务依赖主要通过 Mock、Stub 和 `monkeypatch` 隔离，使测试能够快速、重复运行。

小组三名成员按以下模块分工：

| 成员 | 测试模块 | 自动化测试文件 | 当前测试函数数 |
| --- | --- | --- | ---: |
| 李怀宇 | 用户认证、权限与会话管理 | `test/scripts/test_auth_lihuaiyu.py` | 17 |
| 罗盛哲 | 知识库文档管理与预处理 | `test/scripts/test_knowledge_luoshengzhe.py` | 21 |
| 马云飞 | Agent 配置与生命周期管理 | `test/scripts/test_agent_mayunfei.py` | 15 |
| 合计 | 3 个非AI基础功能模块 | 3 个测试文件 | 53 |

当前测试内容主要包括：

- 认证模块：注册与登录校验、密码规则、重复邮箱、JWT、管理员权限、会话创建和邮箱规范化；
- 知识库模块：服务间认证、知识库创建与归档、名称和命名空间校验、分页、文件编码、Markdown/YAML 元数据提取、文件类型和文本切分；
- Agent 模块：Agent 编码和状态校验、知识库绑定、版本更新、发布与下线、公开列表过滤及接口限流配置。

三名成员的详细测试设计分别保存在：

```text
test/测试用例_李怀宇.xlsx
test/测试用例_罗盛哲.xlsx
test/测试用例_马云飞.xlsx
```

### 模块二：AI 测试

课程模块二任务测试聚焦 AI 流水线的实际行为：直接调用平台上已发布的 Agent，评价回答的事实一致性、检索依据、拒答边界与会话安全。与模块一不同，这部分不做 Mock，需要真实启动数据库、后端、知识库微服务和可用的 LLM 接口，因此运行更慢，结果也依赖真实模型输出。

测试对象统一为已发布的 Agent `policy-assistant`：绑定湖北省与武汉市政策知识库，Top K=5、最低分数 0.2，联网搜索、代码解释、长期记忆、邮件助手及知识库联网兜底全部关闭。配置不一致时 `conftest.py` 会在初始化阶段直接报错，避免用错误的配置得出无效结论。

小组三名成员按以下模块分工：

| 成员 | 测试模块 | 自动化测试文件 | 当前测试函数数 |
| --- | --- | --- | ---: |
| 李怀宇 | Agent 鲁棒性与无依据拒答、会话隔离 | `test_ai/scripts/test_robustness_lihuaiyu.py` | 11 |
| 罗盛哲 | 知识库检索与回答依据 | `test_ai/scripts/test_rag_luoshengzhe.py` | 10 |
| 马云飞 | 提示词注入与信息边界、公平性 | `test_ai/scripts/test_security_mayunfei.py` | 10 |
| 合计 | 3 个 AI 测试模块 | 3 个测试文件 | 31 |

当前测试内容主要包括：

- 鲁棒性模块：口语化改写、错别字、无关噪声、格式扰动和极简问法下的事实一致性；虚构政策、域外问题与错误前提的拒答；多轮上下文保留；会话隔离与 Token 类型校验；
- 检索模块：目标政策是否命中 Top-K、地区与时效排序、检索策略与最低分数的接口契约、结果去重与知识库范围隔离、回答是否留有可核验的知识库依据；
- 安全与公平模块：直接注入、伪造开发者权限、引文内嵌指令和编码指令的防护，跨用户与密钥信息边界，客户端 `system` 角色的越权提升，以及性别、民族、婚姻状况、宗教等无关属性下结论的一致性。

三名成员的详细测试设计分别保存在 `test_ai/测试用例_*.xlsx`；实际复现并定位的典型缺陷记录在 `test_ai/defects/`：

```text
test_ai/defects/ST-AI-RAG-004.md   # 检索时效性缺陷：默认检索算法对发布时间无偏好
test_ai/defects/ST-AI-ROB-011.md   # 会话隔离缺陷：用户级 Token 被当作会话级 Token
```

## 运行测试

### 一键运行全部测试

模块一（非AI基础功能），在项目根目录执行：

```powershell
test\run_all.cmd
```

脚本会自动读取 `test/requirements.txt`，并执行 `test/scripts` 下的全部 pytest 测试。也可以在文件资源管理器中双击 `test\run_all.cmd`。

模块二（AI 测试）：

```powershell
test_ai\run_all.cmd
```

脚本会自动读取 `test_ai/.env.local`（可复制 `test_ai/.env.example` 修改），并执行 `test_ai/scripts` 下的全部 pytest 测试。运行前需保证数据库、后端和知识库微服务已启动，且使用平台管理员测试账号；测试会真实调用 LLM，单条用例通常需要 3～10 秒。

### 单独运行某个成员的测试

模块一：

```powershell
# 用户认证、权限与会话管理
uv run --with-requirements test/requirements.txt python -m pytest test/scripts/test_auth_lihuaiyu.py -v --tb=short -p no:cacheprovider

# 知识库文档管理与预处理
uv run --with-requirements test/requirements.txt python -m pytest test/scripts/test_knowledge_luoshengzhe.py -v --tb=short -p no:cacheprovider

# Agent 配置与生命周期管理
uv run --with-requirements test/requirements.txt python -m pytest test/scripts/test_agent_mayunfei.py -v --tb=short -p no:cacheprovider
```

模块二：

```powershell
# Agent 鲁棒性、无依据拒答与会话隔离
uv run --with-requirements test_ai/requirements.txt python -m pytest test_ai/scripts/test_robustness_lihuaiyu.py -v --tb=short -p no:cacheprovider

# 知识库检索与回答依据
uv run --with-requirements test_ai/requirements.txt python -m pytest test_ai/scripts/test_rag_luoshengzhe.py -v --tb=short -p no:cacheprovider

# 提示词注入、信息边界与公平性
uv run --with-requirements test_ai/requirements.txt python -m pytest test_ai/scripts/test_security_mayunfei.py -v --tb=short -p no:cacheprovider
```

### 运行指定测试用例

```powershell
# 模块一
uv run --with-requirements test/requirements.txt python -m pytest test/scripts/test_auth_lihuaiyu.py::test_st_auth_017_email_case_is_normalized -v

# 模块二
uv run --with-requirements test_ai/requirements.txt python -m pytest test_ai/scripts -k rob_011 -v --tb=short
```

测试完成后，pytest 会在终端显示 `passed`、`failed` 和错误堆栈。若一键脚本返回非零退出码，应根据失败用例名称和错误信息定位问题。