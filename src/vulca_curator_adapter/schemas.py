from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


Modality = Literal["image", "video", "frame", "case"]


class CuratorSignal(BaseModel):
    """Tolerant normalized view of upstream visual curation metadata."""

    model_config = ConfigDict(extra="allow")

    asset_id: str
    uri: str
    modality: Modality
    source_url: Optional[str] = None
    caption: Optional[str] = None
    aesthetic_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    nsfw_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    duplicate_group: Optional[str] = None
    embedding_ref: Optional[str] = None
    curator_stage: Optional[str] = None
    curator_metadata: dict[str, Any] = Field(default_factory=dict)
    review_context: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    public_ready: bool = False

    @model_validator(mode="after")
    def collect_missing_and_extra(self) -> "CuratorSignal":
        extras = self.model_extra or {}
        if extras:
            self.curator_metadata.update(extras)
        missing: list[str] = []
        if self.modality != "case" and not self.source_url:
            missing.append("source_url")
        if not self.caption:
            missing.append("caption")
        self.missing_fields = missing
        self.public_ready = False
        return self


class TriageDecision(BaseModel):
    """Lightweight policy result for one asset."""

    asset_id: str
    triage_lane: str
    why_this_lane: list[str] = Field(default_factory=list)
    human_review_required: bool
    public_ready: bool = False
    missing_context: list[str] = Field(default_factory=list)
    recommended_owner: list[str] = Field(default_factory=list)
    escalation_reason: Optional[str] = None


class ReviewPacket(BaseModel):
    """Human-facing review object generated after triage."""

    asset_id: str
    candidate_surface: dict[str, Any]
    curator_signals: dict[str, Any]
    source_trail: dict[str, Any]
    review_lens: list[str]
    missing_fields: list[str]
    owner_route: list[str]
    human_gate: dict[str, Any]
    review_context: dict[str, Any] = Field(default_factory=dict)
    public_ready: bool = False


class FieldContract(BaseModel):
    """Named field requirements for a workflow-stage contract."""

    model_config = ConfigDict(extra="forbid")

    required_fields: list[str]
    optional_fields: list[str] = Field(default_factory=list)


class ReleaseReadinessOutputContract(BaseModel):
    """Output requirements produced by the release-readiness task."""

    model_config = ConfigDict(extra="forbid")

    required_fields: list[str]
    public_ready_default: bool = False
    human_gate_required: bool = True


class ReleaseReadinessTaskContract(BaseModel):
    """Input and output contract for one release-readiness task batch."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vulca.contract.release_readiness_task.v1"]
    input_contract: FieldContract
    output_contract: ReleaseReadinessOutputContract


class PolicyThresholds(BaseModel):
    """Numeric threshold values used by a policy profile."""

    model_config = ConfigDict(extra="forbid")

    aesthetic_min: float
    nsfw_block: float


class PolicyGates(BaseModel):
    """Boolean policy gates used by a release-readiness profile."""

    model_config = ConfigDict(extra="forbid")

    require_source_for_release: bool
    generated_media_review: bool
    source_gate_review: bool
    visual_evidence_review: bool


class PolicyProfileContract(BaseModel):
    """Contract representation of the selected policy profile."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vulca.contract.policy_profile.v1"]
    name: str
    source: Literal["built-in", "config"] = "built-in"
    config_ref: Optional[str] = None
    thresholds: PolicyThresholds
    gates: PolicyGates


class WorkflowResultsContract(BaseModel):
    """Expected artifacts emitted by the workflow stage."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vulca.contract.workflow_results.v1"]
    artifacts: list[str]


class SafetyBoundaryContract(BaseModel):
    """Safety defaults for the release-readiness stage."""

    model_config = ConfigDict(extra="forbid")

    public_ready_default: bool = False
    human_gate_required: bool = True
    human_gate_confirmed_default: bool = False
    external_demo_requires_redaction: bool = True


class WorkflowContract(BaseModel):
    """Validated contract for one release-readiness workflow run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vulca.contract.workflow_contract.v1"]
    stage_name: Literal["ReleaseReadinessStage"]
    parser: str
    profile: str
    release_readiness_task: ReleaseReadinessTaskContract
    policy_profile: PolicyProfileContract
    workflow_results: WorkflowResultsContract
    safety_boundary: SafetyBoundaryContract
