from __future__ import annotations

import json
import os
from html import escape
from itertools import islice
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from vulca_curator_adapter.schemas import ReviewPacket


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return escape(", ".join(str(item) for item in value))
    if isinstance(value, dict):
        return escape(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return escape(str(value))


def _preview_src(uri: object, html_dir: Path) -> str:
    raw_uri = str(uri)
    parsed = urlsplit(raw_uri)
    if parsed.scheme and parsed.scheme != "file":
        return raw_uri

    candidate = Path(parsed.path if parsed.scheme == "file" else raw_uri)
    if candidate.is_absolute():
        return os.path.relpath(candidate, start=html_dir)

    if (html_dir / candidate).exists():
        return raw_uri

    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.exists():
        if not html_dir.resolve().is_relative_to(Path.cwd().resolve()):
            return raw_uri
        return os.path.relpath(cwd_candidate, start=html_dir)

    return raw_uri


def _image_preview(uri: object, html_dir: Path, modality: object = None) -> str:
    if modality == "case":
        return '<span class="metadata-row">metadata review row</span>'
    if not uri:
        return ""
    escaped_uri = escape(_preview_src(uri, html_dir), quote=True)
    return f'<img src="{escaped_uri}" alt="" style="max-height:120px;max-width:180px;object-fit:contain">'


def write_contact_sheet(path: Path, packets: Iterable[ReviewPacket], max_packets: int = 1000) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = 0
    with path.open("w", encoding="utf-8") as handle:
        handle.write("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>VULCA Curator Adapter Contact Sheet</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #d9e2ec; padding: 8px; vertical-align: top; font-size: 14px; }
    th { background: #f0f4f8; text-align: left; }
    img { background: #f7f9fb; border: 1px solid #d9e2ec; }
    caption { caption-side: top; text-align: left; font-weight: 700; margin-bottom: 12px; }
    .notice { background: #fff8c5; border: 1px solid #f0d000; padding: 8px; margin-bottom: 12px; }
    .metadata-row { color: #475569; font-size: 13px; }
  </style>
</head>
<body>
""")
        handle.write(
            f'  <p class="notice">Only the first {_cell(max_packets)} review packets are rendered in this HTML preview.</p>\n'
        )
        handle.write("""  <table>
    <caption>VULCA Curator Adapter Contact Sheet</caption>
    <thead>
      <tr>
        <th>Asset</th>
        <th>Preview</th>
        <th>URI</th>
        <th>Caption</th>
        <th>Review Lens</th>
        <th>Missing Fields</th>
        <th>Owner Route</th>
        <th>Human Gate</th>
        <th>Review Context</th>
      </tr>
    </thead>
    <tbody>
""")
        for packet in islice(packets, max(0, max_packets)):
            rendered += 1
            handle.write(
                "<tr>"
                f"<td>{_cell(packet.asset_id)}</td>"
                f"<td>{_image_preview(packet.candidate_surface.get('uri'), path.parent, packet.candidate_surface.get('modality'))}</td>"
                f"<td>{_cell(packet.candidate_surface.get('uri'))}</td>"
                f"<td>{_cell(packet.candidate_surface.get('caption'))}</td>"
                f"<td>{_cell(packet.review_lens)}</td>"
                f"<td>{_cell(packet.missing_fields)}</td>"
                f"<td>{_cell(packet.owner_route)}</td>"
                f"<td>{_cell(packet.human_gate)}</td>"
                f"<td>{_cell(packet.review_context)}</td>"
                "</tr>\n"
            )
        handle.write("""    </tbody>
  </table>
</body>
</html>
""")
    return rendered
