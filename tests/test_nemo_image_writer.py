import ast
import math

import pytest
from pydantic import ValidationError

from vulca_curator_adapter.ingest import nemo_image_writer
from vulca_curator_adapter.ingest.nemo_image_writer import (
    ADAPTER_CONTRACT,
    parse_nemo_image_writer_record,
)


def image_writer_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "image_id": "image-0001",
        "tar_file": "shards/images-00000.tar",
        "member_name": "image-0001.jpg",
        "original_path": "/source/image-0001.jpg",
        "metadata": (
            "{'source_url': 'https://example.com/image-0001', "
            "'caption': 'A red chair'}"
        ),
    }
    record.update(overrides)
    return record


def test_exact_pinned_row_maps_source_first_signal_and_provenance() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(),
        sidecar="exports/images-00000.parquet",
        row_number=1,
    )

    assert signal.asset_id == "image-0001"
    assert signal.uri == "shards/images-00000.tar#image-0001.jpg"
    assert signal.modality == "image"
    assert signal.source_url == "https://example.com/image-0001"
    assert signal.caption == "A red chair"
    assert signal.aesthetic_score is None
    assert signal.nsfw_score is None
    assert signal.curator_stage == "nemo_image_writer_parquet"
    assert signal.curator_metadata == {
        "adapter_contract": ADAPTER_CONTRACT,
        "original_path": "/source/image-0001.jpg",
        "nemo_metadata_raw": (
            "{'source_url': 'https://example.com/image-0001', "
            "'caption': 'A red chair'}"
        ),
        "metadata_parse_status": "parsed",
        "parquet_provenance": {
            "sidecar": "exports/images-00000.parquet",
            "row_number": 1,
        },
        "upstream_columns": {},
        "nemo_metadata": {
            "source_url": "https://example.com/image-0001",
            "caption": "A red chair",
        },
    }


def test_optional_documented_scores_map() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(aesthetic_score=0.83, nsfw_score=0.02),
        sidecar="images.parquet",
        row_number=2,
    )

    assert signal.aesthetic_score == 0.83
    assert signal.nsfw_score == 0.02


@pytest.mark.parametrize("field", ["aesthetic_score", "nsfw_score"])
@pytest.mark.parametrize("invalid_value", ["0.5", True])
def test_scores_reject_coercible_non_numeric_values(
    field: str, invalid_value: object
) -> None:
    with pytest.raises(ValueError, match=rf"^{field} must be a real number or null$"):
        parse_nemo_image_writer_record(
            image_writer_record(**{field: invalid_value}),
            sidecar="images.parquet",
            row_number=2,
        )


@pytest.mark.parametrize(
    ("field", "valid_value"),
    [
        ("aesthetic_score", 0),
        ("aesthetic_score", None),
        ("nsfw_score", 1.0),
        ("nsfw_score", None),
    ],
)
def test_scores_accept_real_numbers_and_null(field: str, valid_value: object) -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(**{field: valid_value}),
        sidecar="images.parquet",
        row_number=2,
    )

    assert getattr(signal, field) == valid_value


def test_oversized_metadata_remains_raw_without_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_metadata = "x" * (nemo_image_writer.METADATA_PARSE_LIMIT_BYTES + 1)

    def fail_literal_parse(value: object) -> object:
        raise AssertionError(f"literal parser should not receive {type(value).__name__}")

    monkeypatch.setattr(ast, "literal_eval", fail_literal_parse)

    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=raw_metadata),
        sidecar="images.parquet",
        row_number=3,
    )

    assert signal.curator_metadata["nemo_metadata_raw"] == raw_metadata
    assert signal.curator_metadata["metadata_parse_status"] == "oversize"
    assert "nemo_metadata" not in signal.curator_metadata


def test_large_embedding_is_summarized_in_upstream_columns() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(embedding=list(range(2048))),
        sidecar="images.parquet",
        row_number=4,
    )

    assert signal.curator_metadata["upstream_columns"]["embedding"] == {
        "omitted": True,
        "type": "list",
        "length": 2048,
    }


