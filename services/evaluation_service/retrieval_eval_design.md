# 检索自动化测试设计

## 目标

先只测 `knowledge-service` 的检索能力，不把大模型回答混进来。
核心问题是：给定一个用户问题、一个 Agent 的知识库范围、`topK` 和 `scoreThreshold`，检索结果是不是把“该命中的政策”排到了前面。

## 为什么要单独测检索

- 检索错了，后面 LLM 再强也会答偏。
- 你这个场景是武汉园区服务，检索不只是“语义相似”，还要看：
  - 时效性：2026 > 2025
  - 区域性：武汉 > 湖北 > 国家
  - 产业性：人工智能、信息技术、装备制造、生物医药等优先
  - 业务性：OPC、小微企业、园区企业、高频办事问题优先

## 评测对象

直接调用：

- `POST /internal/v1/kb/search`

请求参数以当前服务真实支持的字段为准：

- `query`
- `kbIds`
- `topK`
- `minScore` / `scoreThreshold`
- `metadataFilter`
- `namespace`

返回结果里可自动判分的字段：

- `kbId`
- `documentId`
- `chunkId`
- `title`
- `score`
- `contentExcerpt`
- `citation`

## 测试层级

### 1. 文档级检索

看返回结果里是否命中了目标政策文档。

适合评估：

- 政策名称能否搜到
- 业务问法能否回到正确文件
- 区域 / 年份 / 产业能否把结果排对

### 2. 片段级检索

看返回结果里的 `contentExcerpt` 是否命中目标段落。

适合评估：

- 申报条件
- 支持对象
- 资金标准
- 办理流程
- 时限要求

### 3. 负例检索

用户问了，但知识库里没有或不该答。

看系统能否：

- 返回空结果
- 或低置信度结果
- 不编造

### 4. 业务排序质量

评测样本可以在 `expectedBehavior` 中声明排序要求，并在 `scenario` 或
`request` 中提供区域、年份等上下文。当前支持：

- `prefer_local` / `prefer_local_then_provincial`：无地区问题默认武汉优先；
- `prefer_latest`：用户明确年份或要求最新政策时，评估发布时间排序；
- `industry_priority`：评估目标产业政策是否排在无关产业之前；
- `chunkAnchors`：要求返回片段包含关键条件、对象、金额或流程锚点。

样本可以覆盖本次检索请求：

```json
{
  "id": "ret_2026_wh_opc_001",
  "query": "我们是武汉的人工智能 OPC 企业，有哪些扶持政策？",
  "request": {
    "kbIds": ["knowledge-base-id"],
    "topK": 5,
    "scoreThreshold": 0.2,
    "metadataFilter": {"common": {"region": "武汉"}},
    "namespace": "policy"
  },
  "scenario": {
    "region": "武汉",
    "year": 2026,
    "industry": "人工智能",
    "entityType": "OPC"
  },
  "golden": {
    "titles": ["武汉市人工智能 OPC 企业认定办法（试行）"],
    "chunkAnchors": ["OPC", "申报条件", "扶持"]
  },
  "expectedBehavior": "prefer_local_then_provincial",
  "priority": 1,
  "answerable": true
}
```

文档 ground truth 支持三种稳定度不同的定位方式：

- `goldenDocumentIds` / `golden.docIds`：最精确，但重新入库后 ID 可能变化；
- `goldenTitles` / `golden.titles`：推荐用于政策文档；
- `goldenSourceRefs` / `golden.sourceRefs`：适合目录路径或稳定来源标识。

## 测试集结构

建议每条样本长这样：

```json
{
  "case_id": "ret_2026_wh_001",
  "query": "我们公司在汉阳区，做人工智能OPC，能申报什么政策？",
  "scenario": {
    "region": "武汉",
    "district": "汉阳",
    "industry": "新一代信息技术产业",
    "company_size": "1-50人",
    "entity_type": "OPC"
  },
  "request": {
    "kb_ids": ["..."],
    "top_k": 5,
    "score_threshold": 0.2,
    "metadata_filter": {
      "city": "武汉",
      "publishYear": 2026
    }
  },
  "golden": {
    "doc_ids": ["..."],
    "chunk_anchors": ["OPC", "认定", "扶持"]
  },
  "expected_behavior": "prefer_local_then_provincial",
  "answerable": true,
  "priority": 1,
  "tags": ["武汉", "2026", "人工智能", "OPC", "资金奖补"]
}
```

## 标签体系

### 必备标签

- `region`: 国家 / 湖北 / 武汉
- `year`: 2026 / 2025
- `industry`
- `policy_type`
- `support_mode`
- `answerable`
- `priority`

`priority` 约定为 `1` 最高、`2` 普通、`3` 较低；`WeightedPassRate` 会让高优先级样本占更大权重。

### 业务标签

- `opc`
- `small_business`
- `park_service`
- `finance`
- `ip`
- `talent`
- `project_apply`
- `employment`

