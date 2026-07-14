from __future__ import annotations

import ast
import json
from numbers import Real
from typing import Optional

from vulca_curator_adapter.schemas import CuratorSignal


ADAPTER_CONTRACT = "nemo.image_writer.parquet.source-first.v1"
UPSTREAM_REPOSITORY = "https://github.com/NVIDIA-NeMo/Curator"
UPSTREAM_COMMIT = "15cc645cbf9e9314fed9e11fc89f6535ea9a8820"
REQUIRED_COLUMNS = frozenset(
    {"image_id", "tar_file", "member_name", "original_path", "metadata"}
)
METADATA_PARSE_LIMIT_BYTES = 10 * 1024
LARGE_SEQUENCE_THRESHOLD = 256
COMPACTION_MAX_DEPTH = 8

_CONSUMED_COLUMNS = REQUIRED_COLUMNS | {"aesthetic_score", "nsfw_score"}
_PARSING_ERRORS = (ValueError, SyntaxError, MemoryError, RecursionError)
_JSON_ERRORS = (TypeError, ValueError, OverflowError, MemoryError, RecursionError)


def _omitted_value(value: object) -> dict[str, object]:
    return {"omitted": True, "type": type(value).__name__}


def _compact_json_value(
    value: object,
    *,
    depth: int = 0,
    active_container_ids: frozenset[int] = frozenset(),
) -> object:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"omitted": True, "type": "binary", "length": len(value)}
    if isinstance(value, (list, tuple)) and len(value) > LARGE_SEQUENCE_THRESHOLD:
        return {
            "omitted": True,
            "type": type(value).__name__,
            "length": len(value),
        }

    if isinstance(value, (dict, list, tuple)):
        if depth >= COMPACTION_MAX_DEPTH or id(value) in active_container_ids:
            return _omitted_value(value)
        descendants = active_container_ids | {id(value)}
        if isinstance(value, dict):
            compacted: object = {
                key: _compact_json_value(
                    item,
                    depth=depth + 1,
                    active_container_ids=descendants,
                )
                for key, item in value.items()
            }
        else:
            items = [
                _compact_json_value(
                    item,
                    depth=depth + 1,
                    active_container_ids=descendants,
                )
                for item in value
            ]
            compacted = tuple(items) if isinstance(value, tuple) else items
        try:
            json.dumps(compacted, ensure_ascii=False, allow_nan=False)
        except _JSON_ERRORS:
            return _omitted_value(value)
        return compacted

    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except _JSON_ERRORS:
        return _omitted_value(value)
    return value


def _json_safe_string_mapping(value: object) -> bool:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return False
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except _JSON_ERRORS:
        return False
    return True


def _parse_metadata(value: object) -> tuple[Optional[dict[str, object]], str]:
    if value is None or value == "":
        return None, "empty"
    if isinstance(value, dict):
        if _json_safe_string_mapping(value):
            return value, "parsed"
        return None, "not_mapping"
    if not isinstance(value, str):
        return None, "not_mapping"
    if len(value.encode("utf-8")) > METADATA_PARSE_LIMIT_BYTES:
        return None, "oversize"

    try:
        parsed = json.loads(value)
    except _PARSING_ERRORS:
        try:
            parsed = ast.literal_eval(value)
        except _PARSING_ERRORS:
            return None, "unparsed"

    if _json_safe_string_mapping(parsed):
        return parsed, "parsed"
    return None, "not_mapping"


def _metadata_alias(metadata: Optional[dict[str, object]], aliases: tuple[str, ...]) -> Optional[str]:
    if metadata is None:
        return None
    for alias in aliases:
        value = metadata.get(alias)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _required_text(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_score(record: dict[str, object], field: str) -> object:
    value = record.get(field)
    if value is not None and (isinstance(value, bool) or not isinstance(value, Real)):
        raise ValueError(f"{field} must be a real number or null")
    return value


def parse_nemo_image_writer_record(
    record: dict[str, object], *, sidecar: str, row_number: int
) -> CuratorSignal:
    image_id = _required_text(record, "image_id")
    tar_file = _required_text(record, "tar_file")
    member_name = _required_text(record, "member_name")

    original_path = record.get("original_path")
    if original_path is not None and not isinstance(original_path, str):
        raise ValueError("original_path must be a string or null")

    aesthetic_score = _optional_score(record, "aesthetic_score")
    nsfw_score = _optional_score(record, "nsfw_score")
    raw_metadata = record.get("metadata")
    parsed_metadata, parse_status = _parse_metadata(raw_metadata)
    curator_metadata: dict[str, object] = {
        "adapter_contract": ADAPTER_CONTRACT,
        "original_path": original_path,
        "nemo_metadata_raw": _compact_json_value(raw_metadata),
        "metadata_parse_status": parse_status,
        "parquet_provenance": {"sidecar": sidecar, "row_number": row_number},
        "upstream_columns": {
            key: _compact_json_value(value)
            for key, value in record.items()
            if key not in _CONSUMED_COLUMNS
        },
    }
    if parsed_metadata is not None:
        curator_metadata["nemo_metadata"] = _compact_json_value(parsed_metadata)

    return CuratorSignal.model_validate(
        {
            "asset_id": image_id,
            "uri": f"{tar_file}#{member_name}",
            "modality": "image",
            "source_url": _metadata_alias(parsed_metadata, ("source_url", "url")),
            "caption": _metadata_alias(parsed_metadata, ("caption", "text")),
            "aesthetic_score": aesthetic_score,
            "nsfw_score": nsfw_score,
            "curator_stage": "nemo_image_writer_parquet",
            "curator_metadata": curator_metadata,
        }
    )