def test_nested_large_embedding_is_summarized_in_upstream_columns() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(
            extension={"payload": {"embedding": [0.0] * 1000}}
        ),
        sidecar="images.parquet",
        row_number=4,
    )

    assert signal.curator_metadata["upstream_columns"]["extension"] == {
        "payload": {
            "embedding": {
                "omitted": True,
                "type": "list",
                "length": 1000,
            }
        }
    }


def test_ordinary_nested_upstream_data_is_preserved() -> None:
    extension = {
        "payload": {
            "dimensions": [640, 480],
            "enabled": True,
            "label": "thumbnail",
        }
    }

    signal = parse_nemo_image_writer_record(
        image_writer_record(extension=extension),
        sidecar="images.parquet",
        row_number=4,
    )

    assert signal.curator_metadata["upstream_columns"]["extension"] == extension


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_compacted_in_raw_and_upstream_data(
    non_finite: float,
) -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(
            metadata={"quality": non_finite},
            extension={"payload": {"quality": non_finite}},
        ),
        sidecar="images.parquet",
        row_number=4,
    )

    omitted_float = {"omitted": True, "type": "float"}
    assert signal.curator_metadata["nemo_metadata_raw"] == {
        "quality": omitted_float
    }
    assert signal.curator_metadata["metadata_parse_status"] == "not_mapping"
    assert "nemo_metadata" not in signal.curator_metadata
    assert signal.curator_metadata["upstream_columns"]["extension"] == {
        "payload": {"quality": omitted_float}
    }


def test_recursive_compaction_breaks_cycles_deterministically() -> None:
    extension: dict[str, object] = {}
    extension["self"] = extension

    signal = parse_nemo_image_writer_record(
        image_writer_record(extension=extension),
        sidecar="images.parquet",
        row_number=4,
    )

    assert signal.curator_metadata["upstream_columns"]["extension"] == {
        "self": {"omitted": True, "type": "dict"}
    }


def test_recursive_compaction_stops_at_depth_limit() -> None:
    extension: object = "leaf"
    for _ in range(nemo_image_writer.COMPACTION_MAX_DEPTH + 1):
        extension = {"next": extension}

    signal = parse_nemo_image_writer_record(
        image_writer_record(extension=extension),
        sidecar="images.parquet",
        row_number=4,
    )

    compacted = signal.curator_metadata["upstream_columns"]["extension"]
    for _ in range(nemo_image_writer.COMPACTION_MAX_DEPTH):
        compacted = compacted["next"]
    assert compacted == {"omitted": True, "type": "dict"}


@pytest.mark.parametrize("field", ["image_id", "tar_file", "member_name"])
def test_empty_required_text_rejects_with_exact_field_message(field: str) -> None:
    with pytest.raises(ValueError, match=rf"^{field} must be a non-empty string$"):
        parse_nemo_image_writer_record(
            image_writer_record(**{field: ""}),
            sidecar="images.parquet",
            row_number=5,
        )


@pytest.mark.parametrize("field", ["image_id", "tar_file", "member_name"])
def test_whitespace_only_required_text_rejects_with_exact_field_message(field: str) -> None:
    with pytest.raises(ValueError, match=rf"^{field} must be a non-empty string$"):
        parse_nemo_image_writer_record(
            image_writer_record(**{field: " \t\n"}),
            sidecar="images.parquet",
            row_number=5,
        )


def test_original_path_rejects_invalid_type() -> None:
    with pytest.raises(ValueError, match=r"^original_path must be a string or null$"):
        parse_nemo_image_writer_record(
            image_writer_record(original_path=123),
            sidecar="images.parquet",
            row_number=6,
        )


def test_out_of_range_aesthetic_score_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        parse_nemo_image_writer_record(
            image_writer_record(aesthetic_score=1.2),
            sidecar="images.parquet",
            row_number=7,
        )


