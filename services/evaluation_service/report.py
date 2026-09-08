"""Report writing helpers for retrieval evaluation."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from services.evaluation_service.profiles import normalize_namespace_label
from services.evaluation_service.schemas import RetrievalReport


def write_report_files(report: RetrievalReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "retrieval_report.json"
    md_path = output_dir / "retrieval_report.md"

    json_path.write_text(report.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


# 多策略对比报告列定义：(字段名, 展示名, 格式化)。
_COMMON_COMPARISON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("precision_at_k", "Precision@K", ".3f"),
    ("recall_at_k", "Recall@K", ".3f"),
    ("mrr", "MRR", ".3f"),
    ("ndcg_at_k", "nDCG@K", ".3f"),
    ("hit_at_k_rate", "Hit@K", ".3f"),
    ("hit_at_1_rate", "Hit@1", ".3f"),
    ("chunk_anchor_hit_rate", "Anchor", ".3f"),
    ("weighted_pass_rate", "Weighted pass", ".3f"),
    ("no_answer_accuracy", "No answer", ".3f"),
    ("latency_ms_avg", "Latency avg", ".1f"),
    ("latency_ms_p50", "Latency p50", ".1f"),
    ("latency_ms_p95", "Latency p95", ".1f"),
)

_POLICY_COMPARISON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("local_priority_score", "Local", ".3f"),
    ("freshness_score", "Freshness", ".3f"),
    ("industry_relevance_score", "Industry", ".3f"),
    ("support_mode_relevance_score", "Support mode", ".3f"),
    ("policy_type_relevance_score", "Policy type", ".3f"),
    ("wrong_region_rate", "Wrong region", ".3f"),
)

_SERVICE_COMPARISON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("route_entry_rate", "Route entry", ".3f"),
    ("step_by_step_rate", "Step-by-step", ".3f"),
    ("service_info_rate", "Service info", ".3f"),
    ("need_clarification_rate", "Need clarify", ".3f"),
    ("boundary_refuse_rate", "Boundary refuse", ".3f"),
)


def _comparison_columns(namespace: str | None) -> tuple[tuple[str, str, str], ...]:
    normalized = normalize_namespace_label(namespace)
    if normalized == "policy":
        return (*_COMMON_COMPARISON_COLUMNS, *_POLICY_COMPARISON_COLUMNS)
    return (*_COMMON_COMPARISON_COLUMNS, *_SERVICE_COMPARISON_COLUMNS)


def write_comparison_report(
    results: list[tuple[str, RetrievalReport]],
    output_dir: Path,
) -> dict[str, Path]:
    """写多策略对比报告（markdown + csv），供一次跑多个策略时横向比较。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "comparison.md"
    csv_path = output_dir / "comparison.csv"
    md_path.write_text(render_comparison_markdown(results), encoding="utf-8")
    csv_path.write_text(render_comparison_csv(results), encoding="utf-8")
    return {"markdown": md_path, "csv": csv_path}


