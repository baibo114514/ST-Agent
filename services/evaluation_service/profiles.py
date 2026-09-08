"""Namespace-aware evaluation profile helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

NAMESPACE_LABEL_ALIASES: Final[dict[str, str]] = {
    "policy": "policy",
    "policies": "policy",
    "service": "service",
    "customer_service": "service",
}


@dataclass(frozen=True, slots=True)
class EvaluationProfile:
    """Evaluation behavior for a namespace of knowledge bases."""

    name: str
    namespace: str
    positive_hit_mode: str = "hit_at_k"
    apply_policy_gates: bool = True


POLICY_PROFILE = EvaluationProfile(name="policy", namespace="policy")
SERVICE_PROFILE = EvaluationProfile(
    name="service",
    namespace="service",
    positive_hit_mode="hit_at_1",
    apply_policy_gates=False,
)

PROFILE_REGISTRY: Final[dict[str, EvaluationProfile]] = {
    POLICY_PROFILE.namespace: POLICY_PROFILE,
    SERVICE_PROFILE.namespace: SERVICE_PROFILE,
}


def normalize_namespace_label(value: str | None) -> str | None:
    """Normalize user-facing namespace labels and common aliases."""
    if value is None:
        return None
    namespace = str(value).strip().lower().replace("-", "_")
    if not namespace:
        return None
    return NAMESPACE_LABEL_ALIASES.get(namespace, namespace)


def knowledge_namespace(namespace: str | None) -> str:
    """Map a user-facing namespace to the knowledge-service namespace."""
    label = normalize_namespace_label(namespace) or "policy"
    if label == "service":
        return "customer_service"
    if label == "policy":
        return "policy"
    return label


def infer_namespace_label_from_path(path: Path) -> str:
    """Infer namespace from a cases file path when config does not specify one."""
    parts = {part.lower() for part in path.parts}
    if "customer_service" in parts:
        return "service"
    return "policy"


def resolve_profile(namespace: str | None) -> EvaluationProfile:
    """Resolve the evaluation profile for a namespace."""
    label = normalize_namespace_label(namespace) or "policy"
    if label in PROFILE_REGISTRY:
        return PROFILE_REGISTRY[label]
    return EvaluationProfile(name=label, namespace=label, positive_hit_mode="hit_at_k", apply_policy_gates=False)
