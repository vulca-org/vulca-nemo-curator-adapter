from __future__ import annotations

from vulca_curator_adapter.schemas import CuratorSignal, ReviewPacket, TriageDecision


def _review_lens_for_lane(lane: str) -> list[str]:
    mapping = {
        "needs_source_context": ["source_context"],
        "needs_brand_review": ["brand_review"],
        "needs_cultural_review": ["cultural_review"],
        "needs_generated_media_review": ["generated_media_publishability"],
        "needs_source_dependency_review": ["source_dependency_review"],
        "needs_metadata_only_review": ["metadata_only_review"],
        "reviewed_source_dependency_label": ["source_dependency_label_review"],
        "needs_sensitive_or_person_rights_review": ["sensitive_or_person_rights_review"],
        "needs_rights_source_review": ["rights_source_review"],
        "needs_artwork_rights_review": ["artwork_rights_review"],
        "visual_evidence_review_required": ["visual_evidence_review"],
        "human_release_gate_required": ["release_gate"],
        "dataset_ok_not_publish_ready": ["release_gate"],
        "dataset_ok": ["dataset_curation"],
        "auto_drop": ["curation_filter"],
    }
    return mapping.get(lane, ["release_gate"])


def build_review_packet(signal: CuratorSignal, decision: TriageDecision) -> ReviewPacket:
    if signal.asset_id != decision.asset_id:
        raise ValueError("signal asset_id does not match decision asset_id")

    missing = sorted(set(signal.missing_fields + decision.missing_context))
    return ReviewPacket(
        asset_id=signal.asset_id,
        candidate_surface={
            "uri": signal.uri,
            "modality": signal.modality,
            "caption": signal.caption,
        },
        curator_signals={
            "aesthetic_score": signal.aesthetic_score,
            "nsfw_score": signal.nsfw_score,
            "duplicate_group": signal.duplicate_group,
            "curator_stage": signal.curator_stage,
        },
        source_trail={
            "source_url": signal.source_url,
            "embedding_ref": signal.embedding_ref,
        },
        review_lens=_review_lens_for_lane(decision.triage_lane),
        missing_fields=missing,
        owner_route=decision.recommended_owner,
        human_gate={
            "required": decision.human_review_required,
            "confirmed": False,
        },
        review_context=signal.review_context,
    )
