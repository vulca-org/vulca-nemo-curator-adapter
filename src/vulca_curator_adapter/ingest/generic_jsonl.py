from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from vulca_curator_adapter.ingest.cosmos import parse_cosmos_record
from vulca_curator_adapter.ingest.nemo import parse_nemo_record
from vulca_curator_adapter.ingest.nemo_parquet import (
    describe_nemo_parquet,
    iter_nemo_parquet_signals,
)
from vulca_curator_adapter.ingest.source_gate import parse_source_gate_record
from vulca_curator_adapter.ingest.visual_evidence import parse_visual_evidence_record
from vulca_curator_adapter.schemas import CuratorSignal

ParserName = Literal["generic", "nemo", "cosmos", "vulca-source-gate", "vulca-visual-evidence"]
InputFormat = Literal["jsonl", "parquet"]


class InputDescriptor(TypedDict):
    input_format: InputFormat
    benchmark_mode: str
    executor_type: str
    adapter_contract: NotRequired[str]
    schema_columns: NotRequired[list[str]]
    pyarrow_version: NotRequired[str]
    upstream: NotRequired[dict[str, str]]


def _validate_parser(parser: ParserName) -> None:
    if parser not in {"generic", "nemo", "cosmos", "vulca-source-gate", "vulca-visual-evidence"}:
        raise ValueError(f"unknown parser: {parser}")


def _classify_input(path: Path) -> InputFormat:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".parquet":
        return "parquet"
    raise ValueError(f"unsupported input suffix: {suffix or '<none>'}")


def _validate_input_parser(input_format: InputFormat, parser: ParserName) -> None:
    if input_format == "parquet" and parser != "nemo":
        raise ValueError("Parquet input currently requires --parser nemo")


def describe_input(path: Path, parser: ParserName) -> InputDescriptor:
    _validate_parser(parser)
    input_format = _classify_input(path)
    _validate_input_parser(input_format, parser)
    if input_format == "jsonl":
        return {
            "input_format": "jsonl",
            "benchmark_mode": "local_jsonl_engineering",
            "executor_type": "local_jsonl_cli",
        }
    return cast(InputDescriptor, describe_nemo_parquet(path))


def iter_jsonl_records(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path.name}:{line_number}: JSONL record must be an object")
            yield record


def parse_generic_record(record: dict) -> CuratorSignal:
    return CuratorSignal.model_validate(record)


def iter_signals(path: Path, parser: ParserName = "generic") -> Iterator[CuratorSignal]:
    _validate_parser(parser)
    input_format = _classify_input(path)
    _validate_input_parser(input_format, parser)
    if input_format == "parquet":
        yield from iter_nemo_parquet_signals(path)
        return

    for record in iter_jsonl_records(path):
        if parser == "generic":
            yield parse_generic_record(record)
        elif parser == "nemo":
            yield parse_nemo_record(record)
        elif parser == "cosmos":
            yield parse_cosmos_record(record)
        elif parser == "vulca-source-gate":
            yield parse_source_gate_record(record)
        elif parser == "vulca-visual-evidence":
            yield parse_visual_evidence_record(record)
