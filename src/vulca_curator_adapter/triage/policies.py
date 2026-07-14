from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, ValidationError


@dataclass(frozen=True)
class PolicyProfile:
    name: str
    aesthetic_min: float
    nsfw_block: float
    require_source_for_release: bool
    generated_media_review: bool
    source_gate_review: bool = False
    visual_evidence_review: bool = False
    source: Literal["built-in", "config"] = "built-in"
    config_ref: Optional[str] = None


class PolicyConfigThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aesthetic_min: float
    nsfw_block: float


class PolicyConfigGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_source_for_release: bool
    generated_media_review: bool
    source_gate_review: bool = False
    visual_evidence_review: bool = False


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["vulca.policy.profile_config.v1"]
    profile: str
    config_ref: Optional[str] = None
    thresholds: PolicyConfigThresholds
    gates: PolicyConfigGates


_POLICIES: dict[str, PolicyProfile] = {
    "dataset-curation": PolicyProfile(
        name="dataset-curation",
        aesthetic_min=0.35,
        nsfw_block=0.8,
        require_source_for_release=False,
        generated_media_review=False,
    ),
    "creative-release": PolicyProfile(
        name="creative-release",
        aesthetic_min=0.25,
        nsfw_block=0.5,
        require_source_for_release=True,
        generated_media_review=True,
    ),
    "generated-media-publishability": PolicyProfile(
        name="generated-media-publishability",
        aesthetic_min=0.25,
        nsfw_block=0.5,
        require_source_for_release=True,
        generated_media_review=True,
    ),
    "source-gate-review": PolicyProfile(
        name="source-gate-review",
        aesthetic_min=0.0,
        nsfw_block=1.0,
        require_source_for_release=False,
        generated_media_review=False,
        source_gate_review=True,
    ),
    "visual-evidence-review": PolicyProfile(
        name="visual-evidence-review",
        aesthetic_min=0.0,
        nsfw_block=1.0,
        require_source_for_release=False,
        generated_media_review=False,
        visual_evidence_review=True,
    ),
}

POLICIES: Mapping[str, PolicyProfile] = MappingProxyType(_POLICIES)


def get_policy(name: str) -> PolicyProfile:
    try:
        return POLICIES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(POLICIES))
        raise ValueError(f"unknown policy profile {name!r}; expected one of: {valid}") from exc


def load_policy_config(path: Path, *, expected_profile: str) -> PolicyProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = PolicyConfig.model_validate(payload)
    except OSError as exc:
        raise ValueError(f"policy config not readable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"policy config is not valid JSON: {path}") from exc
    except ValidationError as exc:
        raise ValueError(f"policy config failed validation: {path}") from exc
    if config.profile != expected_profile:
        raise ValueError(
            f"policy config profile {config.profile!r} does not match requested profile {expected_profile!r}"
        )
    return PolicyProfile(
        name=config.profile,
        aesthetic_min=config.thresholds.aesthetic_min,
        nsfw_block=config.thresholds.nsfw_block,
        require_source_for_release=config.gates.require_source_for_release,
        generated_media_review=config.gates.generated_media_review,
        source_gate_review=config.gates.source_gate_review,
        visual_evidence_review=config.gates.visual_evidence_review,
        source="config",
        config_ref=config.config_ref or path.name,
    )
