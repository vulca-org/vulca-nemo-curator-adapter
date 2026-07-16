from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


PACKAGE_MANIFEST_NAME = "package_manifest.json"
PACKAGE_SCHEMA = "vulca.public_source_candidate_package.v1"
CONFIRMED_STATE = "human_review_confirmed_for_publication"
PUBLIC_REPOSITORY = "vulca-org/vulca-nemo-curator-adapter"
SOURCE_AUTHORITY = "controlled_vulca_curator_adapter_upstream"
EXPORT_DIRECTION = "one_way_upstream_to_public_distribution"
SELECTION_MANIFEST = "configs/nemo_parquet_public_files.txt"


def _candidate_digest(root: Path, included_files: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(included_files):
        payload = (root / PurePosixPath(relative)).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _tracked_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def verify_candidate(root: Path) -> None:
    manifest = json.loads((root / PACKAGE_MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != PACKAGE_SCHEMA:
        raise ValueError("unsupported package manifest schema")
    if manifest.get("package_state") != CONFIRMED_STATE:
        raise ValueError("public candidate is not human-confirmed for publication")

    included_files = manifest.get("included_files")
    if not isinstance(included_files, list) or not all(
        isinstance(relative, str) for relative in included_files
    ):
        raise ValueError("included_files must be a list of paths")
    if len(included_files) != len(set(included_files)):
        raise ValueError("included_files contains duplicates")
    if manifest.get("included_count") != len(included_files):
        raise ValueError("included_count does not match included_files")

    selection_path = root / SELECTION_MANIFEST
    selected_files = [
        line for line in selection_path.read_text(encoding="utf-8").splitlines() if line
    ]
    if selected_files != included_files:
        raise ValueError("selection manifest does not match included_files")
    expected_tracked = set(included_files) | {PACKAGE_MANIFEST_NAME}
    if _tracked_files(root) != expected_tracked:
        raise ValueError("tracked files exceed or omit the curated public boundary")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("package provenance is missing")
    if provenance.get("authority") != SOURCE_AUTHORITY:
        raise ValueError("unexpected source authority")
    if provenance.get("export_direction") != EXPORT_DIRECTION:
        raise ValueError("unexpected export direction")
    if provenance.get("selection_manifest") != SELECTION_MANIFEST:
        raise ValueError("unexpected selection manifest")
    if provenance.get("source_worktree_state") != "clean":
        raise ValueError("candidate was not exported from a clean source worktree")
    source_revision = provenance.get("source_revision")
    if not isinstance(source_revision, str) or re.fullmatch(
        r"[0-9a-f]{40}", source_revision
    ) is None:
        raise ValueError("source revision is not a full Git commit id")

    human_gate = manifest.get("human_gate")
    if not isinstance(human_gate, dict) or human_gate.get("confirmed") is not True:
        raise ValueError("human publication gate is not confirmed")
    publication = manifest.get("publication")
    if not isinstance(publication, dict):
        raise ValueError("publication record is missing")
    if publication.get("repository") != PUBLIC_REPOSITORY:
        raise ValueError("publication repository does not match this distribution")
    if publication.get("source_contents") != "exact_curated_candidate":
        raise ValueError("publication source boundary is not exact")
    if publication.get("candidate_digest_sha256") != _candidate_digest(
        root, included_files
    ):
        raise ValueError("candidate digest does not match the tracked source set")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the exact public Curator adapter boundary and provenance."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        verify_candidate(args.root.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print("Verified exact curated public candidate, provenance, and digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
