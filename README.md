# 🚀 FastGraph Agent Engine

基于 **FastAPI + LangGraph** 的生产级 AI Agent 平台，采用「前端控制台 / 主后端 control-plane / 知识库微服务」三层架构。

> **当前分支 `slim-deploy`** —— 面向阿里云轻量服务器的精简部署版。相比 `main`，本分支聚焦两大能力：**可插拔知识库检索算法体系** 与 **联网搜索 + 知识库兜底**，并裁剪掉监控三件套（Prometheus/Grafana/cAdvisor）与在线评估模块，产物为「容器化数据库 + 外部 embedding/LLM + nginx 反代」的最小部署形态。

---

## ✨ 本分支核心能力

### 1. 可插拔知识库检索算法（六策略 + rerank 变体）

检索逻辑从 service 层抽离成独立子包（`services/knowledge_service/retrieval/`），每种算法一个文件、可独立注册与 A/B 评估：

| 策略 | 类型 | 说明 | 依赖 embedding |
|---|---|---|---|
| `vector` | 向量检索 | HNSW 向量召回（pgvector `cosine_distance`）→ metadata 粗筛 → Python 精筛 → `min_score` 过滤 | ✅ |
| `weighted` | 元数据加权排序 | 向量召回之上叠加区域/时效/产业**软偏好**加分，精度最优 | ✅ |
| `hybrid` | 混合检索 | 向量 + 关键词 n-gram 重叠加分 | ✅ |
| `keyword` | 纯关键词 | `pg_trgm` word_similarity，无嵌入基线 | ❌ |
| `fulltext` | 全文检索 | jieba 分词 + PG `tsvector/ts_rank` | ❌ |
| `keyword_rank` | 关键词评分 + 规则重排 | 移植自 agent-paas，policy 规则重排 | ❌ |

- 向量类策略（`vector`/`weighted`/`hybrid`）均提供 `_reranker` 精排变体。
- **知识库级配置**：每个知识库通过 `searchPolicyJson.strategy` 独立指定算法，请求可用 `strategy` 字段临时覆盖。
- **HNSW 索引 + metadata 过滤下推**：向量检索走 pgvector HNSW 索引，metadata 条件尽量下推到 SQL。

> 100 条业务场景评估集（rerank 开）：`weighted` 通过 86/100、MRR 0.931、hit@1 0.906（六策略最优）；`vector` 通过 80/100、MRR 0.863（基线）。详见 `services/evaluation_service/retrieval_eval_design.md`。

### 2. 联网搜索 + 知识库兜底（AnySearch）

- 联网搜索统一走 **AnySearch**（Bearer auth，`cn`/`zh-CN` 中文区）；未配置 `ANYSEARCH_API_KEY` 时自动降级 **DuckDuckGo**。
- 知识库检索**未命中或低分**时可按需联网兜底，开关是**知识库级**的 `searchPolicyJson.allowWebFallback`（默认关闭），把联网结果追加在知识库结果之后，弥补「最新 / 时效」类检索不足。

### 3. LLM 自选知识库

`knowledge_base_search` 工具的 `kb_id` 为 LLM 可选参数——从该 Agent 已绑定的知识库列表中自选一个精确检索；未填或越权时回退到绑定的完整 `kb_ids`。检索范围（`kb_ids`/`topK`/`scoreThreshold`）经 LangGraph `InjectedState` 从图状态注入，对 LLM 不可见，避免改写用户消息。

### 4. Langfuse 全链路追踪

LLM 调用经 `CallbackHandler` 自动产生 trace；`langfuse_session_id` / `langfuse_user_id` / `langfuse_tags` 挂在 trace 级（会话、用户、Agent 维度可聚合）。支持 Langfuse Cloud 或本地自托管（`docker-compose.yml` 中 `local-langfuse` profile）。

### 5. 阿里云精简部署

- **Docker 只跑基础设施**：PostgreSQL/pgvector（必选）、Ollama（可选本地 embedding）、Langfuse 自托管（可选）。
- **embedding / LLM 走外部 API**（默认 SiliconFlow `BAAI/bge-m3` 与 DeepSeek），无本地模型与磁盘开销。
- **nginx 反代前端 + systemd 托管三进程**，前端 `apiBase` 抽离到 `config.js`，生产默认同源。
- 已移除监控三件套与在线评估模块，最小化服务器资源占用。

---

## 🏗️ 架构设计

### 三层架构

