"""知识库检索与回答依据测试（罗盛哲）。

测 AI 流水线的检索层 + 回答依据层：先把「该被检索到的政策有没有被检索到、排在第几位」
量化成 Hit@K / Hit@1 / MRR，再校验 Agent 的回答确实建立在这批检索结果之上。

指标口径对齐 services/evaluation_service/（runner.py / schemas.py）：region 走
_raw → common → domain 展平后取 region|区域（回退 city→武汉、province→湖北，否则国家），
published_year 取 publishedAt|publishTime|发布时间 里第一个 4 位年份。命中文档的这两个
字段搜索接口不返回，只能另外拉一次文档目录。

运行：test_ai\\run_all.cmd 一键执行（自动发现本文件，无需注册）。
本文件不向磁盘写任何内容，报告与回答只在当前进程内复用；环境不可用时整体 SKIP 而非
ERROR，避免连坐同目录下其他同学的用例。
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from conftest import AITestClient, assert_kb_tool_used


pytestmark = [pytest.mark.ai, pytest.mark.rag]

# 与 conftest 的 AI_TEST_TOP_K / AI_TEST_SCORE_THRESHOLD 一致：必须和 Agent 的
# knowledge.topK / scoreThreshold 相同，否则排名口径对不上。
TEAM_TOP_K = int(os.getenv("AI_TEST_TOP_K", "5"))
TEAM_SCORE_THRESHOLD = float(os.getenv("AI_TEST_SCORE_THRESHOLD", "0.2"))
# 全局默认算法是 vector（KNOWLEDGE_DEFAULT_SEARCH_STRATEGY），它没有任何地区/时效偏好，
# 正好当「换算法能带来多少提升」的基线。
TEAM_BASELINE_STRATEGY = os.getenv("AI_TEST_BASELINE_STRATEGY", "vector").strip().lower()
# knowledge_proxy 限流 60 次/分钟；一次策略全集扫描要发 54 次检索，1.3s 间隔留出余量。
SEARCH_INTERVAL_SECONDS = float(os.getenv("AI_TEST_SEARCH_INTERVAL_SECONDS", "1.3"))

# 镜像 services/knowledge_service/retrieval/__init__.py 注册的算法名。
STRATEGIES = (
    "vector",
    "vector_reranker",
    "weighted",
    "weighted_reranker",
    "hybrid",
    "hybrid_reranker",
    "keyword",
    "fulltext",
    "keyword_rank",
)

# 用例数据写死在脚本里：.gitignore 全局忽略 *.jsonl，用例文件落到 test_ai/ 会被 git 丢掉。
# 每条对应真实语料 services/evaluation_service/data/policies/{2025,2026}/{武汉,湖北}/ 里的一篇政策；
# golden 给多种写法（书名号/空格差异），命中任意一个即算目标文档。
RAG_CASES = (
    dict(
        case_id="st_ai_rag_001",
        query="《武汉市人工智能OPC企业认定办法（试行）》对全职从业人员数量和人工智能投入占比有什么要求？",
        golden=("市人工智能产业专班关于印发武汉市人工智能OPC企业认定办法（试行）的通知",),
    ),
    dict(
        case_id="st_ai_rag_002",
        query="我们公司在武汉做AI客服，团队一共8个人，想把公司认定成OPC，算力和Token投入大概要占到多少比例才行？",
        golden=("市人工智能产业专班关于印发武汉市人工智能OPC企业认定办法（试行）的通知",),
    ),
    dict(
        case_id="st_ai_rag_003",
        query="武汉的人工智能企业在算力使用上有哪些补贴政策？",
        golden=("汉阳区支持人工智能OPC创新发展若干措施", "江城基金OPC政策落实指南"),
    ),
    dict(
        case_id="st_ai_rag_004",
        query="武汉市支持人工智能OPC创新发展的若干措施里包含哪些支持政策？",
        golden=("市人民政府关于印发武汉市支持人工智能 OPC 创新发展若干措施的通知",),
    ),
    dict(
        case_id="st_ai_rag_005",
        query="湖北省“人工智能+制造”专项行动实施方案提出了哪些重点任务？",
        golden=("湖北省“人工智能+制造”专项行动实施方案", "湖北省人工智能+制造专项行动实施方案"),
    ),
    dict(
        case_id="st_ai_rag_006",
        query="武汉市重点研发计划人工智能OPC创新专项的适用对象包括哪些主体？",
        golden=("武汉市重点研发计划人工智能 OPC创新专项实施方案(试行)",),
    ),
)

_CLIENT: AITestClient | None = None
_REPORTS: dict[str | None, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 元数据推导（对齐 services/evaluation_service/runner.py）
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _metadata_view(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """展平 _raw / common / domain 三层，顶层非下划线键优先级最高。"""
    view: dict[str, Any] = {}
    for section in ("_raw", "common", "domain"):
        if isinstance(metadata.get(section), Mapping):
            view.update(metadata[section])
    view.update({k: v for k, v in metadata.items() if not str(k).startswith("_")})
    return view


def _region(metadata: Mapping[str, Any]) -> str:
    """区域标签，只认 武汉 / 湖北 / 国家 三档。

    runner 还有一个 place|地区 分支，但它恒返回「湖北」，是死代码，这里不复刻。
    """
    view = _metadata_view(metadata or {})
    text = _norm(view.get("region") or view.get("区域"))
    if text:
        if "武汉" in text:
            return "武汉"
        if "湖北" in text:
            return "湖北"
        return "国家" if "国" in text or "中央" in text else text
    if _norm(view.get("city") or view.get("城市")):
        return "武汉"
    if _norm(view.get("province") or view.get("省份")):
        return "湖北"
    return "国家"


def _year(metadata: Mapping[str, Any]) -> int | None:
    """发布年份：publishedAt / publishTime / 发布时间 里第一个 4 位数字。"""
    view = _metadata_view(metadata or {})
    for key in ("publishedAt", "publishTime", "发布时间"):
        match = re.search(r"(19|20)\d{2}", str(view.get(key) or ""))
        if match:
            return int(match.group(0))
    return None


def _match(actual: str, expected: str) -> bool:
    """去空白后双向包含，兼容库内标题带 `编号_哈希_` 前缀或书名号/空格差异。"""
    left, right = _norm(actual), _norm(expected)
    return bool(left and right) and (left == right or right in left or left in right)


# ---------------------------------------------------------------------------
# 在线数据获取
# ---------------------------------------------------------------------------


def _client() -> AITestClient:
    if _CLIENT is None:
        pytest.fail("本模块的用例必须依赖 live_answers fixture，由它绑定共享的 ai_client")
    return _CLIENT


def _catalog(client: AITestClient) -> dict[str, dict[str, Any]]:
    """文档目录：搜索接口不返回命中文档的 region / published_year，只能从这里取。"""
    catalog: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        try:
            response = client.http.get(
                f"/api/v1/admin/platform/knowledge-bases/{client.kb_id}/documents",
                params={"includeArchived": "false", "page": page, "pageSize": 100},
                headers={"Authorization": f"Bearer {client.user_token}"},
            )
        except httpx.HTTPError as exc:
            pytest.skip(f"无法读取知识库文档目录（{client.base_url}）：{exc}")
        if not response.is_success:
            pytest.skip(f"读取知识库文档目录失败：HTTP {response.status_code} {response.text[:200]}")
        payload = response.json()
        for item in payload.get("items") or []:
            document_id = str(item.get("id") or "").strip()
            metadata = item.get("metadataJson")
            if document_id:
                metadata = metadata if isinstance(metadata, Mapping) else {}
                catalog[document_id] = {
                    "title": str(item.get("title") or ""),
                    "region": _region(metadata),
                    "year": _year(metadata),
                }
        if page >= int(payload.get("totalPages") or 1):
            break
        page += 1
    if not catalog:
        pytest.skip("知识库文档目录为空：请确认政策语料已完成入库")
    return catalog


def _search(client: AITestClient, query: str, strategy: str | None) -> list[Any]:
    body: dict[str, Any] = {
        "query": query,
        "kbIds": [client.kb_id],
        "topK": TEAM_TOP_K,
        "minScore": TEAM_SCORE_THRESHOLD,
    }
    if strategy:
        body["strategy"] = strategy
    try:
        response = client.http.post(
            "/api/v1/admin/platform/knowledge-search",
            headers={
                "Authorization": f"Bearer {client.user_token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    except httpx.HTTPError as exc:
        pytest.skip(f"调用知识库检索失败（{client.base_url}）：{exc}")
    if not response.is_success:
        pytest.skip(f"知识库检索失败：HTTP {response.status_code} {response.text[:200]}")
    items = response.json().get("items")
    if not isinstance(items, list):
        pytest.skip("知识库检索响应缺少 items")
    return items


def _dedupe(items: list[Any]) -> list[Mapping[str, Any]]:
    """按 documentId 去重、保留首次出现（同一文档的多个 chunk 只算一次）。"""
    seen: set[str] = set()
    unique: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        document_id = str(item.get("documentId") or "").strip()
        if document_id and document_id not in seen:
            seen.add(document_id)
            unique.append(item)
    return unique


def _reciprocal_rank(case: Mapping[str, Any]) -> float:
    ranks = [row["rank"] for row in case["ranking"] if row["matched"]]
    return 1.0 / min(ranks) if ranks else 0.0


def _summary(cases: list[Mapping[str, Any]]) -> dict[str, float]:
    total = len(cases) or 1
    return {
        "hit_at_k_rate": round(sum(1 for c in cases if c["hit_at_k"]) / total, 6),
        "hit_at_1_rate": round(sum(1 for c in cases if c["hit_at_1"]) / total, 6),
        "mrr": round(sum(_reciprocal_rank(c) for c in cases) / total, 6),
    }


def _build_report(strategy: str | None) -> dict[str, Any]:
    client = _client()
    catalog = _catalog(client)
    cases: list[dict[str, Any]] = []
    for index, case in enumerate(RAG_CASES):
        golden = {
            document_id
            for document_id, document in catalog.items()
            if any(_match(document["title"], title) for title in case["golden"])
        }
        if not golden:
            pytest.skip(
                f"知识库里找不到 {case['case_id']} 的目标文档 {list(case['golden'])}；"
                "请确认政策语料已导入该知识库"
            )
        hits = _dedupe(_search(client, case["query"], strategy))
        if index < len(RAG_CASES) - 1:
            time.sleep(SEARCH_INTERVAL_SECONDS)
        top = hits[0] if hits else None
        cases.append(
            {
                "case_id": case["case_id"],
                "hit_at_k": any(h.get("documentId") in golden for h in hits),
                "hit_at_1": bool(hits and hits[0].get("documentId") in golden),
                "matched_count": sum(1 for h in hits if h.get("documentId") in golden),
                "top_title": None if top is None else str(top.get("title") or ""),
                "top_score": None if top is None else float(top.get("score") or 0.0),
                "ranking": [
                    {
                        "rank": index + 1,
                        "region": catalog.get(str(hit.get("documentId")), {}).get("region"),
                        "published_year": catalog.get(str(hit.get("documentId")), {}).get("year"),
                        "matched": hit.get("documentId") in golden,
                    }
                    for index, hit in enumerate(hits)
                ],
            }
        )
    return {"strategy": strategy, "summary": _summary(cases), "cases": cases}


# ---------------------------------------------------------------------------
# 报告设施
# ---------------------------------------------------------------------------


def load_report(strategy: str | None = None) -> dict[str, Any]:
    """指定算法的检索评估报告。``strategy=None`` 走知识库/全局默认算法。

    报告只在当前进程内复用：同一次 pytest 里重复调用不会重复发检索请求，但绝不落盘。
    """
    if strategy not in _REPORTS:
        _REPORTS[strategy] = _build_report(strategy)
    return _REPORTS[strategy]


def case_result(report: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    for case in report["cases"]:
        if case["case_id"] == case_id:
            return case
    pytest.fail(f"报告中没有 {case_id} 的结果")


def ranking(report: Mapping[str, Any], case_id: str) -> list[dict[str, Any]]:
    return list(case_result(report, case_id)["ranking"])


def available_strategies() -> tuple[str, ...]:
    """参与换算法对比的全部检索算法；缺的报告会在 load_report 里自动生成。"""
    return STRATEGIES


# ---------------------------------------------------------------------------
# 回答依据设施
# ---------------------------------------------------------------------------


def assert_grounded(answer: str, *golden_titles: str) -> None:
    """断言回答确实有知识库依据，而不是模型自己编的。

    两份证据缺一不可：
    1. 流式回答里出现 ``knowledge_base_search`` 工具调用记录（证明确实检索过）；
    2. 回答里看得到可核验的依据痕迹——政策名 ``《…》``、发文字号 ``〔2025〕3号``，
       或「知识库 / 检索」这类表述；调用方也可直接传 golden 标题做精确校验。
    """
    assert_kb_tool_used(answer)
    if golden_titles and any(_match(answer, title) for title in golden_titles):
        return
    assert re.search(r"《[^》]{4,}》|〔\d{4}〕\s*\d+\s*号|知识库|检索", answer), (
        f"回答看不出任何可核验的知识库依据：\n{answer[:800]}"
    )


@pytest.fixture(scope="session")
def live_answers(request: pytest.FixtureRequest) -> dict[str, str]:
    """case_id -> Agent 回答。整个会话只取一次，不落盘。"""
    global _CLIENT
    try:
        _CLIENT = request.getfixturevalue("ai_client")
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # 环境没配好一律 SKIP，避免连坐其他同学的用例
        pytest.skip(f"AI 测试环境不可用（{type(exc).__name__}: {exc}）")

    answers: dict[str, str] = {}
    for case in RAG_CASES:
        display_id = case["case_id"].replace("_", "-").upper()
        try:
            answers[case["case_id"]] = _CLIENT.ask(display_id, case["query"])
        except pytest.skip.Exception:
            raise
        except Exception as exc:
            pytest.skip(f"在线获取 {display_id} 的 Agent 回答失败：{exc}")
    return answers


def live_answer(live_answers: Mapping[str, str], case_id: str) -> str:
    if not live_answers.get(case_id):
        pytest.fail(f"没有拿到 {case_id} 的 Agent 回答")
    return live_answers[case_id]


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_st_ai_rag_001_named_policy_reaches_top_k(live_answers: dict[str, str]):
    """按政策原名提问时，目标文档应进入 Top-K，且回答有知识依据。"""
    report = load_report()
    result = case_result(report, "st_ai_rag_001")
    assert result["hit_at_k"] is True, (
        f"直接按政策原名提问，目标文档未进入 Top-{TEAM_TOP_K}；"
        f"Top-1 是「{result['top_title']}」（得分 {result['top_score']}）"
    )
    assert_grounded(live_answer(live_answers, "st_ai_rag_001"))


def test_st_ai_rag_002_business_scenario_hits_expected_policy(live_answers: dict[str, str]):
    """口语化业务场景提问应命中目标政策，而不是只命中泛泛的同主题文档。"""
    report = load_report()
    result = case_result(report, "st_ai_rag_002")
    assert result["matched_count"] >= 1, (
        f"口语化业务场景提问未命中任何目标政策；Top-1 是「{result['top_title']}」"
    )
    assert_grounded(live_answer(live_answers, "st_ai_rag_002"))


def test_st_ai_rag_003_wuhan_outranks_province_and_national(live_answers: dict[str, str]):
    """同一主题下，武汉本地政策应排在省级/国家级政策之前。"""
    report = load_report()
    items = ranking(report, "st_ai_rag_003")
    wuhan_ranks = [int(i["rank"]) for i in items if i.get("region") == "武汉"]
    other_ranks = [int(i["rank"]) for i in items if i.get("region") in {"湖北", "国家"}]
    assert wuhan_ranks, "Top-K 里一份武汉政策都没有"
    if other_ranks:
        assert max(wuhan_ranks) < min(other_ranks), (
            f"武汉政策未优先于省级/国家级政策：武汉位次={sorted(wuhan_ranks)}，"
            f"其他地区位次={sorted(other_ranks)}"
        )
    assert_grounded(live_answer(live_answers, "st_ai_rag_003"))


@pytest.mark.xfail(strict=False, reason="默认 vector 检索没有时效偏好，旧政策可能压住 2026 年新政策")
def test_st_ai_rag_004_newest_policy_ranks_first(live_answers: dict[str, str]):
    """时效性：2026 年目标政策之前不应出现同主题的旧政策。"""
    report = load_report()
    items = ranking(report, "st_ai_rag_004")
    target_ranks = [int(i["rank"]) for i in items if i.get("matched")]
    assert target_ranks, "Top-K 里没有目标文档"
    stale_count = sum(
        1
        for i in items
        if i.get("matched") is not True
        and i.get("published_year") is not None
        and int(i["published_year"]) < 2026
        and int(i["rank"]) < min(target_ranks)
    )
    assert stale_count == 0, "有旧政策排在 2026 年目标文档之前"
    assert_grounded(live_answer(live_answers, "st_ai_rag_004"))


def test_st_ai_rag_005_switching_strategy_changes_hit_rate(live_answers: dict[str, str]):
    """换检索算法应当带来 Hit@1 提升——这是「检索层可调优」的核心证据。"""
    report = load_report(TEAM_BASELINE_STRATEGY)
    baseline = report["summary"]
    others = {
        name: load_report(name)["summary"]["hit_at_1_rate"] for name in available_strategies()
    }
    better = {name: rate for name, rate in others.items() if rate > baseline["hit_at_1_rate"]}
    assert better, (
        f"换算法没有带来任何 Hit@1 提升，默认 {TEAM_BASELINE_STRATEGY}="
        f"{baseline['hit_at_1_rate']}，全部策略={others}"
    )
    assert_grounded(live_answer(live_answers, "st_ai_rag_006"))
