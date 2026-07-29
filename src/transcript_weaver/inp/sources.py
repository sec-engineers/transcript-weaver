"""Standard input and text-file adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from transcript_weaver.inp.errors import SourceUnavailableError, TranscriptNotFoundError
from transcript_weaver.models import AcquiredTranscript, Source


class StdinSource:
    def __init__(
        self,
        stream: TextIO,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stream = stream
        self._clock = clock or (lambda: datetime.now().astimezone())

    def acquire(self) -> AcquiredTranscript:
        text = self._stream.read()
        if not text.strip():
            raise TranscriptNotFoundError("Standard input did not contain a transcript.")
        return AcquiredTranscript(
            transcript=text,
            recorded_at=self._clock(),
            source=Source(type="stdin", name="standard input"),
        )


class FileSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    def acquire(self) -> AcquiredTranscript:
        try:
            if not self._path.exists():
                raise SourceUnavailableError(f"Transcript file does not exist: {self._path}")
            if not self._path.is_file():
                raise SourceUnavailableError(f"Transcript path is not a file: {self._path}")
            text = self._path.read_text(encoding="utf-8")
            modified = self._path.stat().st_mtime
        except UnicodeDecodeError as exc:
            raise SourceUnavailableError(
                f"Transcript file is not valid UTF-8: {self._path}"
            ) from exc
        except OSError as exc:
            raise SourceUnavailableError(f"Could not read transcript file: {self._path}") from exc

        if not text.strip():
            raise TranscriptNotFoundError(f"Transcript file is empty: {self._path}")

        return AcquiredTranscript(
            transcript=text,
            recorded_at=datetime.fromtimestamp(modified).astimezone(),
            source=Source(
                type="file",
                name=self._path.name,
                reference=str(self._path.resolve()),
            ),
        )
