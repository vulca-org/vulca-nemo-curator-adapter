from __future__ import annotations

from pathlib import Path
from typing import Mapping


def write_summary(
    path: Path,
    assets_triaged: int,
    review_packets_written: int,
    html_packets_rendered: int,
    lane_counts: Mapping[str, int],
) -> None:
    lines = [
        "# VULCA Curator Adapter Run Summary",
        "",
        f"Assets triaged: {assets_triaged}",
        f"Review packets written: {review_packets_written}",
        f"HTML packets rendered: {html_packets_rendered}",
        "",
        "## Triage Lanes",
        "",
    ]
    for lane, count in sorted(lane_counts.items()):
        lines.append(f"- `{lane}`: {count}")
    lines.append("")
    lines.append("## Release Boundary")
    lines.append("")
    lines.append("All generated packets keep `public_ready=false` until a human release owner confirms the gate.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
