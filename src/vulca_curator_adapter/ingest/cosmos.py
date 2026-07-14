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


def parse_cosmos_record(record: dict) -> CuratorSignal:
    clip_id, clip_id_key = _consume_required_text(
        record,
        ("clip_id", "video_id", "asset_id"),
        "Cosmos record missing clip identifier",
    )
    uri, uri_key = _consume_required_text(
        record,
        ("frame_uri", "uri", "clip_uri"),
        "Cosmos record missing uri",
    )
    timestamp = record.get("timestamp_sec")
    asset_id = f"{clip_id}:{timestamp}" if timestamp is not None else clip_id
    source_url, source_url_key = _consume_optional(record, ("source_url", "clip_uri"))
    caption, caption_key = _consume_optional(record, ("caption", "summary"))
    duplicate_group, duplicate_group_key = _consume_optional(
        record, ("duplicate_group", "semantic_cluster")
    )
    consumed_keys = {
        clip_id_key,
        uri_key,
        source_url_key,
        caption_key,
        duplicate_group_key,
        "aesthetic_score",
        "nsfw_score",
        "embedding_ref",
    }
    mapped = {
        "asset_id": asset_id,
        "uri": uri,
        "modality": "frame" if uri_key == "frame_uri" else "video",
        "source_url": source_url,
        "caption": caption,
        "aesthetic_score": record.get("aesthetic_score"),
        "nsfw_score": record.get("nsfw_score"),
        "duplicate_group": duplicate_group,
        "embedding_ref": record.get("embedding_ref"),
        "curator_stage": "cosmos_frame" if uri_key == "frame_uri" else "cosmos_video",
        "curator_metadata": {
            key: value
            for key, value in record.items()
            if key not in consumed_keys
        },
    }
    return CuratorSignal.model_validate(mapped)
