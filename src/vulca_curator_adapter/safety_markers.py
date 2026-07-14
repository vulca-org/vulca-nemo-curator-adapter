from __future__ import annotations


def marker(*parts: str) -> str:
    return "".join(parts)


USER_HOME_PATH = marker("/", "Users", "/")
USER_HOME_PATH_LOWER = USER_HOME_PATH.lower()
INTERNAL_REVIEW_STATUS = marker("internal", "_", "review", "_", "only")
VISUAL_INTERNAL_TERM = marker("show", "case")
DO_NOT_SEND_EXTERNALLY = marker("do not ", "send ", "externally")
PRIVATE_LOCAL_PATH = marker("private ", "local ", "path")
OFFICIAL_COMPATIBILITY = marker("official ", "compatibility")
OFFICIAL_NVIDIA_COMPATIBILITY = marker("official ", "nvidia ", "compatibility")
NVIDIA_ENDORSED = marker("nvidia ", "endorsed")
NVIDIA_CERTIFIED_HYPHENATED = marker("nvidia", "-", "certified")
NVIDIA_CERTIFIED = marker("nvidia ", "certified")
PARTNERED_WITH_NVIDIA = marker("partnered ", "with ", "nvidia")
NVIDIA_PARTNERSHIP = marker("nvidia ", "partnership")
COMPATIBLE_WITH_OFFICIAL_NVIDIA_EXPORTS = marker(
    "compatible ",
    "with ",
    "official ",
    "nvidia ",
    "exports",
)
CANDIDATE_SURFACE_FIELD = marker("candidate", "_", "surface")
HUMAN_GATE_FIELD = marker("human", "_", "gate")
