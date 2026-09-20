# ST-AI-RAG-004 检索时效性缺陷

| 项目 | 内容 |
|---|---|
| 对应用例 | `test_ai/scripts/test_rag_luoshengzhe.py::test_st_ai_rag_004_newest_policy_ranks_first` |
| 所属层级 | 检索层（AI 流水线：召回 → 排序） |
| 缺陷类别 | 配置默认值缺陷（默认取值不当，非代码逻辑错误） |
| 严重级别 | 中 —— 不导致崩溃，但使 AI 回答引用已失效政策，属实质性内容错误 |
| 稳定性 | 稳定复现，与提问措辞无关（更换同义问法结果一致） |

## 一、缺陷现象

查询「武汉市支持人工智能OPC创新发展的若干措施里包含哪些支持政策？」时，Top-5 结果中旧政策排在目标新政策之前：

| 角色 | 文档 | 发布时间 |
|---|---|---|
| 目标（应排在前） | 市人民政府关于印发武汉市支持人工智能 OPC 创新发展若干措施的通知 | 2026-02-14 |
| 干扰（实际排在前） | 同主题武汉市人工智能产业政策措施 | 2025-09-12 |

用户问的是现行政策，检索却优先给出已被新政策覆盖的旧文。

## 二、复现步骤

使用出厂默认配置（不设置任何 `KNOWLEDGE_*` 覆盖），启动被测系统后执行：

```cmd
:: db + ollama
scripts\start-docker.cmd
:: frontend / backend / knowledge-service
scripts\start-local.cmd

cd /d <仓库根目录>
test_ai\run_all.cmd
```

`test_st_ai_rag_004_newest_policy_ranks_first` 呈现为 `xfail`（已知弱点）。

## 三、根因定位

调用链三段：

**① 缺陷落点 —— 默认取值** `services/knowledge_service/config.py:88-89`

```python
# 检索算法策略：默认 vector；请求可用 strategy 字段覆盖，便于多种算法 A/B 评估。
self.default_search_strategy = os.getenv("KNOWLEDGE_DEFAULT_SEARCH_STRATEGY", "vector").strip().lower()
```

**② 何时落到该默认值** `services/knowledge_service/retrieval/__init__.py:69`

请求未显式指定 `strategy`、且单库未配置 `searchPolicyJson.strategy` 时：

```python
return settings.default_search_strategy
```

**③ 由此产生的排序行为** `services/knowledge_service/retrieval/vector.py:43-52`

```python
.order_by(distance)                                  # 纯余弦相似度，对发布时间无感
score = max(0.0, 1.0 - float(raw_distance or 0.0))
```

**三段代码均无逻辑错误。** `order_by(distance)` 对名为 `vector`（纯向量检索）的策略是正确实现，
优先级解析写法规范。缺陷落点是**默认取值 `"vector"` 本身选错了**。

### 认定依据

仓库自带的评测结论已否定当前默认值：

- `retrieval/vector.py:9-10`：通过 80/100，MRR 0.863，hit@1 0.781 ——
  *「是加权/混合等策略的**基线**；语义召回质量稳定，**排序弱于 weighted**」*
- `retrieval/weighted.py:12-14`：通过 86/100，MRR 0.931，hit@1 0.906 ——
  *「**六策略中精度最优**：在向量分之上叠加区域/时效软偏好，MRR 比 vector 高 +7.9%、hit@1 高 +16%」*

即默认选中了被自己标注为「基线、排序弱于 weighted」的策略，把被自己标注为「六策略中精度最优」的策略留作非默认。
且 `config.py:88` 注释写明该字段用途是「便于多种算法 A/B 评估」，默认值却未随评估结论更新。
产品为政策问答，被取代的旧政策不是「略不相关」而是错误答案，`vector` 排序对其完全无感 —— 故认定为缺陷。

## 四、修改方案

纯配置改动，不涉及代码变更。项目根 `.env.local`：