```
前端控制台 (frontend/)                    端口 5174
  ├─ /api/v1/auth/*              认证：注册/登录/当前用户（区分管理员与普通用户）
  ├─ /api/v1/admin/platform/*    平台管理：Agent 配置 + 知识库/文档/入库任务代理
  └─ /api/v1/agents/*            普通用户：调用已发布 Agent（流式）
        │
        ▼
主后端 control-plane (app/)               端口 8000
  ├─ api/                REST 路由层（薄壳，只做参数校验与转发）
  ├─ services/           业务服务层：LLM 路由 / Agent 配置 / knowledge 代理 / 数据库
  ├─ core/langgraph/     Agent 执行引擎：状态图（agent ⇄ tools）+ 动态工具
  ├─ models/ + schemas/  数据库表（SQLModel）+ API 契约（Pydantic）
  └─ utils/              通用工具：JWT / 消息处理 / 数据净化
        │  X-KB-Service-Token（服务间认证）
        ▼
知识库微服务 (services/knowledge_service/)  端口 8010
  ├─ 文档上传 → 解析 → 切片 → embedding → 入库任务（状态机）
  └─ 可插拔检索算法（vector/weighted/hybrid/keyword/fulltext/keyword_rank，向量类支持 rerank 变体）
```

### 核心数据流

1. **平台管理员**在控制台创建知识库、上传文档（解析 + 切片 + embedding + 入库任务记录），配置 Agent（模型、角色、工具开关、知识库绑定、检索算法、联网兜底）并发布。
2. **普通用户**选择已发布 Agent 发起对话，主后端读取 Agent 配置。
3. Agent 启用知识库时，LLM 通过 `knowledge_base_search` **工具按需检索**——检索参数经 `InjectedState` 注入，`kb_id` 可由 LLM 自选。
4. LangGraph 状态图（agent ⇄ tools 循环）驱动多轮对话，PostgreSQL Checkpoint 持久化状态，支持 HITL 中断（如邮件审批）。

---

## 🧰 动态工具箱

按 Feature Flag 动态挂载（`all_tools_map`）：

| Feature Flag | 工具 | 说明 |
|---|---|---|
| `web_search` | AnySearch 搜索 | 无 Key 降级 DuckDuckGo |
| `knowledge_base` | KnowledgeBaseSearch | 按 Agent 绑定 kbIds 检索 |
| `memory_tools` | SaveMemory + SearchMemory | 长期记忆 |
| `email_assistant` | PrepareEmail + SendEmail | HITL 审批中断 |
| `code_interpreter` | Python REPL | 可选依赖 `langchain-experimental` |

---

## 🛠️ 快速开始

```bash
git clone https://github.com/Xzcgod/FastGraph-Agent-Engine.git
cd FastGraph-Agent-Engine
git checkout slim-deploy

# 复制环境变量模板
cp .env.example .env.development
```

按需填入 DeepSeek API Key、SiliconFlow embedding Key、Langfuse Key、邮箱授权码等，然后本地混合启动（Docker 跑基础设施，三层代码跑宿主机）：

```powershell
scripts\start-docker.cmd   # PostgreSQL/pgvector（可选：ollama / langfuse 自托管）
scripts\start-local.cmd    # knowledge-service、主后端、前端
```

访问地址：前端控制台 http://127.0.0.1:5174 · API 文档 http://localhost:8000/docs

> 只重启某个本地服务：`scripts\manage-local.cmd restart -Service backend`（`backend`/`knowledge-service`/`frontend`）。

---

## 🌐 线上部署（阿里云轻量服务器）

生产环境已部署于阿里云轻量服务器，实际访问地址：

- **控制台**：http://47.122.117.96/
- **部署说明**：`docs/部署-阿里云轻量服务器.md`

生产运行在 `slim-deploy` 分支，形态为：Docker 仅跑 PostgreSQL/pgvector 等基础设施，embedding/LLM 走外部 API，前端由 nginx 反代，三进程由 systemd 托管。已移除监控三件套与在线评估模块。

---

## 📚 项目文档

- 📌 三层架构与本地混合开发：`docs/三层架构本地开发.md`
- 📌 检索算法与评估设计：`services/evaluation_service/retrieval_eval_design.md`
- 📖 各目录结构说明：`app/README.md`、`services/README.md` 及各自子目录

---

## 🙏 致谢

本项目基于 [tring-yu/FastGraph-Agent-Engine](https://github.com/tring-yu/FastGraph-Agent-Engine) 二次开发，感谢原项目的贡献。

## 📜 许可证

本项目采用 MIT 许可证开源 - 详情请查看 LICENSE 文件。
