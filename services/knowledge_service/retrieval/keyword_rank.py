"""关键词评分 + 规则重排检索策略（keyword_rank）。

忠实移植自参考项目 `agent-paas/knowledge-service` 的「关键词检索型 RAG」：
jieba 分词 → ILIKE 粗筛（≤500 chunk）→ 焦点词硬过滤 → 位置加权评分
（标题/source_ref/正文/短语）→ policy 规则重排（年份匹配/时效/过期）。

不依赖 embedding。profile 固定 policy；legal 相关暂未移植，常量保留便于扩展。

⚠️ 重要说明：本算法是为参考项目「服务咨询类政策知识库 + 规范化短 query」设计的，
依赖其特有的知识库路径/章节等额外信号。移植到当前「口语化长问句 + 18k chunk 政策库」后，
停用词表与 query 分布失配，焦点词硬过滤（60% 覆盖率）在口语问法下大量误杀目标文档。

评估结论（100 条业务场景评估集，rerank 开）：
- 忠实版 0/100（recall@k=0、hit@k=0）——口语化问法下焦点词硬过滤失效。
- 结论：无嵌入的纯规则算法高度依赖停用词表与 query 规范度，不适合口语化问法场景，
  反而佐证了 embedding 语义检索的必要性。
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, List

import jieba
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from services.knowledge_service.retrieval.base import RecallEntry, SearchContext, SearchHit
from services.knowledge_service.retrieval.helpers import (
    _base_conditions,
    _has_searchable_chunk,
    _hit_to_dict,
    _maybe_rerank,
    normalize_score,
)
from services.knowledge_service.service import metadata_matches

# --- 常量（从参考项目移植） ---

SEARCH_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*|[㐀-䶿一-鿿]+")
CJK_TOKEN = re.compile(r"^[㐀-䶿一-鿿]+$")
SEARCH_STOP_WORDS = {
    "一个",
    "一下",
    "什么",
    "介绍",
    "你了解",
    "了解",
    "关于",
    "可以",
    "告诉",
    "如何",
    "怎么",
    "是什么",
    "有哪些",
    "知道",
    "请问",
    "项目吗",
}
CONVERSATIONAL_PHRASES = (
    "你了解吗",
    "能介绍一下吗",
    "介绍一下",
    "请问一下",
    "请问",
    "是什么",
    "有哪些",
    "怎么样",
    "如何",
)
GENERIC_SEARCH_TERMS = {
    "办法",
    "标准",
    "财政",
    "措施",
    "扶持",
    "管理",
    "企业",
    "工作",
    "工业",
    "培育",
    "市级",
    "武汉",
    "武汉市",
    "信息",
    "信息化",
    "申报",
    "科技",
    "认定",
    "条件",
    "通知",
    "项目",
    "政策",
    "支持",
}
POLICY_FRESHNESS_MARKERS = {
    "年度",
    "今年",
    "最新",
    "近期",
    "申报",
    "通知",
    "项目",
    "计划",
    "专项",
    "认定",
    "复核",
    "指南",
    "截止",
    "时间",
}
POLICY_RECENCY_MARKERS = {
    "本年度",
    "当前",
    "今年",
    "近期",
    "最新",
    "现在",
    "申报通知",
    "申报时间",
    "申报指南",
    "截止",
    "日期",
    "什么时候",
}
POLICY_SERVICE_STOP_TERMS = {
    "材料",
    "办理",
    "代办",
    "服务",
    "价格",
    "费用",
    "收费",
    "报价",
    "流程",
    "步骤",
    "资料",
    "清单",
    "咨询",
    "需要",
    "信息",
}
POLICY_SERVICE_CONTEXT_MARKERS = {
    "政策代办类知识库",
    "政策申报",
    "资质办理",
    "知识产权",
    "服务价格",
    "市场参考价格",
    "服务咨询",
    "服务流程",
    "服务内容",
    "服务描述",
    "代理服务",
}
POLICY_SERVICE_SECTION_MARKERS = {
    "agency": ("服务内容", "服务描述", "代理服务", "服务咨询", "需要信息"),
    "benefit": ("政策优惠", "支持措施", "奖励信息", "奖补", "补贴", "补助"),
    "eligibility": ("申报条件", "申报要求", "支持对象", "资格", "条件"),
    "materials": ("申报材料", "材料清单", "服务咨询", "需要信息", "资料"),
    "price": ("服务价格", "市场参考价格", "费用", "价格", "收费", "报价"),
    "process": ("服务流程", "申报流程", "办理流程", "流程", "步骤"),
}
POLICY_SUBJECT_STOP_TERMS = GENERIC_SEARCH_TERMS | {
    *POLICY_SERVICE_STOP_TERMS,
    "2020",
    "2021",
    "2022",
    "2023",
    "2024",
    "2025",
    "2026",
    "2027",
    "2028",
    "2029",
    "年度",
    "今年",
    "最新",
    "近期",
    "开展",
    "组织",
    "实施",
    "武汉",
    "湖北",
    "湖北省",
}
POLICY_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
POLICY_YEAR_RANGE_PATTERN = re.compile(r"((?:19|20)\d{2})\s*(?:[-—–－~至到]+)\s*((?:19|20)\d{2})")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
STRUCTURED_MARKDOWN_FIELD_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?([a-zA-Z0-9_\-㐀-䶿一-鿿（）()]{1,40})\s*[:：]\s*(.*?)\s*$",
    re.MULTILINE,
)
EXPIRED_METADATA_STATUSES = {
    "archived",
    "expired",
    "inactive",
    "invalid",
    "obsolete",
    "废止",
    "失效",
    "过期",
    "已废止",
    "已失效",
    "已过期",
}
EXPIRY_METADATA_KEYS = {
    "deadline",
    "enddate",
    "expireat",
    "expiresat",
    "expirydate",
    "invalidat",
    "validuntil",
    "截止",
    "截止日期",
    "失效日期",
    "有效期至",
    "结束时间",
    "结束日期",
    "endtime",
    "endat",
}
STATUS_METADATA_KEYS = {
    "status",
    "validstatus",
    "effectivestatus",
    "policy_status",
    "policystatus",
    "政策状态",
    "有效状态",
    "状态",
}
LEGAL_GENERIC_SEARCH_TERMS = GENERIC_SEARCH_TERMS | {
    "案件",
    "裁判",
    "法院",
    "法务",
    "法律",
    "法规",
    "法条",
    "合同",
    "纠纷",
    "解释",
    "诉讼",
    "司法",
    "司法解释",
    "条款",
    "违约",
    "协议",
    "义务",
    "责任",
    "仲裁",
}


# --- 文本规范化 ---

def normalized_search_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower().strip()


def normalize_metadata_key(value: str) -> str:
    return re.sub(r"[\s._-]+", "", unicodedata.normalize("NFKC", value).strip().lower().split(".")[-1])


# --- 查询分析 ---

def tokenize_search_query(value: str, max_terms: int = 24) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).lower().strip()
    terms: list[str] = []
    seen: set[str] = set()
    for token in jieba.cut_for_search(normalized, HMM=False):
        for match in SEARCH_TOKEN.findall(token):
            term = match.strip("._-")
            if not term or term in SEARCH_STOP_WORDS:
                continue
            if CJK_TOKEN.fullmatch(term) and len(term) < 2:
                continue
            if not CJK_TOKEN.fullmatch(term) and len(term) < 2 and not term.isdigit():
                continue
            if term not in seen:
                seen.add(term)
                terms.append(term)
            if len(terms) >= max_terms:
                return terms
    return terms


def extract_search_phrases(value: str, max_phrases: int = 8) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).lower().strip()
    for phrase in CONVERSATIONAL_PHRASES:
        normalized = normalized.replace(phrase, " ")
    phrases: list[str] = []
    seen: set[str] = set()
    for match in SEARCH_TOKEN.findall(normalized):
        candidate = match.strip("._-")
        if CJK_TOKEN.fullmatch(candidate) and len(candidate) >= 4 and candidate not in seen:
            seen.add(candidate)
            phrases.append(candidate)
        if len(phrases) >= max_phrases:
            break
    return phrases


def policy_service_intents(value: str) -> list[str]:
    intents: list[str] = []
    checks = (
        ("price", ("服务价格", "市场参考价格", "多少钱", "费用", "价格", "收费", "报价")),
        ("materials", ("申报材料", "材料清单", "需要信息", "需要什么", "准备什么", "材料", "资料", "清单")),
        ("process", ("服务流程", "办理流程", "申报流程", "怎么申报", "如何申报", "流程", "步骤", "办理", "代办")),
        ("eligibility", ("申报条件", "申报要求", "资格", "对象", "条件", "门槛")),
        ("benefit", ("政策优惠", "支持措施", "奖励", "补贴", "补助", "奖补", "优惠")),
        ("agency", ("代办", "办理", "代理", "服务咨询", "服务内容", "服务价格", "市场参考价格")),
    )
    for intent, markers in checks:
        if any(marker in value for marker in markers):
            intents.append(intent)
    return intents


def extract_markdown_headings(value: str) -> list[str]:
    headings: list[str] = []
    for heading in MARKDOWN_HEADING_PATTERN.findall(value):
        normalized = normalized_search_text(heading.strip(" #\t"))
        if normalized:
            headings.append(normalized)
    return headings


def markdown_structured_fields(value: str, max_chars: int = 5000) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, field_value in STRUCTURED_MARKDOWN_FIELD_PATTERN.findall(value[:max_chars]):
        normalized_key = normalize_metadata_key(key)
        normalized_value = unicodedata.normalize("NFKC", field_value).strip()
        if normalized_key and normalized_value and normalized_key not in fields:
            fields[normalized_key] = normalized_value
    return fields


def analyze_search_intent(value: str, profile: str = "policy") -> dict[str, Any]:
    normalized = unicodedata.normalize("NFKC", value).lower().strip()
    profile_kind = "policy"
    terms = tokenize_search_query(normalized)
    phrases = extract_search_phrases(normalized)
    years = list(dict.fromkeys(re.findall(r"(?:19|20)\d{2}", normalized)))
    service_intents = policy_service_intents(normalized)
    if any(marker in normalized for marker in ("截止", "时间", "日期", "什么时候")):
        intent = "deadline"
    elif any(marker in normalized for marker in ("条件", "资格", "对象", "谁能", "申报要求")):
        intent = "eligibility"
    elif any(marker in normalized for marker in ("流程", "材料", "办理", "怎么", "如何", "验收")):
        intent = "procedure"
    elif any(marker in normalized for marker in ("政策", "通知", "项目", "规定", "办法")):
        intent = "policy_lookup"
    else:
        intent = "general"
    return {
        "profile": profile,
        "profileKind": profile_kind,
        "intent": intent,
        "terms": terms,
        "focusTerms": [term for term in terms if term not in GENERIC_SEARCH_TERMS],
        "phrases": phrases,
        "years": years,
        "policyFreshnessSensitive": bool(
            profile_kind == "policy"
            and any(marker in normalized for marker in POLICY_FRESHNESS_MARKERS)
            and (bool(years) or any(marker in normalized for marker in POLICY_RECENCY_MARKERS))
        ),
        "serviceIntents": service_intents if profile_kind == "policy" else [],
        "serviceQuery": bool(profile_kind == "policy" and service_intents),
    }


# --- 评分与过滤 ---

def keyword_match_score(
    terms: list[str],
    phrases: list[str],
    title: str,
    content: str,
    source_ref: str | None = None,
    query_analysis: dict[str, Any] | None = None,
) -> float:
    normalized_title = normalized_search_text(title)
    normalized_content = normalized_search_text(content)
    normalized_source_ref = normalized_search_text(source_ref or "")
    structured_fields = markdown_structured_fields(content)
    structured_text = normalized_search_text("\n".join(structured_fields.values()))
    heading_text = "\n".join(extract_markdown_headings(content))
    matched_terms = 0
    score = 0.0
    for term in terms:
        title_match = term in normalized_title
        content_count = normalized_content.count(term)
        source_match = bool(normalized_source_ref and term in normalized_source_ref)
        structured_match = bool(structured_text and term in structured_text)
        heading_match = bool(heading_text and term in heading_text)
        if title_match or content_count or source_match or structured_match or heading_match:
            matched_terms += 1
        if title_match:
            score += 12.0
        if source_match:
            score += 8.0
        if structured_match:
            score += 6.0
        if heading_match:
            score += 4.0
        if content_count:
            score += 3.0 + min(content_count - 1, 2) * 0.5
    if terms:
        score += 20.0 * matched_terms / len(terms)
    for phrase in phrases:
        if phrase in normalized_title:
            score += 120.0
        elif normalized_source_ref and phrase in normalized_source_ref:
            score += 90.0
        elif phrase in normalized_content:
            score += 80.0
        elif structured_text and phrase in structured_text:
            score += 55.0
        elif heading_text and phrase in heading_text:
            score += 35.0
    if query_analysis and query_analysis.get("serviceQuery") is True:
        if policy_service_section_matches(query_analysis.get("serviceIntents") or [], content):
            score += 30.0
    return score


def policy_service_section_matches(service_intents: list[str], content: str) -> bool:
    if not service_intents:
        return False
    searchable = normalized_search_text("\n".join(extract_markdown_headings(content)) + "\n" + content[:2000])
    for intent in service_intents:
        if any(marker in searchable for marker in POLICY_SERVICE_SECTION_MARKERS.get(str(intent), ())):
            return True
    return False


def terms_match_within_window(
    terms: list[str], text: str, required_matches: int, window_chars: int
) -> bool:
    occurrences: list[tuple[int, str]] = []
    for term in terms:
        start = 0
        for _ in range(50):
            position = text.find(term, start)
            if position < 0:
                break
            occurrences.append((position, term))
            start = position + max(1, len(term))
    occurrences.sort()
    counts: dict[str, int] = {}
    left = 0
    for right, (position, term) in enumerate(occurrences):
        counts[term] = counts.get(term, 0) + 1
        while position - occurrences[left][0] > window_chars:
            left_term = occurrences[left][1]
            counts[left_term] -= 1
            if counts[left_term] == 0:
                del counts[left_term]
            left += 1
        if len(counts) >= required_matches:
            return True
    return False


def is_effective_keyword_match(
    focus_terms: list[str], phrases: list[str], title: str, content: str, source_ref: str | None = None
) -> bool:
    """拒绝只命中「政策/企业/通知」等泛词的候选。"""
    normalized_title = normalized_search_text(title)
    normalized_source_ref = normalized_search_text(source_ref or "")
    normalized_anchor = f"{normalized_title}\n{normalized_source_ref}"
    normalized_content = normalized_search_text(content)
    normalized_searchable = f"{normalized_anchor}\n{normalized_content}"
    if not focus_terms:
        return False
    required_matches = 1 if len(focus_terms) == 1 else math.ceil(len(focus_terms) * 0.6)
    anchored_phrases = [
        phrase
        for phrase in phrases
        if sum(term in phrase for term in focus_terms) >= required_matches
    ]
    if any(phrase in normalized_anchor or phrase in normalized_content for phrase in anchored_phrases):
        return True
    if sum(term in normalized_anchor for term in focus_terms) >= required_matches:
        return True
    return terms_match_within_window(focus_terms, normalized_searchable, required_matches, window_chars=500)


# --- 规则重排 ---

def policy_subject_terms(query_analysis: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_analysis.get("focusTerms") or []:
        normalized = str(term).strip().lower()
        if not normalized or normalized in POLICY_SUBJECT_STOP_TERMS or POLICY_YEAR_PATTERN.fullmatch(normalized):
            continue
        if normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    return terms


def policy_title_subject_multiplier(query_analysis: dict[str, Any], title: str) -> float:
    subject_terms = policy_subject_terms(query_analysis)
    if not subject_terms:
        return 1.0
    normalized_title = unicodedata.normalize("NFKC", title).lower()
    matched_terms = sum(term in normalized_title for term in subject_terms)
    required_matches = 1 if len(subject_terms) == 1 else math.ceil(len(subject_terms) * 0.6)
    return 1.0 if matched_terms >= required_matches else 0.35


def policy_match_quality(reasons: list[str]) -> str:
    if any(reason.startswith("expired") for reason in reasons):
        return "EXPIRED"
    if "year_mismatch" in reasons:
        return "STALE"
    if reasons:
        return "WEAK"
    return "STRONG"


def flattened_policy_text(values: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(values, dict):
        for value in values.values():
            texts.extend(flattened_policy_text(value))
    elif isinstance(values, (list, tuple, set)):
        for value in values:
            texts.extend(flattened_policy_text(value))
    elif values is not None:
        text = unicodedata.normalize("NFKC", str(values)).lower().strip()
        if text:
            texts.append(text)
    return texts


def flattened_metadata_items(values: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(values, dict):
        for key, value in values.items():
            key_text = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                items.extend(flattened_metadata_items(value, key_text))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    items.extend(flattened_metadata_items(item, f"{key_text}.{index}"))
            else:
                items.append((key_text, value))
    elif isinstance(values, (list, tuple, set)):
        for value in values:
            items.extend(flattened_metadata_items(value, prefix))
    return items


def parse_policy_date(value: Any) -> datetime | None:
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return None
    match = re.search(r"((?:19|20)\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


def metadata_indicates_expired(*metadata_values: dict[str, Any], now: datetime | None = None) -> bool:
    reference_time = now or datetime.now(timezone.utc)
    for key, value in flattened_metadata_items(metadata_values):
        normalized_key = normalize_metadata_key(key)
        normalized_value = unicodedata.normalize("NFKC", str(value)).strip().lower()
        if normalized_key in STATUS_METADATA_KEYS and normalized_value in EXPIRED_METADATA_STATUSES:
            return True
        if normalized_key in EXPIRY_METADATA_KEYS:
            expires_at = parse_policy_date(value)
            if expires_at is not None and expires_at < reference_time:
                return True
    return False


def structured_policy_indicates_expired(fields: dict[str, str], now: datetime | None = None) -> bool:
    if metadata_indicates_expired(fields, now=now):
        return True
    status_value = normalized_search_text(fields.get("状态") or fields.get("status") or "")
    policy_field_keys = {"生效时间", "结束时间", "政策级别", "归属部门", "政策来源", "政策类别"}
    return status_value == "1" and bool(policy_field_keys.intersection(fields))


def extract_policy_years(*values: Any) -> set[str]:
    years: set[str] = set()
    for text in flattened_policy_text(values):
        for start, end in POLICY_YEAR_RANGE_PATTERN.findall(text):
            start_year = int(start)
            end_year = int(end)
            if start_year <= end_year and end_year - start_year <= 10:
                years.update(str(year) for year in range(start_year, end_year + 1))
        years.update(POLICY_YEAR_PATTERN.findall(text))
    return years


def policy_service_context_multiplier(
    query_analysis: dict[str, Any],
    title: str,
    content: str,
    source_ref: str | None = None,
) -> tuple[float, list[str], list[str]]:
    normalized_title = normalized_search_text(title)
    normalized_content = normalized_search_text(content)
    normalized_source_ref = normalized_search_text(source_ref or "")
    heading_text = "\n".join(extract_markdown_headings(content))
    context_text = f"{normalized_source_ref}\n{normalized_title}\n{heading_text}\n{normalized_content[:2000]}"
    if not any(marker in context_text for marker in POLICY_SERVICE_CONTEXT_MARKERS):
        return 1.0, [], []
    service_intents = [str(intent) for intent in query_analysis.get("serviceIntents") or []]
    if not service_intents:
        if query_analysis.get("policyFreshnessSensitive") is True:
            return 0.55, ["service_guide_for_live_policy"], []
        return 1.0, [], []
    multiplier = 1.0
    boosts: list[str] = []
    if any(marker in normalized_source_ref for marker in ("政策代办类知识库", "政策申报", "资质办理", "知识产权")):
        multiplier *= 1.25
        boosts.append("service_path_match")
    subject_terms = policy_subject_terms(query_analysis)
    if subject_terms:
        subject_context = f"{normalized_title}\n{normalized_source_ref}"
        required_matches = 1 if len(subject_terms) == 1 else math.ceil(len(subject_terms) * 0.6)
        if sum(term in subject_context for term in subject_terms) >= required_matches:
            multiplier *= 1.2
            boosts.append("service_subject_anchor")
    if policy_service_section_matches(service_intents, content):
        multiplier *= 1.25
        boosts.append("service_section_match")
    if "agency" in service_intents and any(
        marker in context_text
        for marker in ("服务价格", "服务咨询", "服务流程", "服务内容", "市场参考价格", "代理服务")
    ):
        multiplier *= 1.1
        boosts.append("service_content_match")
    return min(multiplier, 1.8), [], boosts


def policy_relevance_adjustment(
    query_analysis: dict[str, Any],
    title: str,
    content: str,
    document_metadata: dict[str, Any] | None = None,
    chunk_metadata: dict[str, Any] | None = None,
    source_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    multiplier = 1.0
    reasons: list[str] = []
    boosts: list[str] = []
    query_years = {str(year) for year in query_analysis.get("years") or []}
    structured_fields = markdown_structured_fields(content)
    metadata_values = [document_metadata or {}, chunk_metadata or {}]
    candidate_years = extract_policy_years(title, source_ref or "", structured_fields, *metadata_values)
    if query_years:
        if candidate_years and not query_years.intersection(candidate_years):
            multiplier *= 0.2
            reasons.append("year_mismatch")
        elif not candidate_years and query_analysis.get("policyFreshnessSensitive") is True:
            multiplier *= 0.7
            reasons.append("missing_year_signal")
    if query_analysis.get("policyFreshnessSensitive") is True:
        title_multiplier = policy_title_subject_multiplier(query_analysis, title)
        if title_multiplier < 1.0:
            multiplier *= title_multiplier
            reasons.append("weak_title_subject_match")
    if metadata_indicates_expired(*metadata_values, now=now):
        multiplier *= 0.2
        reasons.append("expired_metadata")
    elif structured_fields and structured_policy_indicates_expired(structured_fields, now=now):
        multiplier *= 0.2
        reasons.append("expired_structured_policy")
    service_multiplier, service_reasons, service_boosts = policy_service_context_multiplier(
        query_analysis,
        title,
        content,
        source_ref,
    )
    if service_multiplier != 1.0:
        multiplier *= service_multiplier
    reasons.extend(service_reasons)
    boosts.extend(service_boosts)
    return {
        "multiplier": multiplier,
        "quality": policy_match_quality(reasons),
        "reasons": reasons,
        "boosts": boosts,
        "candidateYears": sorted(candidate_years),
    }


def generic_relevance_adjustment(
    document_metadata: dict[str, Any] | None = None,
    chunk_metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    multiplier = 1.0
    if metadata_indicates_expired(document_metadata or {}, chunk_metadata or {}, now=now):
        multiplier *= 0.2
        reasons.append("expired_metadata")
    return {
        "multiplier": multiplier,
        "quality": "EXPIRED" if reasons else "STRONG",
        "reasons": reasons,
        "candidateYears": [],
    }


# --- 检索策略 ---

class KeywordRankSearchStrategy:
    """关键词评分 + 规则重排检索策略（忠实移植参考项目 agent-paas/knowledge-service）。

    流程：jieba 分词 → ILIKE 粗筛（≤500 chunk）→ 焦点词硬过滤 → 位置加权评分
    → policy 规则重排 → 排序。不调用 embedding API。

    score 已用 sigmoid（scale=100）归一化到 0~1，便于与其他策略统一 min_score 过滤
    与兜底阈值判定；rawScore 透传未归一化、未乘规则 multiplier 的原始位置加权分。
    """

    name = "keyword_rank"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        query_analysis = analyze_search_intent(ctx.query, "policy")
        terms = query_analysis["terms"]
        if not terms:
            return []
        phrases = query_analysis["phrases"]
        focus_terms = query_analysis["focusTerms"]

        # 忠实参考项目：粗筛用全部 terms（含泛词）做 ILIKE，裸 limit(500)。
        like_conditions = []
        for term in terms:
            pattern = f"%{term}%"
            like_conditions.extend(
                [
                    KnowledgeChunk.content_text.ilike(pattern),
                    KnowledgeDocument.title.ilike(pattern),
                    KnowledgeDocument.source_ref.ilike(pattern),
                ]
            )

        conditions = _base_conditions(ctx) + [or_(*like_conditions)]
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
            .where(*conditions)
            .limit(500)
        )
        rows = (await session.execute(statement)).all()

        scored: List[tuple[float, float, RecallEntry]] = []
        for chunk, document, kb in rows:
            if not metadata_matches(ctx.metadata_filter, document.metadata_json or {}, chunk.metadata_json or {}):
                continue
            title = document.title or ""
            content = chunk.content_text or ""
            if not is_effective_keyword_match(focus_terms, phrases, title, content, document.source_ref):
                continue
            raw_score = keyword_match_score(terms, phrases, title, content, document.source_ref, query_analysis)
            adjustment = policy_relevance_adjustment(
                query_analysis,
                title,
                content,
                document.metadata_json or {},
                chunk.metadata_json or {},
                document.source_ref,
            )
            final = raw_score * float(adjustment["multiplier"])
            normalized = normalize_score(final, scale=100.0)
            if final > 0 and normalized >= ctx.min_score:
                scored.append((normalized, raw_score, (chunk, document, kb, None, normalized)))

        scored.sort(key=lambda item: item[0], reverse=True)

        items: List[SearchHit] = []
        for _normalized, raw_score, entry in scored[: ctx.top_k]:
            hit = _hit_to_dict(entry)
            hit["rawScore"] = round(raw_score, 6)
            items.append(hit)

        reranked = await _maybe_rerank(ctx, items)
        return reranked[: ctx.top_k]