def test_direct_json_safe_metadata_mapping_is_parsed() -> None:
    metadata = {
        "url": "https://example.com/direct",
        "text": "Direct mapping caption",
        "nested": {"safe": [1, 2, 3]},
    }

    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=metadata),
        sidecar="images.parquet",
        row_number=8,
    )

    assert signal.source_url == "https://example.com/direct"
    assert signal.caption == "Direct mapping caption"
    assert signal.curator_metadata["nemo_metadata_raw"] == metadata
    assert signal.curator_metadata["nemo_metadata"] == metadata
    assert signal.curator_metadata["metadata_parse_status"] == "parsed"


def test_direct_metadata_compacts_stored_vector_without_losing_aliases() -> None:
    metadata = {
        "source_url": "https://example.com/vector",
        "caption": "Vector-backed image",
        "payload": {"embedding": [0.0] * 1000},
    }

    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=metadata),
        sidecar="images.parquet",
        row_number=8,
    )

    compacted_metadata = {
        "source_url": "https://example.com/vector",
        "caption": "Vector-backed image",
        "payload": {
            "embedding": {
                "omitted": True,
                "type": "list",
                "length": 1000,
            }
        },
    }
    assert signal.source_url == "https://example.com/vector"
    assert signal.caption == "Vector-backed image"
    assert signal.curator_metadata["metadata_parse_status"] == "parsed"
    assert signal.curator_metadata["nemo_metadata_raw"] == compacted_metadata
    assert signal.curator_metadata["nemo_metadata"] == compacted_metadata


def test_blank_primary_metadata_aliases_fall_back_to_nonblank_aliases() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(
            metadata={
                "source_url": " \t",
                "url": "https://example.com/fallback",
                "caption": "\n",
                "text": "Fallback caption",
            }
        ),
        sidecar="images.parquet",
        row_number=9,
    )

    assert signal.source_url == "https://example.com/fallback"
    assert signal.caption == "Fallback caption"


def test_all_blank_metadata_aliases_leave_signal_fields_missing() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(
            metadata={
                "source_url": " ",
                "url": "\t",
                "caption": "\n",
                "text": " \t",
            }
        ),
        sidecar="images.parquet",
        row_number=9,
    )

    assert signal.source_url is None
    assert signal.caption is None
    assert signal.missing_fields == ["source_url", "caption"]


@pytest.mark.parametrize(
    ("raw_metadata", "expected_status"),
    [
        ("[1, 2, 3]", "not_mapping"),
        ("not valid metadata {", "unparsed"),
    ],
)
def test_metadata_failure_statuses(raw_metadata: str, expected_status: str) -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=raw_metadata),
        sidecar="images.parquet",
        row_number=9,
    )

    assert signal.curator_metadata["nemo_metadata_raw"] == raw_metadata
    assert signal.curator_metadata["metadata_parse_status"] == expected_status
    assert "nemo_metadata" not in signal.curator_metadata


def test_literal_parser_recursion_error_is_handled_as_unparsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_metadata = "not-json"

    def raise_recursion_error(value: object) -> object:
        raise RecursionError(f"cannot parse {value!r}")

    monkeypatch.setattr(nemo_image_writer.ast, "literal_eval", raise_recursion_error)

    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=raw_metadata),
        sidecar="images.parquet",
        row_number=10,
    )

    assert signal.curator_metadata["nemo_metadata_raw"] == raw_metadata
    assert signal.curator_metadata["metadata_parse_status"] == "unparsed"
    assert "nemo_metadata" not in signal.curator_metadata


def test_non_json_safe_raw_and_extension_values_are_compacted() -> None:
    signal = parse_nemo_image_writer_record(
        image_writer_record(metadata=memoryview(b"abc"), extension={"not", "json"}),
        sidecar="images.parquet",
        row_number=11,
    )

    assert signal.curator_metadata["nemo_metadata_raw"] == {
        "omitted": True,
        "type": "binary",
        "length": 3,
    }
    assert signal.curator_metadata["metadata_parse_status"] == "not_mapping"
    assert signal.curator_metadata["upstream_columns"]["extension"] == {
        "omitted": True,
        "type": "set",
    }
