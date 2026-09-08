#!/usr/bin/env python3
"""按 JSON 配置批量跑多知识库、多策略检索评估。

输入一个 JSON 配置文件，其中声明多个「数据集」：每个数据集指定知识库（kb_name / kb_id /
namespace）、用例文件、检索策略与样本/运行时参数。脚本逐个数据集执行：解析 kb-id →
按 namespace 生成带 request.namespace 的临时用例文件 → 建目录（复用一次）→ 逐策略跑分
→ 多策略时额外输出横向对比报告。

用法：
    python scripts/eval_by_name.py eval_by_name.example.json

JSON 里的相对路径均相对脚本所在目录（scripts/）解析；示例见 eval_by_name.example.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, model_validator

from services.evaluation_service.report import write_comparison_report
from services.evaluation_service.profiles import (
    infer_namespace_label_from_path,
    knowledge_namespace,
    normalize_namespace_label,
)
from services.evaluation_service.runner import prepare_retrieval_catalog, run_retrieval_eval
from services.evaluation_service.schemas import RetrievalReport
from services.evaluation_service.settings import RetrievalEvalConfig

SCRIPT_DIR = Path(__file__).resolve().parent

# 与 retrieval/__init__.py 注册的策略一一对应：向量类三算法各分「无后缀=不重排」
# 与「_reranker=重排」两个变体，其余 keyword/fulltext/keyword_rank 无重排变体。
ALL_STRATEGIES = [
    "vector",
    "vector_reranker",
    "weighted",
    "weighted_reranker",
    "hybrid",
    "hybrid_reranker",
    "keyword",
    "fulltext",
    "keyword_rank",
]

class EvalDatasetConfig(BaseModel):
    """单条数据集评测配置：知识库 + 用例集 + 策略 + 样本/运行时参数。"""

    name: str
    kb_name: str | None = None
    kb_id: str | None = None
    namespace: str | None = None
    cases: str
    strategies: list[str] = Field(default_factory=lambda: list(ALL_STRATEGIES))
    limit: int | None = None
    case_ids: list[str] = Field(default_factory=list)
    interval: float | None = None
    no_report: bool = False

    @model_validator(mode="after")
    def _require_kb(self) -> "EvalDatasetConfig":
        if self.namespace is not None:
            self.namespace = normalize_namespace_label(self.namespace)
        if not self.kb_name and not self.kb_id and not self.namespace:
            raise ValueError("每个 dataset 必须提供 kb_name、kb_id 或 namespace 之一")
        return self


class EvalConfigFile(BaseModel):
    """eval_by_name 的 JSON 配置文件。"""

    output_dir: str | None = None
    datasets: list[EvalDatasetConfig]


def _resolve_path(value: str) -> Path:
    """相对路径按脚本所在目录（scripts/）解析，绝对路径原样返回。"""
    path = Path(value)
    resolved = path if path.is_absolute() else SCRIPT_DIR / path
    return resolved.resolve()


def _safe_name(name: str) -> str:
    """把数据集名转成安全的目录名。"""
    return name.replace("/", "_").replace("\\", "_").strip() or "dataset"


def _dataset_namespace_label(dataset: EvalDatasetConfig) -> str:
    """取数据集对外 namespace 标签；未显式指定时按用例文件路径推断。"""
    if dataset.namespace:
        return dataset.namespace
    return infer_namespace_label_from_path(_resolve_path(dataset.cases))


def _prepare_cases_file(dataset: EvalDatasetConfig, base_output_dir: Path) -> Path:
    """把原始 JSONL 复制成带 request.namespace 的临时版本。"""
    source_path = _resolve_path(dataset.cases)
    namespace_label = _dataset_namespace_label(dataset)
    request_namespace = knowledge_namespace(namespace_label)
    prepared_dir = base_output_dir / "_prepared_cases" / namespace_label
    prepared_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = prepared_dir / source_path.name

    with source_path.open("r", encoding="utf-8") as source, prepared_path.open("w", encoding="utf-8") as sink:
        for raw_line in source:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            raw = json.loads(line)
            request = raw.get("request")
            if not isinstance(request, dict):
                request = {}
            request["namespace"] = request_namespace
            raw["request"] = request
            sink.write(json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n")
    return prepared_path


async def _resolve_kb_id(
    config: RetrievalEvalConfig,
    kb_name: str | None,
    *,
    namespace: str | None = None,
) -> str:
    """按 namespace / 名称查知识库 id：先 namespace 精确匹配，再名称精确/子串兜底。"""
    url = f"{config.knowledge_service_base_url.rstrip('/')}/internal/v1/kb/bases"
    headers = {"X-KB-Service-Token": config.knowledge_service_token}
    # trust_env=False：本机 8010 的请求不走系统代理，否则 WinINET 代理会返回空 502。
    async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
        response = await client.get(url, headers=headers, params={"includeArchived": "false"})
        response.raise_for_status()
        payload = response.json()

    items = payload.get("items") or []
    namespace_label = normalize_namespace_label(namespace)
    namespace_filter = knowledge_namespace(namespace_label) if namespace_label else None

    def _format_candidates(candidates: list[dict[str, object]]) -> str:
        rendered: list[str] = []
        for base in candidates:
            name = str(base.get("name") or "").strip()
            base_namespace = str(base.get("namespace") or "").strip()
            rendered.append(f"{name}({base_namespace})" if base_namespace else name)
        return "、".join(rendered)

    def _match_name(candidates: list[dict[str, object]]) -> str | None:
        if not candidates:
            return None
        if kb_name:
            for base in candidates:
                if str(base.get("name") or "").strip() == kb_name:
                    return str(base["id"])
            for base in candidates:
                if kb_name in str(base.get("name") or ""):
                    return str(base["id"])
        if len(candidates) == 1:
            return str(candidates[0]["id"])
        return None

    if namespace_filter:
        namespace_matches = [base for base in items if str(base.get("namespace") or "").strip() == namespace_filter]
        picked = _match_name(namespace_matches)
        if picked:
            return picked

    picked = _match_name(items)
    if picked:
        return picked

    names = _format_candidates(items)
    if namespace_label:
        raise SystemExit(f"未找到 namespace={namespace_label} 对应的知识库；现有知识库：{names or '（无）'}")
    raise SystemExit(f"未找到知识库「{kb_name or 'unknown'}」；现有知识库：{names or '（无）'}")


def _build_config(
    dataset: EvalDatasetConfig,
    kb_id: str,
    *,
    cases_path: Path | None = None,
    strategy: str | None = None,
    output_dir: Path | None = None,
) -> RetrievalEvalConfig:
    """用数据集配置构建评估配置；strategy/output_dir 由调用方按需覆盖。"""
    config = RetrievalEvalConfig()
    config.default_kb_ids = [kb_id]
    config.cases_path = cases_path or _resolve_path(dataset.cases)
    config.namespace = _dataset_namespace_label(dataset)
    if dataset.limit is not None:
        config.limit = dataset.limit
    if dataset.case_ids:
        config.case_ids = list(dataset.case_ids)
    if dataset.interval is not None:
        config.request_interval_seconds = dataset.interval
    if strategy is not None:
        config.strategy = strategy
    if output_dir is not None:
        config.output_dir = output_dir
    return config


async def _run_dataset_async(
    dataset: EvalDatasetConfig,
    base_output_dir: Path,
    prepared_cases_path: Path,
) -> None:
    """跑单个数据集：解析 kb-id → 建目录 → 逐策略跑分 → 输出对比报告。"""
    config = RetrievalEvalConfig()
    namespace_label = _dataset_namespace_label(dataset)
    if dataset.kb_id:
        kb_id = dataset.kb_id
    else:
        kb_id = await _resolve_kb_id(config, dataset.kb_name, namespace=namespace_label)
    namespace_note = namespace_label if namespace_label == "policy" else f"{namespace_label} -> {knowledge_namespace(namespace_label)}"
    print(
        f"[{dataset.name}] namespace={namespace_note} "
        f"知识库「{dataset.kb_name or dataset.kb_id or namespace_label}」 -> kb-id = {kb_id}"
    )

    # 目录与检索策略无关，建一次复用，避免每个策略重复分页拉取全部文档触发限流(429)。
    catalog = await prepare_retrieval_catalog(_build_config(dataset, kb_id, cases_path=prepared_cases_path))

    dataset_dir = base_output_dir / _safe_name(dataset.name)
    strategies = dataset.strategies or ALL_STRATEGIES
    results: list[tuple[str, RetrievalReport]] = []
    for strategy in strategies:
        strat_config = _build_config(
            dataset,
            kb_id,
            cases_path=prepared_cases_path,
            strategy=strategy,
            output_dir=dataset_dir / strategy,
        )
        strat_config.generate_report = not dataset.no_report
        report = await run_retrieval_eval(strat_config, catalog=catalog)
        s = report.summary
        print(
            f"  strategy={strategy:<14} pass={s.pass_count}/{s.case_count} "
            f"mrr={s.mrr:.3f} ndcg={s.ndcg_at_k:.3f} precision={s.precision_at_k:.3f} "
            f"latency_avg={s.latency_ms_avg:.1f}ms p95={s.latency_ms_p95:.1f}ms"
        )
        results.append((strategy, report))

    # 多策略一起跑时，额外生成一份横向对比报告（markdown + csv）。
    if len(results) > 1 and not dataset.no_report:
        files = write_comparison_report(results, dataset_dir)
        print(f"  对比报告：{files['markdown']}")


def _run_dataset(dataset: EvalDatasetConfig, base_output_dir: Path) -> None:
    """先生成 namespace 归一化后的临时用例，再进入异步评测流程。"""
    prepared_cases_path = _prepare_cases_file(dataset, base_output_dir)
    asyncio.run(_run_dataset_async(dataset, base_output_dir, prepared_cases_path))


def main() -> int:
    # parser = argparse.ArgumentParser(description="按 JSON 配置批量跑多知识库、多策略检索评估。")
    # parser.add_argument("config", default="eval_by_name.example.json",help="评测配置 JSON 文件路径")
    # args = parser.parse_args()

    config_path = SCRIPT_DIR / "eval_by_name.example.json"
    config_file = EvalConfigFile.model_validate_json(config_path.read_text(encoding="utf-8"))

    if config_file.output_dir:
        base_output_dir = _resolve_path(config_file.output_dir)
    else:
        base_output_dir = Path(RetrievalEvalConfig().output_dir)

    for dataset in config_file.datasets:
        _run_dataset(dataset, base_output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
