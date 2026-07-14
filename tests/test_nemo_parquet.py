from __future__ import annotations

import builtins
import importlib
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from vulca_curator_adapter.ingest import nemo_parquet
from vulca_curator_adapter.ingest.nemo_image_writer import (
    ADAPTER_CONTRACT,
    UPSTREAM_COMMIT,
    UPSTREAM_REPOSITORY,
)
from vulca_curator_adapter.ingest.nemo_parquet import (
    DEFAULT_BATCH_SIZE,
    _load_pyarrow,
    describe_nemo_parquet,
    iter_nemo_parquet_signals,
)

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

SCHEMA_COLUMNS = [
    "image_id",
    "tar_file",
    "member_name",
    "original_path",
    "metadata",
]


def parquet_schema(*, extra_fields: list[Any] | None = None) -> Any:
    fields = [pa.field(name, pa.string()) for name in SCHEMA_COLUMNS]
    fields.extend(extra_fields or [])
    return pa.schema(fields)


def parquet_row(image_id: str | None, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "image_id": image_id,
        "tar_file": "shards/images-00000.tar",
        "member_name": f"{image_id}.jpg",
        "original_path": f"/source/{image_id}.jpg",
        "metadata": '{"caption": "A source image"}',
    }
    row.update(overrides)
    return row


def write_parquet(
    path: Path,
    rows: list[dict[str, object]],
    *,
    schema: Any | None = None,
) -> None:
    table = pa.Table.from_pylist(rows, schema=schema or parquet_schema())
    pq.write_table(table, path)


def test_default_batch_size_is_bounded() -> None:
    assert DEFAULT_BATCH_SIZE == 1024


def test_streams_three_rows_across_batches_with_global_row_numbers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "images.parquet"
    write_parquet(
        path,
        [parquet_row("image-1"), parquet_row("image-2"), parquet_row("image-3")],
    )

    signals = list(iter_nemo_parquet_signals(path, batch_size=1))

    assert [signal.asset_id for signal in signals] == ["image-1", "image-2", "image-3"]
    assert [
        signal.curator_metadata["parquet_provenance"]["row_number"]
        for signal in signals
    ] == [1, 2, 3]
    assert {
        signal.curator_metadata["parquet_provenance"]["sidecar"]
        for signal in signals
    } == {"images.parquet"}


def test_empty_parquet_with_required_schema_yields_no_signals(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    write_parquet(path, [])

    assert list(iter_nemo_parquet_signals(path)) == []


def test_descriptor_reports_schema_pin_and_execution_labels(tmp_path: Path) -> None:
    path = tmp_path / "images.parquet"
    write_parquet(path, [])

    assert describe_nemo_parquet(path) == {
        "input_format": "parquet",
        "adapter_contract": ADAPTER_CONTRACT,
        "schema_columns": SCHEMA_COLUMNS,
        "pyarrow_version": pa.__version__,
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
        },
        "benchmark_mode": "local_parquet_engineering",
        "executor_type": "local_parquet_cli",
    }


def test_missing_required_schema_columns_fail_before_rows_are_read(tmp_path: Path) -> None:
    path = tmp_path / "missing.parquet"
    schema = pa.schema(
        [
            pa.field("image_id", pa.string()),
            pa.field("tar_file", pa.string()),
            pa.field("member_name", pa.string()),
        ]
    )
    write_parquet(path, [], schema=schema)

    with pytest.raises(
        ValueError,
        match=r"^missing\.parquet: missing required columns: metadata, original_path$",
    ):
        list(iter_nemo_parquet_signals(path))


def test_empty_parquet_rejects_incompatible_contract_types(tmp_path: Path) -> None:
    path = tmp_path / "wrong-types.parquet"
    schema = pa.schema(
        [
            pa.field("image_id", pa.int64()),
            pa.field("tar_file", pa.bool_()),
            pa.field("member_name", pa.float64()),
            pa.field("original_path", pa.int64()),
            pa.field("metadata", pa.binary()),
            pa.field("aesthetic_score", pa.string()),
            pa.field("nsfw_score", pa.bool_()),
        ]
    )
    write_parquet(path, [], schema=schema)

    with pytest.raises(ValueError) as caught:
        describe_nemo_parquet(path)

    assert str(caught.value) == (
        "wrong-types.parquet: incompatible column types: "
        "image_id=int64, tar_file=bool, member_name=double, original_path=int64, "
        "metadata=binary, aesthetic_score=string, nsfw_score=bool"
    )


