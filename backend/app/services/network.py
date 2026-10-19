"""Process-wide network settings.

A Finder-launched app doesn't inherit shell proxy variables, so the optional proxy from
settings is exported into the environment, where httpx (MinerU, PDF download), the openai
SDK and the arxiv library (requests) all pick it up.
"""

import os

from app.logging_config import get_logger

logger = get_logger("services.network")

USER_AGENT = "PaperInsight/0.2 (macOS desktop; arXiv paper tracker)"

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_original_env = {name: os.environ.get(name) for name in (*_PROXY_VARS, "NO_PROXY", "no_proxy")}
_LOCAL_HOSTS = "127.0.0.1,localhost,::1"


def apply_proxy(proxy_url: str) -> None:
    proxy_url = (proxy_url or "").strip()
    if proxy_url:
        for name in _PROXY_VARS:
            os.environ[name] = proxy_url
        logger.info("Using proxy %s", proxy_url)
    else:
        for name in _PROXY_VARS:
            if _original_env[name] is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = _original_env[name]

    # Local services (our API, local MinerU, Ollama) must never go through a proxy
    for name in ("NO_PROXY", "no_proxy"):
        existing = _original_env[name]
        os.environ[name] = f"{existing},{_LOCAL_HOSTS}" if existing else _LOCAL_HOSTS
