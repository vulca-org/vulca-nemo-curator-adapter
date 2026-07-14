from __future__ import annotations

from pathlib import Path
from typing import Mapping


def _counter_lines(counts: Mapping[str, int]) -> list[str]:
    if not counts:
        return ["- none"]
    return [f"- `{key}`: {value}" for key, value in sorted(counts.items())]


def write_visual_review_report(
    path: Path,
    *,
    assets_triaged: int,
    review_packets_written: int,
    images_existing: int,
    lane_counts: Mapping[str, int],
    risk_bucket_counts: Mapping[str, int],
) -> None:
    lines = [
        "# Visual Evidence Internal Review Pack",
        "",
        "This is an internal-only visual evidence pack, not an outreach-ready NVIDIA demo.",
        "All rows keep `public_ready=false` and require rights/source review before external use.",
        "",
        "## Totals",
        "",
        f"- Input rows: {assets_triaged}",
        f"- Review packets: {review_packets_written}",
        f"- Image existence count: {images_existing}/{assets_triaged}",
        "",
        "## Triage Lanes",
        "",
        *_counter_lines(lane_counts),
        "",
        "## Risk Buckets",
        "",
        *_counter_lines(risk_bucket_counts),
        "",
        "## External Use Blockers",
        "",
        "- rights/source verification",
        "- sensitive/person review",
        "- public-source attribution",
        "",
        "## Release Boundary",
        "",
        "This pack is internal-only. It is not public-ready and should not be used as external outreach material.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
