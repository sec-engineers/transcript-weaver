"""Shared pipeline models and the versioned public packet contract."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from transcript_weaver import __version__
from transcript_weaver.runtime import generate_run_id, validate_run_id

SCHEMA_VERSION = 1
UTC_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ModelError(ValueError):
    """Raised when acquired data cannot form a valid packet."""


@dataclass(frozen=True, slots=True)
class Source:
    """Safe source identity included in a pipeline packet."""

    type: str
    name: str | None = None
    reference: str | None = None

    def as_dict(self) -> dict[str, str]:
        if not self.type.strip():
            raise ModelError("Source type cannot be empty.")
        result = {"type": self.type}
        if self.name:
            result["name"] = self.name
        if self.reference:
            result["reference"] = self.reference
        return result


@dataclass(frozen=True, slots=True)
class AcquiredTranscript:
    """Adapter-neutral acquisition result."""

    transcript: str
    recorded_at: datetime
    source: Source
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptPacket:
    """Schema v1 packet emitted by ``trwinp``."""

    recorded_at: datetime
    source: Source
    transcript: str
    run_id: str = field(default_factory=generate_run_id)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_acquired(
        cls, acquired: AcquiredTranscript, *, run_id: str | None = None
    ) -> TranscriptPacket:
        return cls(
            recorded_at=acquired.recorded_at,
            source=acquired.source,
            transcript=acquired.transcript,
            run_id=run_id or generate_run_id(),
            metadata=(
                {"duration_seconds": acquired.duration_seconds}
                if acquired.duration_seconds is not None
                else {}
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        text = self.transcript.strip()
        if not text:
            raise ModelError("Transcript is empty.")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ModelError("Transcript datetime must include timezone information.")
        duration = self.metadata.get("duration_seconds")
        if duration is not None and (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
        ):
            raise ModelError("Transcript duration_seconds must be a finite nonnegative number.")
        utc_value = self.recorded_at.astimezone(timezone.utc).replace(microsecond=0)
        return {
            "schema_version": SCHEMA_VERSION,
            "trw_version": __version__,
            "run": {"id": validate_run_id(self.run_id)},
            "datetime": utc_value.strftime(UTC_DATETIME_FORMAT),
            "source": self.source.as_dict(),
            "transcript": text,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        """Serialize deterministically with exactly one trailing newline."""
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n"
