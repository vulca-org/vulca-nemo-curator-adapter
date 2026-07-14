from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import ValidationError

from vulca_curator_adapter.ingest.nemo_image_writer import (
    ADAPTER_CONTRACT,
    REQUIRED_COLUMNS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPOSITORY,
    parse_nemo_image_writer_record,
)
from vulca_curator_adapter.schemas import CuratorSignal


DEFAULT_BATCH_SIZE = 1024
_CORE_TEXT_COLUMNS = frozenset({"image_id", "tar_file", "member_name"})
_OPTIONAL_SCORE_COLUMNS = frozenset({"aesthetic_score", "nsfw_score"})


def _load_pyarrow() -> tuple[Any, Any, str]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise ValueError(
            "PyArrow is required for NeMo Parquet ingestion; install it with "
            "`pip install vulca-curator-adapter[nemo-parquet]`."
        ) from exc
    return pa, pq, pa.__version__


def _is_string_type(pa: Any, data_type: Any) -> bool:
    return pa.types.is_string(data_type) or pa.types.is_large_string(data_type)


def _is_compatible_contract_type(pa: Any, column: str, data_type: Any) -> bool:
    if column in _CORE_TEXT_COLUMNS:
        return _is_string_type(pa, data_type)
    if column == "original_path":
        return _is_string_type(pa, data_type) or pa.types.is_null(data_type)
    if column == "metadata":
        return (
            _is_string_type(pa, data_type)
            or pa.types.is_struct(data_type)
            or pa.types.is_null(data_type)
        )
    if column in _OPTIONAL_SCORE_COLUMNS:
        return (
            pa.types.is_integer(data_type)
            or pa.types.is_floating(data_type)
            or pa.types.is_null(data_type)
        )
    return True


def _open_parquet(path: Path) -> tuple[Any, Any, list[str], str]:
    pa, pq, pyarrow_version = _load_pyarrow()
    try:
        parquet_file = pq.ParquetFile(path)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"{path.name}: unreadable Parquet: {exc}") from exc

    schema_columns = list(parquet_file.schema_arrow.names)
    duplicate_columns = sorted(
        name for name, count in Counter(schema_columns).items() if count > 1
    )
    if duplicate_columns:
        raise ValueError(
            f"{path.name}: duplicate columns: {', '.join(duplicate_columns)}"
        )

    missing_columns = sorted(REQUIRED_COLUMNS.difference(schema_columns))
    if missing_columns:
        raise ValueError(
            f"{path.name}: missing required columns: {', '.join(missing_columns)}"
        )

    schema = parquet_file.schema_arrow
    incompatible_types = [
        f"{field.name}={field.type}"
        for field in schema
        if not _is_compatible_contract_type(pa, field.name, field.type)
    ]
    if incompatible_types:
        raise ValueError(
            f"{path.name}: incompatible column types: {', '.join(incompatible_types)}"
        )
    return pa, parquet_file, schema_columns, pyarrow_version


def describe_nemo_parquet(path: Path) -> dict[str, Any]:
    _, _, schema_columns, pyarrow_version = _open_parquet(path)
    return {
        "input_format": "parquet",
        "adapter_contract": ADAPTER_CONTRACT,
        "schema_columns": schema_columns,
        "pyarrow_version": pyarrow_version,
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
        },
        "benchmark_mode": "local_parquet_engineering",
        "executor_type": "local_parquet_cli",
    }


def _run_reader_operation(path: Path, pa: Any, operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except pa.ArrowException as exc:
        raise ValueError(f"{path.name}: failed while reading Parquet: {exc}") from exc
    except ValueError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{path.name}: failed while reading Parquet: {exc}") from exc


def _iter_record_batches(
    path: Path, pa: Any, parquet_file: Any, batch_size: int
) -> Iterator[list[dict[str, object]]]:
    batches = _run_reader_operation(
        path,
        pa,
        lambda: iter(parquet_file.iter_batches(batch_size=batch_size)),
    )
    while True:
        try:
            batch = _run_reader_operation(path, pa, lambda: next(batches))
        except StopIteration:
            return
        records = _run_reader_operation(path, pa, batch.to_pylist)
        yield records


def iter_nemo_parquet_signals(
    path: Path, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> Iterator[CuratorSignal]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    pa, parquet_file, _, _ = _open_parquet(path)
    row_number = 0
    for records in _iter_record_batches(path, pa, parquet_file, batch_size):
        for record in records:
            row_number += 1
            try:
                signal = parse_nemo_image_writer_record(
                    record,
                    sidecar=path.name,
                    row_number=row_number,
                )
            except (ValidationError, ValueError) as exc:
                raise ValueError(f"{path.name}:{row_number}: {exc}") from exc
            yield signal
