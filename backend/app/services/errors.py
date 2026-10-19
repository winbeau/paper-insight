"""Typed pipeline errors. `code` is sent to the frontend as the SSE error code."""

from typing import Literal

ErrorCode = Literal[
    "config_error",      # missing/invalid model, provider, key or MinerU setup
    "download_error",    # PDF download failed
    "parse_error",       # MinerU failed
    "llm_error",         # model call failed or returned unusable output
    "timeout",
    "rate_limit",
    "entity_too_large",
    "busy",              # the paper is already being processed by another run
    "interrupted",       # the run was cancelled (client disconnect / app quit)
    "stopped",           # stopped by the user ("stop all"); the paper goes back to pending
    "unknown",
]


class PipelineError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message
