from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from vulca_curator_adapter.ingest.generic_jsonl import InputDescriptor, ParserName
from vulca_curator_adapter.safety_markers import (
    CANDIDATE_SURFACE_FIELD,
    HUMAN_GATE_FIELD,
    INTERNAL_REVIEW_STATUS,
    USER_HOME_PATH_LOWER,
    VISUAL_INTERNAL_TERM,
)
from vulca_curator_adapter.schemas import CuratorSignal, ReviewPacket, TriageDecision, WorkflowContract
from vulca_curator_adapter.triage.policies import PolicyProfile


WORKFLOW_SURFACE = "Curator-like metadata -> release-readiness stage -> review packet -> human gate -> audit evidence"
RUN_MANIFEST_SCHEMA = "vulca.evidence.run_manifest.v1"
OPERATION_TRACE_SCHEMA = "vulca.evidence.operation_trace.v1"
SAFETY_CHECKS_SCHEMA = "vulca.evidence.safety_checks.v1"
WORKFLOW_CONTRACT_SCHEMA = "vulca.contract.workflow_contract.v1"
RELEASE_READINESS_TASK_SCHEMA = "vulca.contract.release_readiness_task.v1"
POLICY_PROFILE_SCHEMA = "vulca.contract.policy_profile.v1"
WORKFLOW_RESULTS_SCHEMA = "vulca.contract.workflow_results.v1"
WORKFLOW_RUN_METRICS_SCHEMA = "vulca.metrics.workflow_run.v1"
BLOCKED_PUBLIC_TERMS = (
    USER_HOME_PATH_LOWER,
    INTERNAL_REVIEW_STATUS,
    "<script",
    VISUAL_INTERNAL_TERM,
    CANDIDATE_SURFACE_FIELD,
    HUMAN_GATE_FIELD,
)


def build_contract_refs() -> dict[str, str]:
    return {
        "release_readiness_task": RELEASE_READINESS_TASK_SCHEMA,
        "policy_profile": POLICY_PROFILE_SCHEMA,
        "workflow_results": WORKFLOW_RESULTS_SCHEMA,
    }


def build_policy_config_summary(policy: PolicyProfile) -> dict[str, Any]:
    summary = {
        "source": policy.source,
        "config_ref": policy.config_ref,
    }
    if policy.source == "config":
        summary["schema_version"] = "vulca.policy.profile_config.v1"
    return summary


def build_workflow_contract(*, parser: ParserName, profile: str, policy: PolicyProfile) -> dict[str, Any]:
    contract = {
        "schema_version": WORKFLOW_CONTRACT_SCHEMA,
        "stage_name": "ReleaseReadinessStage",
        "parser": parser,
        "profile": profile,
        "release_readiness_task": {
            "schema_version": RELEASE_READINESS_TASK_SCHEMA,
            "input_contract": {
                "required_fields": ["asset_id", "uri", "modality"],
                "optional_fields": [
                    "source_url",
                    "caption",
                    "aesthetic_score",
                    "nsfw_score",
                    "duplicate_group",
                    "embedding_ref",
                    "curator_stage",
                    "curator_metadata",
                    "review_context",
                ],
            },
            "output_contract": {
                "required_fields": [
                    "asset_id",
                    "triage_lane",
                    "review_lens",
                    "owner_route",
                    "human_gate",
                    "public_ready",
                ],
                "public_ready_default": False,
                "human_gate_required": True,
            },
        },
        "policy_profile": {
            "schema_version": POLICY_PROFILE_SCHEMA,
            "name": policy.name,
            "source": policy.source,
            "config_ref": policy.config_ref,
            "thresholds": {
                "aesthetic_min": policy.aesthetic_min,
                "nsfw_block": policy.nsfw_block,
            },
            "gates": {
                "require_source_for_release": policy.require_source_for_release,
                "generated_media_review": policy.generated_media_review,
                "source_gate_review": policy.source_gate_review,
                "visual_evidence_review": policy.visual_evidence_review,
            },
        },
        "workflow_results": {
            "schema_version": WORKFLOW_RESULTS_SCHEMA,
            "artifacts": [
                "triage.jsonl",
                "review_packets.jsonl",
                "operation_trace.jsonl",
                "safety_checks.json",
                "run_manifest.json",
            ],
        },
        "safety_boundary": {
            "public_ready_default": False,
            "human_gate_required": True,
            "human_gate_confirmed_default": False,
            "external_demo_requires_redaction": True,
        },
    }
    return WorkflowContract.model_validate(contract).model_dump(mode="json")


