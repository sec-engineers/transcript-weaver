"""Input-stage exceptions and stable exit statuses."""

from enum import IntEnum


class ExitStatus(IntEnum):
    OK = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    SOURCE_UNAVAILABLE = 3
    TRANSCRIPT_NOT_FOUND = 4
    AUTH_REQUIRED = 5


class InputError(RuntimeError):
    status = ExitStatus.GENERAL_ERROR


class SourceUnavailableError(InputError):
    status = ExitStatus.SOURCE_UNAVAILABLE


class TranscriptNotFoundError(InputError):
    status = ExitStatus.TRANSCRIPT_NOT_FOUND


class AuthenticationRequiredError(InputError):
    status = ExitStatus.AUTH_REQUIRED
