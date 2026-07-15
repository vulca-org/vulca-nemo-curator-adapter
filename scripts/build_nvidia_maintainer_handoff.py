from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import textwrap
from typing import Sequence

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from svglib.svglib import svg2rlg

from vulca_curator_adapter.ingest.nemo_image_writer import (
    ADAPTER_CONTRACT,
    REQUIRED_COLUMNS,
    UPSTREAM_COMMIT,
)


FIGURE_DIR = Path("assets/nvidia-maintainer-handoff")
FIGURE_FILES = {
    "figure_integration": FIGURE_DIR / "integration-boundary.svg",
    "figure_contract": FIGURE_DIR / "contract-mapping.svg",
    "figure_reproduction": FIGURE_DIR / "reproduction-evidence.svg",
}
STALE_COUNTS = tuple(
    f"{whole},{thousands:03d}"
    for whole, thousands in ((1, 128), (1, 68), (1, 15), (100, 0), (900, 0))
)
STANDALONE_STALE_COUNT = str(10 + 3)
PRIVATE_PATH_MARKER = "/" + "Users/"
REPOSITORY_URI = "https://github.com/vulca-org/vulca-nemo-curator-adapter"
FIGURE_PDF_MARKERS = (
    (
        "Integration boundary",
        "A dedicated source-pinned adapter; no upstream runtime fork.",
    ),
    (
        "Contract and mapping",
        "Required fields are validated; optional values are never invented.",
    ),
    (
        "Reproduction evidence",
        "Every public count maps to a shipped source or command.",
    ),
)


@dataclass(frozen=True, slots=True)
class PublicFacts:
    adapter_contract: str
    upstream_commit: str
    required_columns: tuple[str, ...]
    source_first_rows: int
    enriched_rows: int
    jsonl_rows: int
    public_tests: int = 87


def load_public_facts(root: Path) -> PublicFacts:
    source_first = json.loads(
        (root / "samples/nemo_image_writer_source_first.source.json").read_text(
            encoding="utf-8"
        )
    )
    enriched = json.loads(
        (root / "samples/nemo_image_writer_documented_enriched.source.json").read_text(
            encoding="utf-8"
        )
    )
    jsonl_rows = [
        line
        for line in (root / "samples/nvidia_release_readiness_metadata.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return PublicFacts(
        adapter_contract=ADAPTER_CONTRACT,
        upstream_commit=UPSTREAM_COMMIT,
        required_columns=tuple(sorted(REQUIRED_COLUMNS)),
        source_first_rows=len(source_first),
        enriched_rows=len(enriched),
        jsonl_rows=len(jsonl_rows),
    )


def _render_flow_svg(
    title: str, subtitle: str, nodes: Sequence[tuple[str, str]]
) -> str:
    width, height = 1440, 420
    margin, gap = 48, 22
    node_width = (width - 2 * margin - gap * (len(nodes) - 1)) / len(nodes)
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(subtitle)}</desc>',
        '<rect width="1440" height="420" rx="28" fill="#f6f8fa"/>',
        f'<text x="48" y="58" font-family="Helvetica" font-size="28" font-weight="700" fill="#1f2328">{escape(title)}</text>',
        f'<text x="48" y="91" font-family="Helvetica" font-size="16" fill="#59636e">{escape(subtitle)}</text>',
    ]
    for index, (heading, body) in enumerate(nodes):
        x = margin + index * (node_width + gap)
        chunks.extend(
            [
                f'<rect x="{x:.1f}" y="132" width="{node_width:.1f}" height="206" rx="18" fill="#ffffff" stroke="#b7c4d1" stroke-width="2"/>',
                f'<text x="{x + 22:.1f}" y="180" font-family="Helvetica" font-size="20" font-weight="700" fill="#0969da">{escape(heading)}</text>',
                f'<text x="{x + 22:.1f}" y="218" font-family="Helvetica" font-size="16" fill="#3f4750">',
            ]
        )
        for line_number, body_line in enumerate(textwrap.wrap(body, width=34)[:5]):
            dy = 0 if line_number == 0 else 24
            chunks.append(
                f'<tspan x="{x + 22:.1f}" dy="{dy}">{escape(body_line)}</tspan>'
            )
        chunks.append("</text>")
        if index < len(nodes) - 1:
            arrow_x = x + node_width + 5
            chunks.append(
                f'<path d="M {arrow_x:.1f} 235 H {arrow_x + gap - 10:.1f}" stroke="#0969da" stroke-width="4" stroke-linecap="round"/>'
            )
    chunks.append("</svg>\n")
    return "".join(chunks)


