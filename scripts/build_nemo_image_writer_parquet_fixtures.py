from __future__ import annotations

import argparse
import json
from math import isfinite
from numbers import Real
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from typing import Any, Literal


FieldKind = Literal["string", "score"]
SchemaSpec = tuple[tuple[str, FieldKind], ...]

SOURCE_FIRST_SCHEMA: SchemaSpec = (
    ("image_id", "string"),
    ("tar_file", "string"),
    ("member_name", "string"),
    ("original_path", "string"),
    ("metadata", "string"),
)
DOCUMENTED_ENRICHED_SCHEMA: SchemaSpec = SOURCE_FIRST_SCHEMA + (
    ("aesthetic_score", "score"),
    ("nsfw_score", "score"),
)


FIXTURES: dict[str, tuple[str, str]] = {
    "source_first": (
        "nemo_image_writer_source_first.source.json",
        "nemo_image_writer_source_first.parquet",
    ),
    "documented_enriched": (
        "nemo_image_writer_documented_enriched.source.json",
        "nemo_image_writer_documented_enriched.parquet",
    ),
}
FIXTURE_SCHEMAS: dict[str, SchemaSpec] = {
    "source_first": SOURCE_FIRST_SCHEMA,
    "documented_enriched": DOCUMENTED_ENRICHED_SCHEMA,
}


def _valid_score(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return isfinite(value) and 0 <= value <= 1
    except (OverflowError, TypeError, ValueError):
        return False


def _load_and_validate_rows(
    source_dir: Path,
    source_name: str,
    schema_spec: SchemaSpec,
) -> list[dict[str, object]]:
    try:
        source_text = (source_dir / source_name).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{source_name}: unable to read UTF-8 JSON: {exc}") from exc
    try:
        rows = json.loads(source_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source_name}: invalid JSON: {exc.msg}") from exc

    if (
        not isinstance(rows, list)
        or len(rows) != 2
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise ValueError(f"{source_name}: expected a JSON array of exactly two objects")

    expected_columns = tuple(field_name for field_name, _ in schema_spec)
    for row_number, row in enumerate(rows, start=1):
        actual_columns = tuple(row)
        if actual_columns != expected_columns:
            raise ValueError(
                f"{source_name}: row {row_number}: expected columns in order: "
                f"{', '.join(expected_columns)}; got: {', '.join(actual_columns)}"
            )
        for field_name, field_kind in schema_spec:
            value = row[field_name]
            if field_kind == "string" and not isinstance(value, str):
                raise ValueError(
                    f"{source_name}: row {row_number}: {field_name} must be a string"
                )
            if field_kind == "score" and not _valid_score(value):
                raise ValueError(
                    f"{source_name}: row {row_number}: {field_name} must be a "
                    "finite real number between 0 and 1"
                )
    return rows


def _arrow_schema(pa: Any, schema_spec: SchemaSpec) -> Any:
    return pa.schema(
        [
            pa.field(
                field_name,
                pa.string() if field_kind == "string" else pa.float64(),
                nullable=False,
            )
            for field_name, field_kind in schema_spec
        ]
    )


def _restore_outputs(
    outputs: dict[str, Path],
    backups: dict[str, Path],
    initially_absent: set[str],
) -> None:
    for name, output_path in outputs.items():
        backup_path = backups.get(name)
        if backup_path is not None:
            backup_path.replace(output_path)
        elif name in initially_absent:
            try:
                output_path.unlink()
            except FileNotFoundError:
                pass


def _publish_staged_outputs(
    staged_paths: dict[str, Path],
    outputs: dict[str, Path],
    backups: dict[str, Path],
    initially_absent: set[str],
) -> None:
    try:
        for name in FIXTURES:
            staged_paths[name].replace(outputs[name])
    except Exception as publication_error:
        try:
            _restore_outputs(outputs, backups, initially_absent)
        except Exception as rollback_error:
            raise RuntimeError(
                "fixture publication failed and rollback failed: "
                f"publish error: {publication_error}; "
                f"rollback error: {rollback_error}"
            ) from publication_error
        raise RuntimeError(
            "fixture publication failed; restored previous outputs: "
            f"{publication_error}"
        ) from publication_error


def build_fixtures(source_dir: Path, out_dir: Path) -> dict[str, Path]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise ValueError(
            'fixture generation requires pip install ".[nemo-parquet]"'
        ) from exc

    tables: dict[str, Any] = {}
    outputs: dict[str, Path] = {}
    for name, (source_name, output_name) in FIXTURES.items():
        schema_spec = FIXTURE_SCHEMAS[name]
        rows = _load_and_validate_rows(source_dir, source_name, schema_spec)
        tables[name] = pa.Table.from_pylist(
            rows,
            schema=_arrow_schema(pa, schema_spec),
        )
        outputs[name] = out_dir / output_name

    out_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".nemo-image-writer-fixtures-",
        dir=out_dir,
    ) as staging_name:
        staging_dir = Path(staging_name)
        staged_paths: dict[str, Path] = {}
        for name, (_, output_name) in FIXTURES.items():
            staged_path = staging_dir / output_name
            pq.write_table(tables[name], staged_path)
            staged_paths[name] = staged_path

        backups: dict[str, Path] = {}
        initially_absent: set[str] = set()
        for name, (_, output_name) in FIXTURES.items():
            output_path = outputs[name]
            if output_path.exists():
                backup_path = staging_dir / f"{output_name}.backup"
                copy2(output_path, backup_path)
                backups[name] = backup_path
            else:
                initially_absent.add(name)
        _publish_staged_outputs(
            staged_paths,
            outputs,
            backups,
            initially_absent,
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Build synthetic NeMo ImageWriterStage Parquet contract fixtures.")
    )
    parser.add_argument("--source-dir", type=Path, default=Path("samples"))
    parser.add_argument("--out", type=Path, default=Path("samples"))
    args = parser.parse_args()
    outputs = build_fixtures(args.source_dir, args.out)
    for name, path in sorted(outputs.items()):
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
