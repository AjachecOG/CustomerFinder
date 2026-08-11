"""Application error hierarchy and exit codes."""

from __future__ import annotations


class ExitCode:
    """CLI process exit codes from the implementation plan."""

    SUCCESS = 0
    UNEXPECTED = 1
    BAD_ARGS = 2
    CONFIG = 3
    OVERTURE = 4
    GOOGLE_STRICT = 5
    OUTPUT = 6


class CustomerFinderError(Exception):
    """Base error with a stable exit code."""

    exit_code: int = ExitCode.UNEXPECTED

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ArgumentError(CustomerFinderError):
    """Invalid CLI arguments or SearchRequest validation failure."""

    exit_code = ExitCode.BAD_ARGS


class ConfigError(CustomerFinderError):
    """Invalid YAML, missing config files, or missing Google API key."""

    exit_code = ExitCode.CONFIG

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        field: str | None = None,
    ) -> None:
        parts: list[str] = []
        if path is not None:
            parts.append(f"path={path}")
        if field is not None:
            parts.append(f"field={field}")
        detail = f" ({', '.join(parts)})" if parts else ""
        super().__init__(f"{message}{detail}")
        self.path = path
        self.field = field


class OvertureError(CustomerFinderError):
    """STAC, DuckDB, or Overture schema failures."""

    exit_code = ExitCode.OVERTURE


class GoogleEnrichmentError(CustomerFinderError):
    """Required Google enrichment failed under strict mode."""

    exit_code = ExitCode.GOOGLE_STRICT


class OutputError(CustomerFinderError):
    """Result file write / filesystem failures."""

    exit_code = ExitCode.OUTPUT