```ini
KNOWLEDGE_DEFAULT_SEARCH_STRATEGY=weighted
KNOWLEDGE_SEARCH_FRESHNESS_WEIGHT=0.3
```

**换算法（主要）**：`weighted` 策略（`retrieval/weighted.py`）在向量分之上叠加
区域 / 时效 / 产业 / 支持方式 / 政策文种五类软偏好，其中时效项会把较新政策排在较旧政策之前，
正是本缺陷所缺能力。实质是让默认配置与仓库自带评测结论保持一致，而非引入新逻辑。

**提权重（配套）**：时效项计算式为
`max(0.0, 1.0 - abs(参考年 - 文档年) / 5.0) * KNOWLEDGE_SEARCH_FRESHNESS_WEIGHT`（`helpers.py::_weighted_bonus`）。
出厂 0.03 时上限仅 `0.2 × 0.03 = 0.006`，低于本例近似标题文档之间的余弦分差，**等效于不参与排序决策**；
取值应与分数尺度（0~1）同量级，而非与其余加分项（0.04~0.05）同量级，故取 0.3（上限 0.06）。

**生效方式**：配置不热加载（`config.py` 在 import 时构造 `Settings()`），须重启 knowledge-service：

```cmd
scripts\stop-local.cmd
scripts\start-local.cmd
```

本目录 `fix_ST-AI-RAG-004.py`（一键入口 `fix_ST-AI-RAG-004.cmd`）封装写入 / 回退 / 重启，
用于保证写入内容与本文档一致，并可在演示时一键切换修复前后状态。

## 五、修复验证

`xfail` 标记会遮蔽真实结论（修复后仅显示 `xpassed`），故加 `--runxfail`
令 pytest 忽略该标记、按普通用例执行：

```cmd
:: 修复前 —— 删除 .env.local 两行配置并重启
python -m pytest test_ai\scripts\test_rag_luoshengzhe.py -k rag_004 --runxfail -v
:: 期望 FAILED：旧政策仍排在目标新政策之前，现象复现

:: 修复后 —— 恢复两行配置并重启
python -m pytest test_ai\scripts\test_rag_luoshengzhe.py -k rag_004 --runxfail -v
:: 期望 PASSED：目标新政策排序正确
```

建议将两次完整输出另存至 `test_ai/results/`（未被 `.gitignore` 忽略）作为附件。

## 六、副作用与回归范围

时效权重提高后，需确认时效项不会压过语义相关性，导致「很相关但较旧」的文档被无关的新文档挤掉。

另：`helpers.py:278` 的 `_preference_from_filter` 在请求未携带 `metadataFilter` 时
**把区域默认为「武汉」**（docstring 已明示），武汉文档 +0.050、湖北文档 +0.033；
切换默认算法后湖北主题的检索排序可能被扰动。

回归重点：ST-AI-RAG-003（地区优先级）、ST-AI-RAG-005（省级对照，湖北语料），
以及李怀宇（Agent 鲁棒性层）、马云飞（安全/公平层）中涉及湖北语料的断言。
全量回归：`test_ai\run_all.cmd`。

## 七、遗留说明

1. 当前为两行配置同时生效，尚未单独验证「只换算法、保持权重 0.03 是否已足够」。
   若注释掉权重一行、重启后重跑仍 `PASSED`，本方案可精简为一行配置。
2. 权重 0.3 满足上述量级要求，但未在仓库自带评测集（180 篇政策语料）上做敏感性标定；
   亦未运行 `services/evaluation_service` 对比修复前后的 MRR / hit@1 / nDCG，
   因此「修复不引入回归」目前仅由 `test_ai\run_all.cmd` 全量用例间接支持。
3. 修复落在被 `.gitignore` 忽略的 `.env.local`，不入库是有意为之（环境配置因机器而异，
   入库会污染他人环境）。可复现载体为本文档第四节的配置片段与第五节的前后对照输出。
