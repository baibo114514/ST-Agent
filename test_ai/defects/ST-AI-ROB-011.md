# ST-AI-ROB-011 会话隔离缺陷（用户 token 被当作会话 token）

| 项目 | 内容 |
| --- | --- |
| 对应用例 | `test_ai/scripts/test_robustness_lihuaiyu.py::test_st_ai_rob_011_user_token_is_not_a_session_token` |
| 所属层级 | 接口鉴权层（对话入口 → LangGraph 线程归属） |
| 缺陷类别 | 校验缺失（代码逻辑缺陷：依赖项未校验 token 类型，直接把 JWT 的 sub 当会话 ID） |
| 严重级别 | 中 —— 非越权（读不到他人会话），但会话隔离失效、对话静默丢失或串话，且返回 200 无任何告警 |
| 稳定性 | 稳定复现，与模型输出无关（HTTP 语义层面确定） |

## 一、缺陷现象

用登录接口返回的**用户级 token** 调用对话接口，接口返回 **200 并正常流式回答**（期望 401/403）：

| 请求头携带 | 返回码 | 本轮问答是否进入会话历史 |
| --- | --- | --- |
| 会话级 token（对照组） | 200 | 是 |
| 用户级 token（实验组） | **200** | **否**（历史条数 3 → 3 未变，`GET /sessions/{id}/history` 查不到本轮问答） |

接口既没有拒绝，对话也没有归属到任何会话——用户在客户端上表现为「回答正常，但刷新后这轮对话消失」。

**二次现象（依赖模型，非稳定可复现）**：由于该轮对话落在一条空线程上、丢失上一轮的政策上下文，省略式追问被答成错误结论：

- 对照组（会话 token）：问「那人工智能投入比例要求是多少？」→ 正确答出 **≥30%**
- 实验组（用户 token）：同样问法 → 答 **「没有'人工智能投入比例'这一统一要求」**（检索关键词因丢失 OPC 上下文而退化，捞到其它政策）

即：上下文丢失不只是「历史查不到」，还会让用户拿到错误的政策结论。

## 二、复现步骤

```cmd
:: 数据库
scripts\start-docker.cmd
:: knowledge-service / backend / frontend
scripts\start-local.cmd

cd /d <仓库根目录>
uv run --with-requirements test_ai\requirements.txt python -m pytest test_ai\scripts -k rob_011 -v --tb=short
```

修复前该用例 **FAILED**，断言信息中记录 HTTP 200、会话历史条数未变与回答片段。

纯手工复现（不跑用例）三步：

1. `POST /api/v1/auth/login` 取 `access_token`（用户级 token）；
2. `POST /api/v1/sessions` 取 `session_id` 与 `token`（会话级 token）；
3. 用**第 1 步的 token** 调 `POST /api/v1/agents/{agentId}/chat/stream`，观察返回码；再用第 2 步的会话 ID 读 `GET /api/v1/sessions/{session_id}/history`，核对本轮问答是否被记入。

## 三、根因定位

调用链五段：

**① 缺陷落点 —— 依赖项未校验 token 类型** `app/utils/auth.py:127-159`（修复前）

```python
token = credentials.credentials
session_id = verify_token(token)          # 只解 JWT 的 sub
if not session_id:
    raise HTTPException(status_code=401, detail="Could not validate credentials", ...)
return session_id                         # 直接当作会话 ID 返回
```

函数名与 docstring 都承诺「返回 Token 中的 session_id」，实现却对 token 类型不做任何判断。

**② 两种 token 的 sub 语义不同**

| Token 来源 | 签发处 | `sub` 取值 |
| --- | --- | --- |
| 登录 / 注册（用户级） | `app/api/v1/auth.py:99`、`app/api/v1/auth.py:166` | `str(user.id)`，如 `"3"` |
| 建会话（会话级） | `app/api/v1/sessions.py:59` | `session_id`（UUID） |

两者都是 JWT、都以 `Authorization: Bearer` 传递，客户端侧无法从外观区分。

**③ 用户 token 能同时通过两个依赖** `app/utils/auth.py:196-208`

`get_current_user` 刻意兼容两种 token（sub 为纯数字 → 按 user_id 查；否则 → 按 session_id 查），
因此携带用户 token 时，`verify_session_access` 与 `get_current_user` 会**同时放行**。

**④ 该值被直接当作 LangGraph 线程 ID** `app/api/v1/agents.py:38` → `app/core/langgraph/graph.py:325-341`

```python
session_id: str = Depends(verify_session_access),
...
config = {"configurable": {"thread_id": session_id, ...}}
```

**⑤ 会话历史却按 session_id 查** `app/api/v1/sessions.py:108-117`

对话被持久化到 `thread_id = "<用户ID>"` 这条**不属于任何会话**的线程，而历史接口只按传入的
session_id 读 checkpoint，两边永远对不上。若客户端持续误用同一用户 token，多轮对话都会累积在
这条匿名线程里，不同会话相互串话。