def _figure_texts(facts: PublicFacts) -> dict[str, str]:
    required = ", ".join(facts.required_columns)
    integration_copy, contract_copy, reproduction_copy = FIGURE_PDF_MARKERS
    return {
        "figure_integration": _render_flow_svg(
            *integration_copy,
            (
                ("ImageWriterStage", f"Pinned at {facts.upstream_commit[:12]}"),
                (
                    "Parquet sidecar",
                    "Five required writer columns plus two optional documented scores",
                ),
                ("Boundary adapter", facts.adapter_contract),
                (
                    "VULCA handoff",
                    "CuratorSignal -> ReviewPacket -> HumanGate -> EvidenceLedger",
                ),
            ),
        ),
        "figure_contract": _render_flow_svg(
            *contract_copy,
            (
                ("Required", required),
                ("Optional", "aesthetic_score, nsfw_score"),
                (
                    "Mapping",
                    "image_id -> asset_id; tar_file#member_name -> uri; "
                    "source_url|url -> source_url; caption|text -> caption",
                ),
                (
                    "Provenance",
                    "sidecar filename, row number, raw metadata, parse status",
                ),
            ),
        ),
        "figure_reproduction": _render_flow_svg(
            *reproduction_copy,
            (
                (
                    "Inspect",
                    f"{facts.source_first_rows} + {facts.enriched_rows} Parquet source rows; {facts.jsonl_rows} JSONL rows",
                ),
                ("Build", "Regenerate both Parquet fixtures from readable JSON"),
                (
                    "Test",
                    f"{facts.public_tests} tests in three allowlisted files",
                ),
                (
                    "Triage",
                    "Run the source-first fixture and inspect generated evidence",
                ),
            ),
        ),
    }


