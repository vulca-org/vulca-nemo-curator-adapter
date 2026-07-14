from __future__ import annotations

from typing import Any

from vulca_curator_adapter.schemas import CuratorSignal


def _required_text(record: dict[str, Any], key: str, error_message: str) -> str:
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(error_message)


def _mapping(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return value if isinstance(value, dict) else {}


def parse_source_gate_record(record: dict[str, Any]) -> CuratorSignal:
    case_id = _required_text(record, "case_id", "VULCA source-gate record missing case_id")
    source = _mapping(record, "source")
    source_context = _mapping(record, "source_context")
    human_review = _mapping(record, "human_review")
    suggested_review = _mapping(record, "suggested_review")
    audit = _mapping(record, "audit")

    source_dependency = human_review.get("source_dependency") or suggested_review.get("source_dependency")
    decision_basis = human_review.get("decision_basis") or suggested_review.get("decision_basis")
    review_priority = suggested_review.get("review_priority")
    source_context_available = bool(source_context.get("available"))
    source_image_available = bool(source_context.get("source_image_available"))
    source_case_type = record.get("source_case_type")
    candidate_reason = audit.get("candidate_reason")

    caption_parts = ["VULCA source-gate review case"]
    if source_case_type:
        caption_parts.append(f"for {source_case_type}")
    if source_dependency:
        caption_parts.append(f"with source_dependency={source_dependency}")
    if decision_basis:
        caption_parts.append(f"and decision_basis={decision_basis}")

    return CuratorSignal.model_validate(
        {
            "asset_id": case_id,
            "uri": f"vulca-source-gate://{case_id}",
            "modality": "case",
            "caption": " ".join(caption_parts) + ".",
            "curator_stage": "vulca_source_gate",
            "review_context": {
                "source_dependency": source_dependency,
                "decision_basis": decision_basis,
                "privacy_scope": source.get("privacy_scope"),
                "source_context_available": source_context_available,
                "source_image_available": source_image_available,
                "review_priority": review_priority,
                "source_case_type": source_case_type,
                "source_id": source.get("source_id"),
                "curation_status": source.get("curation_status"),
                "candidate_reason": candidate_reason,
            },
            "curator_metadata": {
                "case_type": record.get("case_type"),
                "schema_version": record.get("schema_version"),
            },
        }
    )