### 认定依据

1. **函数契约自相矛盾**：`verify_session_access` 的语义是「验证会话级访问权限并返回 session_id」，
   实现却等同于「解码 JWT 的 sub」，名字、文档与行为不一致。
2. **使平台既有的会话隔离设计全部失效**：建会话时同步创建 Thread 记录（`app/services/database.py:174-186`），
   `history` / `resume` 都做归属校验（`app/api/v1/sessions.py:38-43`），说明会话隔离是明确的设计目标；
   本缺陷在误用 token 时让这套设计落空。
3. **静默失败**：返回 200 且回答正确，开发者和用户都无从察觉；若返回 401，调用方立刻能发现用错了 token。
4. **合法用法唯一**：前端固定使用会话 token（`frontend/app.js:782`），说明用户 token 不是被设计的用法，
   应被拒绝而非被容忍。

## 四、修改方案

单文件、4 行代码改动，不涉及 token 格式变更，无需数据迁移。`app/utils/auth.py::verify_session_access`：

```python
    token = credentials.credentials
    session_id = verify_token(token)
    session = await database_service.get_session(session_id) if session_id else None

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate session credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session.id
```

改为**查库确认 `sub` 对应一个真实存在的会话**：

- 用户级 token 的 `sub` 是用户 ID，查不到会话 → 401；
- 会话级 token → 放行，返回的仍是会话 ID（以库中记录为准）；
- `session_id` 为 `None`（token 无效）时由同一条 `if not session` 覆盖；
- **顺带修掉**「会话被删除后其旧 token 仍可用」（JWT 有效期 30 天，原先只解码不查库）。

不采用的写法：用 `str(session_id).isdigit()` 之类判断「是不是用户 ID」——属于猜测，会话 ID 格式一变即失效。
可选的加固（本期未做）：在 JWT 中显式声明 `token_type`（`user` / `session`），把类型判断从「查库推断」变为「声明式」。

**生效方式**：开发模式下 `scripts/dev_server.py` 开启了 `reload=True`，保存后自动重载；不放心可重启：

```cmd
scripts\stop-local.cmd
scripts\start-local.cmd
```

## 五、修复验证

```cmd
uv run --with-requirements test_ai\requirements.txt python -m pytest test_ai\scripts -k rob_011 -v --tb=short
```

| 阶段 | 结果 |
| --- | --- |
| 修复前 | **FAILED**：`HTTP 200；会话历史条数保持在 3 条（误用后 3 条）`，回答片段为「没有'人工智能投入比例'这一统一要求」 |
| 修复后 | **PASSED**：用户级 token 返回 401 |

该用例内置**对照组**（会话级 token 正常对话 → 会话历史非空），因此 PASSED 同时证明：
接口在拒绝非法 token 的同时，合法会话路径未被误伤。配套回归：

```cmd
uv run --with-requirements test_ai\requirements.txt python -m pytest test_ai\scripts -k "rob_010 or rob_011" -v
:: 2 passed（rob_010 覆盖多轮上下文与正常会话历史读取）
```

建议把修复前后的完整输出另存至 `test_ai/results/`（未被 `.gitignore` 忽略）作为附件。

## 六、副作用与回归范围

**性能**：每次对话新增一次会话查库（按主键查询，可忽略；`history` 接口本来也要查会话）。

**行为变化**：会话被删除后，其旧 token 调用对话接口会立即返回 401（修复前仍可写入线程）。

**回归重点**：

- ST-AI-ROB-001 ~ ROB-010：正常会话 token 路径，全部依赖本依赖项，必须复核；
- ST-AI-RAG-001 ~ RAG-010：`ai_client.search` 走平台管理接口，不经过本依赖项，预期不受影响；
- ST-AI-SEC-001 ~ SEC-006：涉及会话与身份边界的断言；
- 全量回归：`test_ai\run_all.cmd`。

**明确不改动的部分**：`get_current_user` 继续兼容两种 token（`/auth/me` 等端点依赖该行为），仅收紧对话入口。

## 七、遗留说明

1. **未加 `token_type` 声明**：当前靠「会话存在性」判定类型，语义上够用；若将来有其它端点也要使用会话 token，需要改为显式声明类型，避免同类缺陷在新端点复现。
2. **演示方法**：本缺陷的界面症状需要临时把 `frontend/app.js:782` 的 `${state.sessionToken}` 改为
   `${state.userToken}` 才会出现（前端合法用法不会触发），演示结束后需还原该行。

## 附：缺陷复现与修复对照

```cmd
:: 缺陷版（git stash / 回退 app/utils/auth.py 的修复）
python -m pytest test_ai\scripts -k rob_011 -v --tb=short
:: 期望 FAILED：HTTP 200，本轮问答未进入会话

:: 修复版
python -m pytest test_ai\scripts -k rob_011 -v --tb=short
:: 期望 PASSED：非会话级 token 返回 401，对照组正常路径不受影响
```