def render_comparison_markdown(results: list[tuple[str, RetrievalReport]]) -> str:
    """对比报告 markdown：一行一策略，列对齐关键指标。"""
    namespace = results[0][1].namespace if results else None
    columns = _comparison_columns(namespace)
    header = ["Strategy", "Pass"] + [label for _, label, _ in columns]
    lines = [
        "# Retrieval Strategy Comparison",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for name, report in results:
        summary = report.summary
        cells = [name, f"{summary.pass_count}/{summary.case_count}"]
        cells.extend(f"{getattr(summary, field):{fmt}}" for field, _, fmt in columns)
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_comparison_csv(results: list[tuple[str, RetrievalReport]]) -> str:
    """对比报告 csv：策略名 + 通过数/率 + 各指标数值，便于后续分析。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    namespace = results[0][1].namespace if results else None
    columns = _comparison_columns(namespace)
    writer.writerow(
        ["strategy", "pass_count", "case_count", "pass_rate"]
        + [field for field, _, _ in columns]
    )
    for name, report in results:
        summary = report.summary
        pass_rate = summary.pass_count / summary.case_count if summary.case_count else 0.0
        row = [name, summary.pass_count, summary.case_count, f"{pass_rate:.4f}"]
        row.extend(f"{getattr(summary, field):.4f}" for field, _, _ in columns)
        writer.writerow(row)
    return buffer.getvalue()


def _append_metric_lines(
    lines: list[str],
    metrics: list[tuple[str, float, str]],
) -> None:
    for label, value, fmt in metrics:
        lines.append(f"- {label}: {value:{fmt}}")


def render_markdown(report: RetrievalReport) -> str:
    lines: list[str] = []
    summary = report.summary
    lines.append("# Retrieval Evaluation Report")
    lines.append("")
    lines.append(f"- Generated at: {report.generated_at}")
    lines.append(f"- Namespace: `{report.namespace or '-'}`")
    lines.append(f"- Profile: `{report.profile_name or '-'}`")
    lines.append(f"- Base URL: `{report.base_url}`")
    lines.append(f"- Cases: `{report.cases_path}`")
    lines.append(f"- KB IDs: {', '.join(report.kb_ids) if report.kb_ids else '-'}")
    lines.append(f"- Total documents: {report.total_documents}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    _append_metric_lines(
        lines,
        [
            ("Case count", summary.case_count, ".0f"),
            ("Pass count", summary.pass_count, ".0f"),
            ("Fail count", summary.fail_count, ".0f"),
            ("Error count", summary.error_count, ".0f"),
            ("Precision@K", summary.precision_at_k, ".3f"),
            ("Recall@K", summary.recall_at_k, ".3f"),
            ("MRR", summary.mrr, ".3f"),
            ("nDCG@K", summary.ndcg_at_k, ".3f"),
            ("Chunk anchor hit rate", summary.chunk_anchor_hit_rate, ".3f"),
        ],
    )
    if normalize_namespace_label(report.namespace) == "policy":
        _append_metric_lines(
            lines,
            [
                ("Local priority score", summary.local_priority_score, ".3f"),
                ("Freshness score", summary.freshness_score, ".3f"),
                ("Industry relevance score", summary.industry_relevance_score, ".3f"),
                ("Support mode relevance score", summary.support_mode_relevance_score, ".3f"),
                ("Policy type relevance score", summary.policy_type_relevance_score, ".3f"),
                ("Wrong region rate", summary.wrong_region_rate, ".3f"),
            ],
        )
    else:
        _append_metric_lines(
            lines,
            [
                ("Route entry rate", summary.route_entry_rate, ".3f"),
                ("Step-by-step rate", summary.step_by_step_rate, ".3f"),
                ("Service info rate", summary.service_info_rate, ".3f"),
                ("Need clarification rate", summary.need_clarification_rate, ".3f"),
                ("Boundary refuse rate", summary.boundary_refuse_rate, ".3f"),
            ],
        )
    _append_metric_lines(
        lines,
        [
            ("Weighted pass rate", summary.weighted_pass_rate, ".3f"),
            ("Hit@K", summary.hit_at_k_rate, ".3f"),
            ("Hit@1", summary.hit_at_1_rate, ".3f"),
            ("No-answer accuracy", summary.no_answer_accuracy, ".3f"),
            ("Golden count mismatch rate", summary.golden_count_mismatch_rate, ".3f"),
        ],
    )
    _append_metric_lines(
        lines,
        [
            ("Latency avg", summary.latency_ms_avg, ".1f"),
            ("Latency p50", summary.latency_ms_p50, ".1f"),
            ("Latency p95", summary.latency_ms_p95, ".1f"),
            ("Latency max", summary.latency_ms_max, ".1f"),
        ],
    )
    lines.append("")

    if report.by_behavior:
        lines.append("## By Behavior")
        lines.append("")
        lines.append("| Behavior | Cases | Pass | Hit@K | Hit@1 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for behavior, data in sorted(report.by_behavior.items(), key=lambda item: item[0]):
            lines.append(
                f"| {behavior} | {data.case_count} | {data.pass_count} | {data.hit_at_k_rate:.3f} | {data.hit_at_1_rate:.3f} |"
            )
        lines.append("")

    if report.by_intent:
        lines.append("## By Intent")
        lines.append("")
        lines.append("| Intent | Cases | Pass | Precision@K | nDCG@K | Local |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for intent, data in sorted(report.by_intent.items(), key=lambda item: item[0]):
            lines.append(
                f"| {intent} | {data.case_count} | {data.pass_count} | {data.precision_at_k:.3f} | {data.ndcg_at_k:.3f} | {data.local_priority_score:.3f} |"
            )
        lines.append("")

    if report.by_priority:
        lines.append("## By Priority")
        lines.append("")
        lines.append("| Priority | Cases | Pass | Weighted Pass | Hit@1 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for priority, data in sorted(report.by_priority.items(), key=lambda item: item[0]):
            lines.append(
                f"| {priority} | {data.case_count} | {data.pass_count} | {data.weighted_pass_rate:.3f} | {data.hit_at_1_rate:.3f} |"
            )
        lines.append("")

    if report.by_tag:
        lines.append("## By Tag")
        lines.append("")
        lines.append("| Tag | Cases | Pass | Hit@K | Local |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for tag, data in sorted(report.by_tag.items(), key=lambda item: item[0]):
            lines.append(
                f"| {tag} | {data.case_count} | {data.pass_count} | {data.hit_at_k_rate:.3f} | {data.local_priority_score:.3f} |"
            )
        lines.append("")

    failed_cases = [case for case in report.cases if not case.passed][:20]
    if failed_cases:
        lines.append("## Failures")
        lines.append("")
        lines.append("| Case | Intent | Reason | Top Title | Region | Year |")
        lines.append("| --- | --- | --- | --- | --- | ---: |")
        for case in failed_cases:
            top = case.ranking[0] if case.ranking else None
            lines.append(
                f"| {case.case_id} | {case.intent or '-'} | {case.failure_reason or '-'} | {case.top_title or '-'} | {top.region if top else '-'} | {top.published_year if top else '-'} |"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"
