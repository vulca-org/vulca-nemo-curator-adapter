from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time
from typing import Literal, Optional

from vulca_curator_adapter.evidence import (
    build_operation_trace,
    build_safety_checks,
    build_workflow_metrics,
    input_label,
    new_run_id,
    utc_now_iso,
    write_workflow_contract,
    write_run_manifest,
    write_safety_checks,
)
from vulca_curator_adapter.ingest.generic_jsonl import ParserName, describe_input, iter_signals
from vulca_curator_adapter.packets.review_packet import build_review_packet
from vulca_curator_adapter.triage.decision import decide
from vulca_curator_adapter.triage.policies import get_policy, load_policy_config
from vulca_curator_adapter.writers.html import write_contact_sheet
from vulca_curator_adapter.writers.jsonl import JsonlStreamWriter
from vulca_curator_adapter.writers.review_report import write_review_report
from vulca_curator_adapter.writers.summary import write_summary
from vulca_curator_adapter.writers.visual_report import write_visual_review_report


ProfileName = Literal[
    "dataset-curation",
    "creative-release",
    "generated-media-publishability",
    "source-gate-review",
    "visual-evidence-review",
]
RUN_OUTPUT_FILENAMES = (
    "triage.jsonl",
    "review_packets.jsonl",
    "summary.md",
    "contact_sheet.html",
    "review_report.md",
    "visual_review_report.md",
    "operation_trace.jsonl",
    "workflow_contract.json",
    "run_manifest.json",
    "safety_checks.json",
)


def _clear_run_outputs(out_dir: Path) -> None:
    for filename in RUN_OUTPUT_FILENAMES:
        path = out_dir / filename
        if path.exists():
            path.unlink()


