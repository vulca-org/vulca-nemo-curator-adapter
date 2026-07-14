from __future__ import annotations

from vulca_curator_adapter.schemas import CuratorSignal, TriageDecision
from vulca_curator_adapter.triage.policies import PolicyProfile


def decide(signal: CuratorSignal, policy: PolicyProfile) -> TriageDecision:
    if policy.visual_evidence_review:
        context = signal.review_context
        risk_bucket = context.get("risk_bucket")

        if risk_bucket in {"celebrity_or_living_person", "news_sensitive"}:
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_sensitive_or_person_rights_review",
                why_this_lane=[f"risk_bucket={risk_bucket}"],
                human_review_required=True,
                recommended_owner=["rights_reviewer", "sensitive_content_reviewer", "review_owner"],
                escalation_reason="visual evidence contains sensitive or person-rights review risk",
            )

        if risk_bucket == "artwork_rights_review":
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_artwork_rights_review",
                why_this_lane=["risk_bucket=artwork_rights_review"],
                human_review_required=True,
                recommended_owner=["rights_reviewer", "review_owner"],
                escalation_reason="artwork rights and source attribution need review before external use",
            )

        if risk_bucket == "needs_source_context":
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_source_context",
                why_this_lane=["risk_bucket=needs_source_context"],
                human_review_required=True,
                missing_context=["public_source_attribution"],
                recommended_owner=["source_owner", "review_owner"],
                escalation_reason="public source attribution is unresolved",
            )

        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="visual_evidence_review_required",
            why_this_lane=[f"risk_bucket={risk_bucket or 'unspecified'}"],
            human_review_required=True,
            recommended_owner=["visual_reviewer", "review_owner"],
            escalation_reason="visual evidence requires internal review before external use",
        )

    if policy.source_gate_review:
        context = signal.review_context
        source_dependency = context.get("source_dependency")
        decision_basis = context.get("decision_basis")
        source_context_available = context.get("source_context_available")

        if source_dependency == "required" and not source_context_available:
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_source_context",
                why_this_lane=["source_dependency required but source_context is unavailable"],
                human_review_required=True,
                missing_context=["source_context"],
                recommended_owner=["source_owner", "review_owner"],
                escalation_reason="source context is required before review can be trusted",
            )

        if source_dependency == "required":
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_source_dependency_review",
                why_this_lane=["source_dependency required"],
                human_review_required=True,
                recommended_owner=["source_dependency_reviewer", "review_owner"],
                escalation_reason="decision depends on source context and needs review",
            )

        if decision_basis == "metadata_only":
            return TriageDecision(
                asset_id=signal.asset_id,
                triage_lane="needs_metadata_only_review",
                why_this_lane=["decision_basis is metadata_only"],
                human_review_required=True,
                recommended_owner=["metadata_reviewer", "review_owner"],
                escalation_reason="metadata-only decision needs internal review boundary",
            )

        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="reviewed_source_dependency_label",
            why_this_lane=["source dependency label is reviewed"],
            human_review_required=True,
            recommended_owner=["review_owner"],
            escalation_reason="internal review packet keeps human confirmation explicit",
        )

    if signal.nsfw_score is not None and signal.nsfw_score >= policy.nsfw_block:
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="auto_drop",
            why_this_lane=[f"nsfw_score above or equal to {policy.nsfw_block}"],
            human_review_required=False,
            escalation_reason="blocked by upstream safety threshold",
        )

    if signal.aesthetic_score is not None and signal.aesthetic_score < policy.aesthetic_min:
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="auto_drop" if policy.name == "dataset-curation" else "dataset_ok_not_publish_ready",
            why_this_lane=[f"aesthetic_score below {policy.aesthetic_min}"],
            human_review_required=False if policy.name == "dataset-curation" else True,
            escalation_reason="low curation score",
        )

    if policy.require_source_for_release and "source_url" in signal.missing_fields:
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_source_context",
            why_this_lane=["source_url missing"],
            human_review_required=True,
            missing_context=["source_url"],
            recommended_owner=["source_owner", "release_owner"],
            escalation_reason="release context missing",
        )

    metadata = signal.curator_metadata
    if metadata.get("person_rights_context"):
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_sensitive_or_person_rights_review",
            why_this_lane=["person_rights_context flag present"],
            human_review_required=True,
            recommended_owner=["rights_reviewer", "release_owner"],
            escalation_reason="person rights risk cannot be resolved from score metadata",
        )

    if metadata.get("rights_source_context"):
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_rights_source_review",
            why_this_lane=["rights_source_context flag present"],
            human_review_required=True,
            missing_context=["public_source_attribution"],
            recommended_owner=["rights_reviewer", "source_owner", "release_owner"],
            escalation_reason="rights and source attribution need review before external release",
        )

    if policy.generated_media_review and metadata.get("generated_media"):
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_generated_media_review",
            why_this_lane=["generated_media flag present"],
            human_review_required=True,
            missing_context=["label_posture"] if metadata.get("label_posture") == "missing" else [],
            recommended_owner=["creative_ops", "release_owner"],
            escalation_reason="generated media requires publishability review",
        )

    if metadata.get("brand_context"):
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_brand_review",
            why_this_lane=["brand_context flag present"],
            human_review_required=True,
            recommended_owner=["brand_owner", "release_owner"],
            escalation_reason="brand fit cannot be resolved from score metadata",
        )

    if metadata.get("cultural_context"):
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="needs_cultural_review",
            why_this_lane=["cultural_context flag present"],
            human_review_required=True,
            recommended_owner=["cultural_reviewer", "release_owner"],
            escalation_reason="cultural fit cannot be resolved from score metadata",
        )

    if policy.name == "dataset-curation":
        return TriageDecision(
            asset_id=signal.asset_id,
            triage_lane="dataset_ok",
            why_this_lane=["curation scores pass dataset thresholds"],
            human_review_required=False,
        )

    return TriageDecision(
        asset_id=signal.asset_id,
        triage_lane="human_release_gate_required",
        why_this_lane=["asset may be usable but release decision is unresolved"],
        human_review_required=True,
        recommended_owner=["release_owner"],
        escalation_reason="release decision cannot be resolved from curation scores",
    )
