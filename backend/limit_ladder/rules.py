"""Pure point-in-time ST status resolution for the limit-up ladder."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class STStatusQuality(StrEnum):
    ACCURATE = "accurate"
    APPROXIMATE = "approximate"


@dataclass(frozen=True, slots=True)
class PointInTimeSTStatus:
    """Resolved ST status with provenance that must survive snapshot materialization."""

    is_st: bool
    source: str
    source_ref: str | None
    quality: STStatusQuality
