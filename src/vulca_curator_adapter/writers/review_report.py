from __future__ import annotations

from pathlib import Path
from typing import Mapping


def _counter_lines(counts: Mapping[str, int]) -> list[str]:
    if not counts:
        return ["- none"]
    return [f"- `{key}`: {value}" for key, value in sorted(counts.items())]


def write_review_report(
    path: Path,
    *,
    assets_triaged: int,
    review_packets_written: int,
    lane_counts: Mapping[str, int],
    source_dependency_counts: Mapping[str, int],
    decision_basis_counts: Mapping[str, int],
    source_context_availability_counts: Mapping[str, int],
    privacy_scope_counts: Mapping[str, int],
) -> None:
    lines = [
        "# Source-Gate Internal Review Pack",
        "",
        "This is an internal review pack, not an outreach-ready NVIDIA case study.",
        "All rows keep `public_ready=false` and require human confirmation before reuse.",
        "",
        "## Totals",
        "",
        f"- Input rows: {assets_triaged}",
        f"- Review packets: {review_packets_written}",
        "",
        "## Triage Lanes",
        "",
        *_counter_lines(lane_counts),
        "",
        "## Source Dependency",
        "",
        *_counter_lines(source_dependency_counts),
        "",
        "## Decision Basis",
        "",
        *_counter_lines(decision_basis_counts),
        "",
        "## Source Context Availability",
        "",
        *_counter_lines(source_context_availability_counts),
        "",
        "## Privacy Scope",
        "",
        *_counter_lines(privacy_scope_counts),
        "",
        "## Release Boundary",
        "",
        "This pack is internal-only. It is not public-ready and should not be used as external outreach material.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