def run_triage(
    input_path: Path,
    parser: ParserName,
    profile: ProfileName,
    out_dir: Path,
    html_limit: int = 1000,
    policy_config_path: Path | None = None,
) -> dict[str, int]:
    if html_limit < 0:
        raise ValueError("html_limit must be non-negative")

    policy = load_policy_config(policy_config_path, expected_profile=profile) if policy_config_path else get_policy(profile)
    assets_triaged = 0
    review_packets_written = 0
    lane_counts: Counter[str] = Counter()
    source_dependency_counts: Counter[str] = Counter()
    decision_basis_counts: Counter[str] = Counter()
    source_context_availability_counts: Counter[str] = Counter()
    privacy_scope_counts: Counter[str] = Counter()
    risk_bucket_counts: Counter[str] = Counter()
    images_existing = 0
    source_gate_active = profile == "source-gate-review"
    visual_evidence_active = profile == "visual-evidence-review"
    html_packets = []
    run_id = new_run_id()
    created_at = utc_now_iso()
    input_label_value = input_label(input_path)
    input_descriptor = describe_input(input_path, parser)
    packet_public_ready_false = 0
    packet_human_gate_required = 0
    packet_human_gate_unconfirmed = 0

    started_at = time.perf_counter()
    _clear_run_outputs(out_dir)

    try:
        with (
            JsonlStreamWriter(out_dir / "triage.jsonl") as triage_writer,
            JsonlStreamWriter(out_dir / "review_packets.jsonl") as packet_writer,
            JsonlStreamWriter(out_dir / "operation_trace.jsonl") as trace_writer,
        ):
            for signal in iter_signals(input_path, parser=parser):
                decision = decide(signal, policy)
                assets_triaged += 1
                lane_counts[decision.triage_lane] += 1
                if source_gate_active:
                    context = signal.review_context
                    if context.get("source_dependency"):
                        source_dependency_counts[str(context["source_dependency"])] += 1
                    if context.get("decision_basis"):
                        decision_basis_counts[str(context["decision_basis"])] += 1
                    availability = "available" if context.get("source_context_available") else "missing"
                    source_context_availability_counts[availability] += 1
                    if context.get("privacy_scope"):
                        privacy_scope_counts[str(context["privacy_scope"])] += 1
                if visual_evidence_active:
                    context = signal.review_context
                    if context.get("risk_bucket"):
                        risk_bucket_counts[str(context["risk_bucket"])] += 1
                    if context.get("image_exists"):
                        images_existing += 1
                triage_writer.write(decision)
                packet = None
                if decision.human_review_required:
                    packet = build_review_packet(signal, decision)
                    review_packets_written += 1
                    if not packet.public_ready:
                        packet_public_ready_false += 1
                    if bool(packet.human_gate.get("required")):
                        packet_human_gate_required += 1
                    if not bool(packet.human_gate.get("confirmed")):
                        packet_human_gate_unconfirmed += 1
                    packet_writer.write(packet)
                    if len(html_packets) < html_limit:
                        html_packets.append(packet)
                trace_writer.write(
                    build_operation_trace(
                        run_id=run_id,
                        input_label_value=input_label_value,
                        input_descriptor=input_descriptor,
                        parser=parser,
                        profile=profile,
                        signal=signal,
                        decision=decision,
                        packet=packet,
                    )
                )
    except Exception:
        _clear_run_outputs(out_dir)
        raise

    html_packets_rendered = write_contact_sheet(out_dir / "contact_sheet.html", html_packets, max_packets=html_limit)
    write_summary(
        out_dir / "summary.md",
        assets_triaged=assets_triaged,
        review_packets_written=review_packets_written,
        html_packets_rendered=html_packets_rendered,
        lane_counts=lane_counts,
    )
    if source_gate_active:
        write_review_report(
            out_dir / "review_report.md",
            assets_triaged=assets_triaged,
            review_packets_written=review_packets_written,
            lane_counts=lane_counts,
            source_dependency_counts=source_dependency_counts,
            decision_basis_counts=decision_basis_counts,
            source_context_availability_counts=source_context_availability_counts,
            privacy_scope_counts=privacy_scope_counts,
        )
    if visual_evidence_active:
        write_visual_review_report(
            out_dir / "visual_review_report.md",
            assets_triaged=assets_triaged,
            review_packets_written=review_packets_written,
            images_existing=images_existing,
            lane_counts=lane_counts,
            risk_bucket_counts=risk_bucket_counts,
        )
    safety_checks = build_safety_checks(
        out_dir=out_dir,
        packets_written=review_packets_written,
        public_ready_false_count=packet_public_ready_false,
        human_gate_required_count=packet_human_gate_required,
        human_gate_unconfirmed_count=packet_human_gate_unconfirmed,
    )
    write_safety_checks(out_dir / "safety_checks.json", safety_checks)
    write_workflow_contract(out_dir / "workflow_contract.json", parser=parser, profile=profile, policy=policy)
    output_files = [
        filename for filename in RUN_OUTPUT_FILENAMES if filename == "run_manifest.json" or (out_dir / filename).exists()
    ]
    workflow_metrics = build_workflow_metrics(
        input_path=input_path,
        input_descriptor=input_descriptor,
        runtime_seconds=time.perf_counter() - started_at,
        input_rows=assets_triaged,
        review_packets=review_packets_written,
        operation_trace_rows=assets_triaged,
    )
    write_run_manifest(
        out_dir / "run_manifest.json",
        run_id=run_id,
        created_at=created_at,
        input_path=input_path,
        input_descriptor=input_descriptor,
        parser=parser,
        profile=profile,
        policy=policy,
        counts={
            "input_rows": assets_triaged,
            "review_packets": review_packets_written,
            "html_packets_rendered": html_packets_rendered,
        },
        outputs=output_files,
        workflow_metrics=workflow_metrics,
    )

    return {
        "assets_triaged": assets_triaged,
        "review_packets": review_packets_written,
        "html_packets_rendered": html_packets_rendered,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vulca-curator")
    subcommands = parser.add_subparsers(dest="command", required=True)
    triage = subcommands.add_parser("triage", help="Triages visual curation metadata into review lanes.")
    triage.add_argument("input_path", type=Path)
    triage.add_argument(
        "--parser",
        choices=["generic", "nemo", "cosmos", "vulca-source-gate", "vulca-visual-evidence"],
        default="generic",
    )
    triage.add_argument(
        "--profile",
        choices=[
            "dataset-curation",
            "creative-release",
            "generated-media-publishability",
            "source-gate-review",
            "visual-evidence-review",
        ],
        required=True,
    )
    triage.add_argument("--out", dest="out_dir", type=Path, required=True)
    triage.add_argument("--html-limit", dest="html_limit", type=int, default=1000)
    triage.add_argument("--policy-config", dest="policy_config_path", type=Path)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "triage":
        try:
            result = run_triage(
                input_path=args.input_path,
                parser=args.parser,
                profile=args.profile,
                out_dir=args.out_dir,
                html_limit=args.html_limit,
                policy_config_path=args.policy_config_path,
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Triaged {result['assets_triaged']} assets; wrote {result['review_packets']} review packets.")
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2
