from __future__ import annotations

from typing import Optional

from vulca_curator_adapter.schemas import CuratorSignal


def _consume_required_text(record: dict, keys: tuple[str, ...], error_message: str) -> tuple[str, str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value, key
    raise ValueError(error_message)


def _consume_optional(record: dict, keys: tuple[str, ...]) -> tuple[object, Optional[str]]:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value, key
    return None, None


def parse_nemo_record(record: dict) -> CuratorSignal:
    asset_id, asset_id_key = _consume_required_text(
        record,
        ("asset_id", "id", "image_id"),
        "NeMo record missing asset identifier",
    )
    uri, uri_key = _consume_required_text(
        record,
        ("uri", "image_path", "path"),
        "NeMo record missing uri",
    )
    source_url, source_url_key = _consume_optional(record, ("source_url", "url"))
    caption, caption_key = _consume_optional(record, ("caption", "text"))
    duplicate_group, duplicate_group_key = _consume_optional(
        record, ("duplicate_group", "dedupe_cluster")
    )
    embedding_ref, embedding_ref_key = _consume_optional(record, ("embedding_ref", "embedding_path"))
    consumed_keys = {
        asset_id_key,
        uri_key,
        source_url_key,
        caption_key,
        duplicate_group_key,
        embedding_ref_key,
        "aesthetic_score",
        "nsfw_score",
    }
    mapped = {
        "asset_id": asset_id,
        "uri": uri,
        "modality": "image",
        "source_url": source_url,
        "caption": caption,
        "aesthetic_score": record.get("aesthetic_score"),
        "nsfw_score": record.get("nsfw_score"),
        "duplicate_group": duplicate_group,
        "embedding_ref": embedding_ref,
        "curator_stage": "nemo_image",
        "curator_metadata": {
            key: value
            for key, value in record.items()
            if key not in consumed_keys
        },
    }
    return CuratorSignal.model_validate(mapped)