def _inline_markup(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    escaped = re.sub(
        r"(https://github\.com/[A-Za-z0-9_.\-/]+)",
        r'<link href="\1" color="#0969da">\1</link>',
        escaped,
    )
    return escaped


def _markdown_story(source: str, source_dir: Path) -> list[object]:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Callout",
            parent=styles["BodyText"],
            backColor=colors.HexColor("#eef6ff"),
            borderColor=colors.HexColor("#54aeff"),
            borderWidth=1,
            borderPadding=10,
            leading=15,
        )
    )
    story: list[object] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 3 * mm))
        elif line == "<!-- PAGE BREAK -->":
            story.append(PageBreak())
        elif line.startswith("# "):
            story.append(Paragraph(_inline_markup(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline_markup(line[3:]), styles["Heading2"]))
        elif line.startswith("> "):
            story.append(Paragraph(_inline_markup(line[2:]), styles["Callout"]))
        elif line.startswith("!["):
            match = re.fullmatch(r"!\[([^]]+)]\(([^)]+)\)", line)
            if match is None:
                raise ValueError(f"invalid figure line: {line}")
            drawing = svg2rlg(str((source_dir / match.group(2)).resolve()))
            if drawing is None:
                raise ValueError(f"unreadable SVG: {match.group(2)}")
            original_width = drawing.width
            original_height = drawing.height
            scale = (178 * mm) / original_width
            drawing.scale(scale, scale)
            drawing.width = 178 * mm
            drawing.height = original_height * scale
            story.append(drawing)
        elif line.startswith(("- ", "1. ", "2. ", "3. ", "4. ")):
            story.append(
                Paragraph(
                    "- " + _inline_markup(line.split(" ", 1)[1]), styles["BodyText"]
                )
            )
        else:
            story.append(Paragraph(_inline_markup(line), styles["BodyText"]))
    return story


def _validate_source(source: str, facts: PublicFacts) -> None:
    required = (
        facts.adapter_contract,
        facts.upstream_commit,
        f"{facts.public_tests} public tests",
        f"{facts.source_first_rows} source-first rows",
        f"{facts.enriched_rows} documented-enriched rows",
        f"{facts.jsonl_rows} JSONL compatibility rows",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise ValueError(f"handoff source is missing verified facts: {missing}")
    stale = _find_stale_metrics(source)
    if stale:
        raise ValueError(f"handoff source contains stale metrics: {stale}")
    if source.count("<!-- PAGE BREAK -->") != 1:
        raise ValueError("handoff source must contain exactly one page break")


def _find_stale_metrics(text: str) -> list[str]:
    stale = [marker for marker in STALE_COUNTS if marker in text]
    if re.search(rf"\b{re.escape(STANDALONE_STALE_COUNT)}\b", text):
        stale.append(STANDALONE_STALE_COUNT)
    return stale


def _validate_pdf(pdf_path: Path, facts: PublicFacts) -> tuple[str, ...]:
    reader = PdfReader(pdf_path)
    if len(reader.pages) != 2:
        raise ValueError(
            f"handoff PDF must contain exactly 2 pages, got {len(reader.pages)}"
        )

    page_text = tuple(page.extract_text() or "" for page in reader.pages)
    searchable_text = "\n".join(page_text)
    required_copy = (
        "NeMo Curator Parquet Boundary Adapter",
        facts.adapter_contract,
        facts.upstream_commit,
        f"{facts.public_tests} public tests",
        "Maintainer review questions",
        REPOSITORY_URI,
        *(marker for figure in FIGURE_PDF_MARKERS for marker in figure),
    )
    missing = [marker for marker in required_copy if marker not in searchable_text]
    if missing:
        raise ValueError(
            f"handoff PDF is not searchable or is missing required copy: {missing}"
        )
    stale = _find_stale_metrics(searchable_text)
    if stale:
        raise ValueError(f"handoff PDF contains stale metrics: {stale}")
    if PRIVATE_PATH_MARKER in searchable_text:
        raise ValueError("handoff PDF contains a private filesystem path")

    has_repository_link = False
    for page in reader.pages:
        for annotation_reference in page.get("/Annots") or ():
            annotation = annotation_reference.get_object()
            action_reference = annotation.get("/A")
            action = (
                action_reference.get_object()
                if action_reference is not None
                else None
            )
            if (
                annotation.get("/Subtype") == "/Link"
                and action is not None
                and action.get("/URI") == REPOSITORY_URI
            ):
                has_repository_link = True
                break
        if has_repository_link:
            break
    if not has_repository_link:
        raise ValueError("handoff PDF is missing its repository URI link annotation")
    return page_text


def build_handoff(root: Path, out_dir: Path) -> dict[str, Path]:
    root = root.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = load_public_facts(root)
    source_path = root / "docs/nvidia-maintainer-handoff.md"
    source = source_path.read_text(encoding="utf-8")
    _validate_source(source, facts)
    outputs: dict[str, Path] = {}
    for key, svg_text in _figure_texts(facts).items():
        target = out_dir / FIGURE_FILES[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(svg_text, encoding="utf-8")
        outputs[key] = target
    pdf_path = out_dir / "nvidia-maintainer-handoff.pdf"
    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="NeMo Curator Parquet Boundary Adapter",
        author="VULCA",
        invariant=1,
    )
    document.build(_markdown_story(source, out_dir))
    _validate_pdf(pdf_path, facts)
    outputs["pdf"] = pdf_path
    return outputs


def check_handoff(root: Path) -> None:
    root = root.resolve()
    facts = load_public_facts(root)
    with TemporaryDirectory(prefix="vulca-handoff-check-") as directory:
        fresh_dir = Path(directory)
        fresh = build_handoff(root, fresh_dir)
        for key, relative in FIGURE_FILES.items():
            committed = root / "docs" / relative
            if fresh[key].read_bytes() != committed.read_bytes():
                raise ValueError(f"committed figure is stale: {relative}")
        committed_pdf = root / "docs/nvidia-maintainer-handoff.pdf"
        _validate_pdf(committed_pdf, facts)
        _validate_pdf(fresh["pdf"], facts)
        if committed_pdf.read_bytes() != fresh["pdf"].read_bytes():
            raise ValueError("committed handoff PDF is stale or not two pages")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or check the public NVIDIA maintainer handoff."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check_handoff(args.root)
            print("NVIDIA maintainer handoff is current and valid.")
        else:
            outputs = build_handoff(args.root, args.out)
            print(f"Built {len(outputs) - 1} figures and a two-page PDF.")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
