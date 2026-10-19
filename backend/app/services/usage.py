"""Token usage and prompt-cache accounting.

DeepSeek (and other providers) cache prompt prefixes automatically; cached input tokens
are much cheaper and faster. Every model call reports its usage here so the app can show
the cache hit rate and verify that prompts keep their cache-stable prefix (see
app.prompts for the layout rules).

Usage is aggregated in three places: per call (log line), per scope (e.g. one paper's
analysis: vision + reasoning calls), and globally (persisted in DATA_DIR/usage.json).
"""

import contextlib
import contextvars
import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, Optional

from app.config import DATA_DIR
from app.logging_config import get_logger

logger = get_logger("services.usage")

USAGE_FILE = DATA_DIR / "usage.json"


@dataclass
class Usage:
    requests: int = 0
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.requests += other.requests
        self.prompt_tokens += other.prompt_tokens
        self.cache_hit_tokens += other.cache_hit_tokens
        self.cache_miss_tokens += other.cache_miss_tokens
        self.completion_tokens += other.completion_tokens
        self.reasoning_tokens += other.reasoning_tokens

    @property
    def hit_rate(self) -> Optional[float]:
        known = self.cache_hit_tokens + self.cache_miss_tokens
        return self.cache_hit_tokens / known if known else None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["hit_rate"] = self.hit_rate
        return data


def usage_from_payload(payload: Any) -> Optional[Usage]:
    """Normalize an OpenAI-compatible `usage` object (DeepSeek or OpenAI cache fields)."""
    if payload is None:
        return None
    data = payload if isinstance(payload, dict) else (
        payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    )
    prompt = int(data.get("prompt_tokens") or 0)
    hit = data.get("prompt_cache_hit_tokens")
    miss = data.get("prompt_cache_miss_tokens")
    if hit is None:
        details = data.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if cached is not None:
            hit, miss = int(cached), max(0, prompt - int(cached))
    completion_details = data.get("completion_tokens_details") or {}
    reasoning = completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else 0
    # Providers that report no cache fields stay out of the hit rate (hit = miss = 0)
    return Usage(
        requests=1,
        prompt_tokens=prompt,
        cache_hit_tokens=int(hit or 0),
        cache_miss_tokens=int(miss or 0),
        completion_tokens=int(data.get("completion_tokens") or 0),
        reasoning_tokens=int(reasoning or 0),
    )


# --- scopes (per paper / per agent run) ---------------------------------------------

_scope: contextvars.ContextVar[Optional[Usage]] = contextvars.ContextVar("usage_scope", default=None)


@contextlib.contextmanager
def usage_scope() -> Iterator[Usage]:
    """Collect the usage of every model call made inside (incl. tasks spawned within)."""
    scope = Usage()
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        # A generator closed from another context (e.g. by GC) can't reset the token
        with contextlib.suppress(ValueError):
            _scope.reset(token)


# --- global totals -------------------------------------------------------------------

_lock = threading.Lock()
_totals: Dict[str, Usage] = {}
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(USAGE_FILE.read_text())
        for purpose, values in raw.get("by_purpose", {}).items():
            values.pop("hit_rate", None)
            _totals[purpose] = Usage(**values)
    except (OSError, ValueError, TypeError):
        pass


def _save() -> None:
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(
            {"by_purpose": {k: asdict(v) for k, v in _totals.items()}}, indent=1
        ))
    except OSError as e:
        logger.debug("Could not persist usage: %s", e)


def record(purpose: str, model: str, usage: Usage) -> None:
    scope = _scope.get()
    if scope is not None:
        scope.add(usage)
    with _lock:
        _load()
        _totals.setdefault(purpose, Usage()).add(usage)
        _save()
    rate = usage.hit_rate
    logger.info(
        "%s %s: prompt=%d (cache hit %d, %s) completion=%d",
        purpose, model, usage.prompt_tokens, usage.cache_hit_tokens,
        f"{rate:.0%}" if rate is not None else "n/a", usage.completion_tokens,
    )


def summary() -> Dict[str, Any]:
    with _lock:
        _load()
        total = Usage()
        for usage in _totals.values():
            total.add(usage)
        return {
            "total": total.to_dict(),
            "by_purpose": {k: v.to_dict() for k, v in _totals.items()},
        }


def reset() -> None:
    with _lock:
        _totals.clear()
        _save()
