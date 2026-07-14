from __future__ import annotations

from pathlib import Path
from typing import Any

from vulca_curator_adapter.schemas import CuratorSignal


def _required_text(record: dict[str, Any], key: str, error_message: str) -> str:
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(error_message)


def _optional_int(record: dict[str, Any], key: str) -> int | None:
    value = record.get(key)
    return value if isinstance(value, int) else None


def parse_visual_evidence_record(record: dict[str, Any]) -> CuratorSignal:
    slug = _required_text(record, "slug", "VULCA visual evidence record missing slug")
    image_path = _required_text(
        record,
        "image_path",
        "VULCA visual evidence record missing image_path",
    )
    risk_bucket = _required_text(
        record,
        "risk_bucket",
        "VULCA visual evidence record missing risk_bucket",
    )
    external_use_status = record.get("external_use_status") or "external_review_blocked"
    domain = record.get("domain")
    notes = record.get("notes")
    entities_count = _optional_int(record, "entities_count")
    threshold_hint = record.get("threshold_hint")

    caption_parts = [f"VULCA visual evidence for {slug}."]
    if domain:
        caption_parts.append(f"Domain: {domain}.")
    if risk_bucket:
        caption_parts.append(f"Risk bucket: {risk_bucket}.")
    if notes:
        caption_parts.append(str(notes))

    return CuratorSignal.model_validate(
        {
            "asset_id": slug,
            "uri": image_path,
            "modality": "image",
            "caption": " ".join(caption_parts),
            "source_url": None,
            "curator_stage": "vulca_visual_evidence",
            "review_context": {
                "risk_bucket": risk_bucket,
                "domain": domain,
                "source_image_path": str(Path(image_path)),
                "image_exists": Path(image_path).exists(),
                "entities_count": entities_count,
                "threshold_hint": threshold_hint,
                "external_use_status": external_use_status,
            },
            "curator_metadata": {
                "risk_bucket": risk_bucket,
                "domain": domain,
                "external_use_status": external_use_status,
            },
        }
    )
