"""Pure point-in-time ST status resolution for the limit-up ladder."""

from __future__ import annotations

import re
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


_ST_NAME_PREFIX = re.compile(r"^(?:S\*?ST|\*?ST)", re.IGNORECASE)


def resolve_point_in_time_st(
    *,
    name: str | None,
    accurate_is_st: bool | None = None,
    accurate_source: str | None = None,
    accurate_source_ref: str | None = None,
) -> PointInTimeSTStatus:
    """Prefer an authoritative daily fact and otherwise fall back to name inference.

    The fallback is always labelled ``approximate``. An authoritative value without
    a source is rejected so downstream code cannot present an untraceable fact as
    accurate.
    """
    if accurate_is_st is not None:
        source = (accurate_source or "").strip()
        if not source:
            raise ValueError("accurate ST status requires accurate_source")
        return PointInTimeSTStatus(
            is_st=bool(accurate_is_st),
            source=source,
            source_ref=accurate_source_ref,
            quality=STStatusQuality.ACCURATE,
        )

    normalized_name = (name or "").strip()
    return PointInTimeSTStatus(
        is_st=bool(_ST_NAME_PREFIX.match(normalized_name)),
        source="stock_name",
        source_ref=normalized_name or None,
        quality=STStatusQuality.APPROXIMATE,
    )