def test_duplicate_columns_fail_before_required_column_check(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.parquet"
    table = pa.Table.from_arrays(
        [
            pa.array(["image-first"]),
            pa.array(["image-last"]),
            pa.array(["shards/images.tar"]),
            pa.array(["image.jpg"]),
            pa.array(["{}"]),
            pa.array(['{"caption": "last"}']),
        ],
        names=[
            "image_id",
            "image_id",
            "tar_file",
            "member_name",
            "metadata",
            "metadata",
        ],
    )
    pq.write_table(table, path)

    with pytest.raises(
        ValueError,
        match=r"^duplicates\.parquet: duplicate columns: image_id, metadata$",
    ):
        list(iter_nemo_parquet_signals(path))


def test_empty_required_value_reports_global_row_number(tmp_path: Path) -> None:
    path = tmp_path / "empty-value.parquet"
    write_parquet(
        path,
        [parquet_row("image-1"), parquet_row("image-2", member_name="")],
    )

    with pytest.raises(
        ValueError,
        match=(
            r"^empty-value\.parquet:2: member_name must be a non-empty string$"
        ),
    ):
        list(iter_nemo_parquet_signals(path, batch_size=1))


def test_null_required_value_reports_global_row_number(tmp_path: Path) -> None:
    path = tmp_path / "null-value.parquet"
    write_parquet(path, [parquet_row("image-1"), parquet_row(None)])

    with pytest.raises(
        ValueError,
        match=r"^null-value\.parquet:2: image_id must be a non-empty string$",
    ):
        list(iter_nemo_parquet_signals(path, batch_size=1))


def test_mapper_runtime_error_propagates_without_reader_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "mapper.parquet"
    write_parquet(path, [parquet_row("image-1")])
    error = RuntimeError("mapper failed")

    def fail_mapping(*args: object, **kwargs: object) -> Any:
        raise error

    monkeypatch.setattr(
        nemo_parquet,
        "parse_nemo_image_writer_record",
        fail_mapping,
    )

    with pytest.raises(RuntimeError) as caught:
        list(iter_nemo_parquet_signals(path))

    assert caught.value is error


def test_corrupt_parquet_has_normalized_open_error(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.parquet"
    path.write_bytes(b"not a parquet file")

    with pytest.raises(
        ValueError,
        match=r"^corrupt\.parquet: unreadable Parquet: ",
    ):
        list(iter_nemo_parquet_signals(path))


def test_open_does_not_normalize_runtime_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError("unexpected open failure")

    class FailingParquetModule:
        @staticmethod
        def ParquetFile(path: Path) -> Any:
            raise error

    monkeypatch.setattr(
        nemo_parquet,
        "_load_pyarrow",
        lambda: (pa, FailingParquetModule, pa.__version__),
    )

    with pytest.raises(RuntimeError) as caught:
        nemo_parquet._open_parquet(tmp_path / "reader.parquet")

    assert caught.value is error


def install_iteration_failure(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    class FailingReader:
        schema_arrow = parquet_schema()

        def iter_batches(self, *, batch_size: int) -> Any:
            if False:
                yield batch_size
            raise error

    class FailingParquetModule:
        @staticmethod
        def ParquetFile(path: Path) -> Any:
            return FailingReader()

    monkeypatch.setattr(
        nemo_parquet,
        "_load_pyarrow",
        lambda: (pa, FailingParquetModule, pa.__version__),
    )


def test_iteration_preserves_value_error_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ValueError("already normalized")
    install_iteration_failure(monkeypatch, error)

    with pytest.raises(ValueError) as caught:
        list(iter_nemo_parquet_signals(tmp_path / "reader.parquet"))

    assert caught.value is error
    assert str(caught.value) == "already normalized"


@pytest.mark.parametrize(
    "error",
    [
        pa.ArrowInvalid("invalid batch"),
        OSError("disk unavailable"),
        RuntimeError("reader stopped"),
    ],
)
def test_iteration_normalizes_supported_reader_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    install_iteration_failure(monkeypatch, error)

    with pytest.raises(
        ValueError,
        match=(
            rf"^reader\.parquet: failed while reading Parquet: "
            rf"{str(error)}$"
        ),
    ):
        list(iter_nemo_parquet_signals(tmp_path / "reader.parquet"))


def test_iteration_does_not_normalize_unexpected_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = LookupError("unexpected reader failure")
    install_iteration_failure(monkeypatch, error)

    with pytest.raises(LookupError) as caught:
        list(iter_nemo_parquet_signals(tmp_path / "reader.parquet"))

    assert caught.value is error


@pytest.mark.parametrize("batch_size", [0, -1])
def test_non_positive_batch_size_is_rejected(
    tmp_path: Path, batch_size: int
) -> None:
    with pytest.raises(ValueError, match=r"^batch_size must be positive$"):
        list(iter_nemo_parquet_signals(tmp_path / "unused.parquet", batch_size=batch_size))


def test_extra_columns_are_streamed_into_upstream_metadata(tmp_path: Path) -> None:
    path = tmp_path / "extra.parquet"
    schema = parquet_schema(extra_fields=[pa.field("source_quality", pa.string())])
    write_parquet(
        path,
        [parquet_row("image-1", source_quality="licensed")],
        schema=schema,
    )

    [signal] = list(iter_nemo_parquet_signals(path))

    assert signal.curator_metadata["upstream_columns"] == {
        "source_quality": "licensed"
    }


def test_localized_loader_returns_modules_and_version() -> None:
    loaded_pa, loaded_pq, version = _load_pyarrow()

    assert loaded_pa is pa
    assert loaded_pq is pq
    assert version == pa.__version__


def test_missing_pyarrow_has_install_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def blocked_pyarrow_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ModuleNotFoundError("blocked for test", name="pyarrow")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_pyarrow_import)

    with pytest.raises(
        ValueError,
        match=r"pip install vulca-curator-adapter\[nemo-parquet\]",
    ):
        _load_pyarrow()


def test_module_import_does_not_import_pyarrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def reject_pyarrow_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise AssertionError("nemo_parquet imported PyArrow at module import time")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_pyarrow_import)

    importlib.reload(nemo_parquet)


def test_base_import_without_pyarrow(tmp_path: Path) -> None:
    script = textwrap.dedent(
        r"""
        import builtins
        import json
        import sys
        from pathlib import Path

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "pyarrow" or name.startswith("pyarrow."):
                raise AssertionError(f"unexpected PyArrow import: {name}")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        from vulca_curator_adapter.cli import build_parser, run_triage

        assert "triage" in build_parser().format_help()
        root = Path(sys.argv[1])
        input_path = root / "input.jsonl"
        input_path.write_text(
            json.dumps({"id": "jsonl-1", "image_path": "synthetic://jsonl-1.png"}) + "\n",
            encoding="utf-8",
        )
        result = run_triage(
            input_path=input_path,
            parser="nemo",
            profile="creative-release",
            out_dir=root / "run",
        )
        assert result["assets_triaged"] == 1
        """
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