## 样本分类

### A. 直接命中文档

用户直接问政策名或高度接近政策名。

例：

- “武汉市人工智能OPC企业认定办法是什么？”
- “湖北省工伤预防五年行动方案怎么理解？”

### B. 业务场景问法

用户不提文件名，只说业务需求。

例：

- “我们是汉阳区 20 人的 AI 公司，能申报什么？”
- “小微企业想办知识产权贷款，武汉有啥政策？”

### C. 无地区问法

用户没说武汉/湖北，但平台默认是武汉园区服务。

例：

- “我们想申请扶持，应该看什么政策？”
- “研发型企业有什么补贴？”

这里重点看：

- 是否优先武汉
- 是否在武汉无结果时再补湖北
- 是否最后才看国家

### D. 省级政策问法

用户明确问湖北省。

例：

- “湖北省有没有中小企业数字化转型政策？”
- “湖北省知识产权行政保护相关文件有哪些？”

### E. 负例 / 过期 / 不适用

例：

- “2022 年武汉人工智能 OPC 认定政策还能用吗？”
- “外地城市的政策能不能直接套到武汉？”

### F. 业务排序质量

评测样本可以在 `expectedBehavior` 中声明排序要求，并在 `scenario` 或
`request` 中提供区域、年份等上下文。当前支持：

- `prefer_local` / `prefer_local_then_provincial`：无地区问题默认武汉优先；
- `prefer_latest`：用户要求最新政策时评估发布时间排序；
- `chunkAnchors`：要求返回片段包含条件、对象、金额或流程锚点。

## 自动生成策略

### 1. 用元数据筛重点政策

按你现有口径先筛：

- 武汉 2026
- 武汉 2025
- 湖北 2026
- 湖北 2025

并优先保留：

- `若干措施`
- `实施方案`
- `实施意见`
- `管理办法`
- `行动方案`
- `认定办法`
- `政策落实指南`
- `技术经理人`
- `孵化器`
- `知识产权`
- `科技金融`
- `OPC`

### 2. 用 AI 生成问法

AI 负责把同一政策扩成多种自然问法：

- 政策名直问
- 口语化问法
- 场景化问法
- 模糊问法
- 追问式问法

人工只做抽检，不人工从零写满。

### 3. 用规则自动打标签

标签来源优先级：

1. 文件元数据
2. 标题关键词
3. 正文段落关键词
4. 人工修正

## 评测指标

### 文档级

- `Recall@K`
- `MRR@K`
- `nDCG@K`
- `HitRate@1`
- `HitRate@K`

### 业务级

- `LocalPriorityHitRate`
- `ProvinceFallbackRate`
- `NoAnswerAccuracy`
- `WrongRegionPenalty`
- `PolicyFreshnessScore`
- `IndustryRelevanceScore`
- `WeightedPassRate`：按样本 `priority` 汇总，高优先级业务样本权重更高

### 片段级

- `AnchorHitRate`
- `ChunkRecall@K`

### 速度级

- `LatencyMs`：单次检索端到端延迟（毫秒），逐条记录，汇总 avg / p50 / p95 / max。
- 用于回归 HNSW 索引、oversample、rerank 等对检索耗时的实际影响。

## 推荐初始门槛

先用这组做第一版回归门槛：

- `Recall@5 >= 0.85`
- `MRR@5 >= 0.70`
- `HitRate@1 >= 0.60`
- `LocalPriorityHitRate >= 0.80`
- `NoAnswerAccuracy >= 0.90`

## 目录建议

评测服务当前位于 `services/evaluation_service/`，后续可以继续按能力拆分为：

```text
services/evaluation_service/
  retrieval/
    cases/
      retrieval_cases.jsonl
      retrieval_smoke.jsonl
      retrieval_regression.jsonl
    runner.py
    builder.py
    metrics.py
    report.py
  answer/
    ...
  data/
    policies/
    questions/
    manifests/
```

## 这版先不做的事

- 不先测 LLM 回答质量
- 不先做 Langfuse trace 级评分
- 不把旧的 trace evaluator 当主线继续扩

## 下一步

1. 先把检索评测集定成 JSONL。
2. 再把 `knowledge-service` 的搜索结果做自动判分。
3. 最后再接 LLM 回答评测。

## 运行方式

默认运行 8 条真实咨询 smoke 集：

```powershell
.\.venv\Scripts\python.exe -m services.evaluation_service.main --kb-id <知识库ID>
```

只运行一条样本：

```powershell
.\.venv\Scripts\python.exe -m services.evaluation_service.main --kb-id <知识库ID> --case-id smoke_wh_opc_recognition
```

旧的 `政策文件类Agent评估集.jsonl` 保留作为原始问题来源，但其中大量样本是
元数据分类统计问题，不应直接作为真实咨询回归集使用。
