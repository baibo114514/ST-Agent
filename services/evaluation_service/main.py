#!/usr/bin/env python3
"""检索评估 CLI 入口。

用法示例（详见 README）：
    python -m services.evaluation_service.main --kb-id <知识库ID>
    python -m services.evaluation_service.main --kb-id <ID> --limit 8 --no-report
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from services.evaluation_service.client import KnowledgeServiceError
from services.evaluation_service.runner import run_retrieval_eval
from services.evaluation_service.profiles import normalize_namespace_label
from services.evaluation_service.settings import RetrievalEvalConfig


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器，所有参数均对应 RetrievalEvalConfig 的覆盖项。"""
    parser = argparse.ArgumentParser(description="Retrieval evaluation runner for knowledge-service.")
    parser.add_argument(
        "--cases",
        dest="cases_path",
        type=Path,
        default=None,
        help="Path to retrieval cases JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help="Directory for reports.",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default=None,
        help="Knowledge-service base URL.",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=None,
        help="Knowledge-service token.",
    )
    parser.add_argument(
        "--kb-id",
        dest="kb_ids",
        action="append",
        default=None,
        help="Default knowledge base id. Repeatable.",
    )
    parser.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=None,
        help="Default topK for search requests.",
    )
    parser.add_argument(
        "--score-threshold",
        dest="score_threshold",
        type=float,
        default=None,
        help="Default score threshold for search requests.",
    )
    parser.add_argument(
        "--strategy",
        dest="strategy",
        default=None,
        help=(
            "Override retrieval strategy for all cases "
            "(vector/vector_reranker/weighted/weighted_reranker/hybrid/hybrid_reranker/"
            "keyword/fulltext/keyword_rank)."
        ),
    )
    parser.add_argument(
        "--namespace",
        dest="namespace",
        default=None,
        help="Evaluation namespace (policy/service).",
    )
    parser.add_argument(
        "--interval",
        dest="request_interval_seconds",
        type=float,
        default=None,
        help="Seconds to sleep between requests.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=float,
        default=None,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--page-size",
        dest="document_page_size",
        type=int,
        default=None,
        help="Document catalog page size.",
    )
    parser.add_argument("--local-priority-threshold", type=float, default=None)
    parser.add_argument("--freshness-threshold", type=float, default=None)
    parser.add_argument("--chunk-anchor-threshold", type=float, default=None)
    parser.add_argument("--industry-relevance-threshold", type=float, default=None)
    parser.add_argument("--negative-max-score", type=float, default=None)
    parser.add_argument("--no-report", action="store_true", help="Do not write JSON and Markdown reports")
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=None,
        help="Limit number of cases.",
    )
    parser.add_argument(
        "--case-id",
        dest="case_ids",
        action="append",
        default=None,
        help="Run only selected case ids. Repeatable.",
    )
    return parser


def _merge_list_values(values: list[str] | None) -> list[str]:
    """合并可重复参数与逗号分隔值（如 --kb-id a --kb-id b,c），去重保序。"""
    merged: list[str] = []
    for value in values or []:
        for piece in str(value).split(","):
            text = piece.strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def build_config(args: argparse.Namespace) -> RetrievalEvalConfig:
    """把解析后的命令行参数覆盖到默认配置上（仅覆盖显式传入项）。"""
    config = RetrievalEvalConfig()
    if args.cases_path is not None:
        config.cases_path = args.cases_path
    if args.output_dir is not None:
        config.output_dir = args.output_dir
    if args.base_url:
        config.knowledge_service_base_url = args.base_url
    if args.token is not None:
        config.knowledge_service_token = args.token
    if args.kb_ids:
        config.default_kb_ids = _merge_list_values(args.kb_ids)
    if args.top_k is not None:
        config.top_k = args.top_k
    if args.score_threshold is not None:
        config.score_threshold = args.score_threshold
    if args.strategy is not None:
        config.strategy = args.strategy
    if args.namespace is not None:
        config.namespace = normalize_namespace_label(args.namespace)
    if args.request_interval_seconds is not None:
        config.request_interval_seconds = args.request_interval_seconds
    if args.timeout_seconds is not None:
        config.timeout_seconds = args.timeout_seconds
    if args.document_page_size is not None:
        config.document_page_size = args.document_page_size
    if args.local_priority_threshold is not None:
        config.local_priority_threshold = args.local_priority_threshold
    if args.freshness_threshold is not None:
        config.freshness_threshold = args.freshness_threshold
    if args.chunk_anchor_threshold is not None:
        config.chunk_anchor_threshold = args.chunk_anchor_threshold
    if args.industry_relevance_threshold is not None:
        config.industry_relevance_threshold = args.industry_relevance_threshold
    if args.negative_max_score is not None:
        config.negative_max_score = args.negative_max_score
    if args.no_report:
        config.generate_report = False
    if args.limit is not None:
        config.limit = args.limit
    if args.case_ids:
        config.case_ids = _merge_list_values(args.case_ids)
    return config


async def _run(args: argparse.Namespace) -> int:
    config = build_config(args)
    report = await run_retrieval_eval(config)
    print(f"cases={report.summary.case_count}")
    print(f"pass_rate={report.summary.pass_count}/{report.summary.case_count}")
    print(f"namespace={report.namespace or config.namespace or '-'}")
    print(f"profile={report.profile_name or '-'}")
    print(f"precision_at_k={report.summary.precision_at_k:.3f}")
    print(f"mrr={report.summary.mrr:.3f}")
    print(f"ndcg_at_k={report.summary.ndcg_at_k:.3f}")
    print(f"local_priority_score={report.summary.local_priority_score:.3f}")
    print(f"freshness_score={report.summary.freshness_score:.3f}")
    print(f"industry_relevance_score={report.summary.industry_relevance_score:.3f}")
    print(f"route_entry_rate={report.summary.route_entry_rate:.3f}")
    print(f"step_by_step_rate={report.summary.step_by_step_rate:.3f}")
    print(f"service_info_rate={report.summary.service_info_rate:.3f}")
    print(f"need_clarification_rate={report.summary.need_clarification_rate:.3f}")
    print(f"boundary_refuse_rate={report.summary.boundary_refuse_rate:.3f}")
    print(f"weighted_pass_rate={report.summary.weighted_pass_rate:.3f}")
    print(f"report_dir={config.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KnowledgeServiceError as exc:
        logging.getLogger("evaluation_service").exception("retrieval_eval_cli_failed: %s", exc)
        if exc.status_code == 404:
            print("指定的知识库不存在，请先从 knowledge-service 查询当前 KB ID，再重新传入 --kb-id。", file=sys.stderr)
        else:
            print(f"检索评测失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logging.getLogger("evaluation_service").exception("retrieval_eval_cli_failed: %s", exc)
        print(f"检索评测失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