def write_workflow_contract(path: Path, *, parser: ParserName, profile: str, policy: PolicyProfile) -> dict[str, Any]:
    contract = build_workflow_contract(parser=parser, profile=profile, policy=policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return contract


def build_upstream_integration_surface(input_descriptor: InputDescriptor) -> dict[str, Any]:
    executor_type = input_descriptor["executor_type"]
    if executor_type == "local_jsonl_cli":
        executor_label = "local JSONL CLI executor"
    elif executor_type == "local_parquet_cli":
        executor_label = "local Parquet CLI executor"
    else:
        raise ValueError(f"unsupported executor_type: {executor_type}")

    return {
        "surface_name": "release-readiness-stage",
        "placement": "after curation export/write stage and before enterprise release review",
        "nvidia_style_components": {
            "task": {
                "input": "curated metadata task or exported record batch",
                "output": "release-readiness task with review packet references",
            },
            "stage": {
                "name": "ReleaseReadinessStage",
                "input_contract": "Curator-like metadata records with asset id, URI, scores, source fields, and optional review context",
                "output_contract": "review packet artifacts, operation traces, safety checks, and run manifest",
            },
            "pipeline": {
                "upstream": [
                    "load",
                    "filter",
                    "deduplicate",
                    "classify",
                    "transform",
                    "export/write",
                ],
                "downstream": [
                    "review packet artifacts",
                    "human gate decision records",
                    "audit evidence ledger",
                ],
            },
            "executor": {
                "current": executor_label,
                "future": "pipeline executor handoff compatible with Ray, Dagster, or OpenLineage-style orchestration",
            },
            "workflow_results": [
                "run_manifest.json",
                "operation_trace.jsonl",
                "safety_checks.json",
                "review_packets.jsonl",
            ],
        },
        "non_goals": [
            "filtering",
            "deduplication",
            "embedding",
            "captioning",
            "training",
            "GPU acceleration",
            "NVIDIA official export compatibility claim",
        ],
    }


def new_run_id() -> str:
    return f"vulca-run-{uuid4().hex[:12]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def input_label(path: Path) -> str:
    return path.name


def input_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_workflow_metrics(
    *,
    input_path: Path,
    input_descriptor: InputDescriptor,
    runtime_seconds: float,
    input_rows: int,
    review_packets: int,
    operation_trace_rows: int,
) -> dict[str, Any]:
    measured_runtime = max(float(runtime_seconds), 0.000001)
    return {
        "schema_version": WORKFLOW_RUN_METRICS_SCHEMA,
        "benchmark_mode": input_descriptor["benchmark_mode"],
        "executor_type": input_descriptor["executor_type"],
        "gpu_scale_benchmark": False,
        "input_bytes": input_path.stat().st_size,
        "operation_trace_rows": operation_trace_rows,
        "runtime_seconds": round(measured_runtime, 6),
        "rows_per_second": round(input_rows / measured_runtime, 3) if input_rows else 0.0,
        "packets_per_second": round(review_packets / measured_runtime, 3) if review_packets else 0.0,
    }


def build_operation_trace(
    *,
    run_id: str,
    input_label_value: str,
    input_descriptor: InputDescriptor,
    parser: ParserName,
    profile: str,
    signal: CuratorSignal,
    decision: TriageDecision,
    packet: ReviewPacket | None,
) -> dict[str, Any]:
    packet_written = packet is not None
    input_format = input_descriptor["input_format"]
    if input_format == "jsonl":
        adapter_contract = None
        parquet_provenance = None
        metadata_parse_status = None
    elif input_format == "parquet":
        adapter_contract = input_descriptor.get("adapter_contract")
        if not isinstance(adapter_contract, str) or not adapter_contract:
            raise ValueError("Parquet input descriptor must include adapter_contract")
        if signal.curator_metadata.get("adapter_contract") != adapter_contract:
            raise ValueError("Parquet signal adapter_contract does not match input descriptor")

        parquet_provenance = signal.curator_metadata.get("parquet_provenance")
        if not isinstance(parquet_provenance, dict):
            raise ValueError("Parquet signal parquet_provenance must be an object")
        if parquet_provenance.get("sidecar") != input_label_value:
            raise ValueError("Parquet signal parquet_provenance sidecar does not match input label")
        row_number = parquet_provenance.get("row_number")
        if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number <= 0:
            raise ValueError("Parquet signal parquet_provenance row_number must be a positive integer")

        metadata_parse_status = signal.curator_metadata.get("metadata_parse_status")
        if metadata_parse_status not in {"empty", "not_mapping", "oversize", "parsed", "unparsed"}:
            raise ValueError(f"Parquet signal metadata_parse_status is not recognized: {metadata_parse_status}")
    else:
        raise ValueError(f"unsupported input format: {input_format}")

    return {
        "schema_version": OPERATION_TRACE_SCHEMA,
        "run_id": run_id,
        "workflow_stage": "release-readiness",
        "input_label": input_label_value,
        "parser": parser,
        "profile": profile,
        "asset_id": signal.asset_id,
        "normalized_signal": {
            "modality": signal.modality,
            "curator_stage": signal.curator_stage,
            "has_source_url": bool(signal.source_url),
            "missing_fields": signal.missing_fields,
            "public_ready": signal.public_ready,
            "adapter_contract": adapter_contract,
            "parquet_provenance": parquet_provenance,
            "metadata_parse_status": metadata_parse_status,
        },
        "triage_decision": {
            "triage_lane": decision.triage_lane,
            "why_this_lane": decision.why_this_lane,
            "human_review_required": decision.human_review_required,
            "missing_context": decision.missing_context,
            "recommended_owner": decision.recommended_owner,
        },
        "review_packet": {
            "written": packet_written,
            "review_lens": packet.review_lens if packet else [],
            "owner_route": packet.owner_route if packet else [],
            "missing_fields": packet.missing_fields if packet else [],
            "human_gate": packet.human_gate if packet else {},
            "public_ready": packet.public_ready if packet else False,
        },
        "contract_refs": build_contract_refs(),
        "output_artifacts": {
            "triage": "triage.jsonl",
            "review_packet": "review_packets.jsonl" if packet_written else None,
        },
    }


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _blocked_matches(text: str, terms: tuple[str, ...] = BLOCKED_PUBLIC_TERMS) -> list[str]:
    lower = text.lower()
    return sorted({term for term in terms if term in lower})


def build_safety_checks(
    *,
    out_dir: Path,
    packets_written: int,
    public_ready_false_count: int,
    human_gate_required_count: int,
    human_gate_unconfirmed_count: int,
) -> dict[str, Any]:
    html = _read_text_if_exists(out_dir / "contact_sheet.html")
    combined = "\n".join(
        _read_text_if_exists(out_dir / filename)
        for filename in ("summary.md", "contact_sheet.html", "review_report.md", "visual_review_report.md")
    )
    private_matches = _blocked_matches(combined, (USER_HOME_PATH_LOWER,))
    public_term_matches = _blocked_matches(combined)
    checks = {
        "private_path_scan": {
            "passed": not private_matches,
            "matches": private_matches,
        },
        "blocked_public_term_scan": {
            "passed": not public_term_matches,
            "matches": public_term_matches,
        },
        "html_script_scan": {
            "passed": "<script" not in html.lower(),
            "matches": ["<script"] if "<script" in html.lower() else [],
        },
        "html_img_scan": {
            "passed": "<img" not in html.lower(),
            "matches": ["<img"] if "<img" in html.lower() else [],
        },
        "html_table_scan": {
            "passed": "<table" not in html.lower(),
            "matches": ["<table"] if "<table" in html.lower() else [],
        },
        "public_ready_false": {
            "passed": public_ready_false_count == packets_written,
            "count": public_ready_false_count,
            "expected": packets_written,
        },
        "human_gate_required": {
            "passed": human_gate_required_count == packets_written,
            "count": human_gate_required_count,
            "expected": packets_written,
        },
        "human_gate_unconfirmed": {
            "passed": human_gate_unconfirmed_count == packets_written,
            "count": human_gate_unconfirmed_count,
            "expected": packets_written,
        },
    }
    return {
        "schema_version": SAFETY_CHECKS_SCHEMA,
        "external_ready": False,
        "note": "CLI contact sheets are QA artifacts; external pages must be built from redacted aggregate evidence.",
        "checks": checks,
    }


def write_safety_checks(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_run_manifest(
    path: Path,
    *,
    run_id: str,
    created_at: str,
    input_path: Path,
    input_descriptor: InputDescriptor,
    parser: ParserName,
    profile: str,
    policy: PolicyProfile,
    counts: dict[str, int],
    outputs: list[str],
    workflow_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "run_id": run_id,
        "created_at": created_at,
        "workflow_surface": WORKFLOW_SURFACE,
        "stage_name": "release-readiness",
        "upstream_integration_surface": build_upstream_integration_surface(input_descriptor),
        "contract": {
            "artifact": "workflow_contract.json",
            "schema_version": WORKFLOW_CONTRACT_SCHEMA,
            "stage_name": "ReleaseReadinessStage",
        },
        "policy_config": build_policy_config_summary(policy),
        "parser": parser,
        "profile": profile,
        "input": {
            "label": input_label(input_path),
            "sha256": input_sha256(input_path),
            **input_descriptor,
        },
        "counts": counts,
        "workflow_metrics": workflow_metrics
        or build_workflow_metrics(
            input_path=input_path,
            input_descriptor=input_descriptor,
            runtime_seconds=0.000001,
            input_rows=int(counts.get("input_rows", 0)),
            review_packets=int(counts.get("review_packets", 0)),
            operation_trace_rows=int(counts.get("input_rows", 0)),
        ),
        "outputs": outputs,
        "safety_boundary": {
            "external_ready": False,
            "public_ready_default": False,
            "human_gate_required": True,
            "external_demo_requires_redaction": True,
        },
        "git": {
            "commit": git_commit(),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
