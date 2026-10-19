"""Validated settings schemas: model providers and the per-step pipeline config."""

import uuid
from datetime import datetime
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.models import AppSettings

MASK_PREFIX = "••••"

# Out-of-the-box setup: DeepSeek-V4.1-Flash (API id "deepseek-flash", text + image input)
# for both the reasoning and the vision step — the user only has to enter an API key.
DEFAULT_PROVIDER_ID = "deepseek"
DEFAULT_MODEL = "deepseek-flash"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")


# --- Model providers (OpenAI-compatible endpoints) ---------------------------------


class Provider(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    # Send response_format={"type": "json_object"} for the analysis step.
    # Off by default: many gateways reject it for reasoning models.
    json_mode: bool = False

    @property
    def needs_api_key(self) -> bool:
        """Remote endpoints need a key; local servers (Ollama, LM Studio) don't."""
        host = urlsplit(self.base_url).hostname or ""
        return not self.api_key and host not in LOCAL_HOSTS and not host.endswith(".local")


def default_providers() -> List[Provider]:
    return [Provider(id=DEFAULT_PROVIDER_ID, name="DeepSeek", base_url="https://api.deepseek.com")]


# --- Pipeline steps ----------------------------------------------------------------


class MineruCloudConfig(BaseModel):
    token: str = ""
    model_version: Literal["vlm", "pipeline"] = "vlm"
    is_ocr: bool = False
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "en"


class MineruLocalConfig(BaseModel):
    # managed: the app installs MinerU + pulls checkpoints into its data dir and runs the server
    # external: an already-running `mineru-kit api-server` (e.g. on a GPU box)
    mode: Literal["managed", "external"] = "managed"
    tier: Literal["basic", "standard"] = "standard"
    source: Literal["huggingface", "modelscope"] = "huggingface"
    external_url: str = "http://127.0.0.1:8000"
    external_api_key: str = ""


class ParserConfig(BaseModel):
    engine: Literal["mineru_cloud", "mineru_local"] = "mineru_local"
    cloud: MineruCloudConfig = Field(default_factory=MineruCloudConfig)
    local: MineruLocalConfig = Field(default_factory=MineruLocalConfig)


class ModelRef(BaseModel):
    provider_id: str = ""
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.provider_id and self.model)


class VisionConfig(ModelRef):
    provider_id: str = DEFAULT_PROVIDER_ID
    model: str = DEFAULT_MODEL
    enabled: bool = True
    max_figures: int = Field(default=6, ge=1, le=20)
    concurrency: int = Field(default=3, ge=1, le=8)
    max_tokens: int = Field(default=800, ge=64, le=8192)


class ReasoningConfig(ModelRef):
    provider_id: str = DEFAULT_PROVIDER_ID
    model: str = DEFAULT_MODEL
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=32768, ge=256, le=262144)
    max_input_chars: int = Field(default=150000, ge=4000, le=1_000_000)


class PipelineConfig(BaseModel):
    parser: ParserConfig = Field(default_factory=ParserConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)


# --- Settings API ------------------------------------------------------------------


class AppSettingsRead(BaseModel):
    research_focus: str = ""
    research_idea: str = ""
    focus_keywords: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    arxiv_categories: List[str] = Field(default_factory=lambda: ["cs.CV", "cs.LG"])
    providers: List[Provider] = Field(default_factory=default_providers)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    proxy_url: str = ""
    last_fetch_at: Optional[datetime] = None


class AppSettingsUpdate(BaseModel):
    """Every field optional: omitted fields keep their stored value."""
    research_focus: Optional[str] = None
    research_idea: Optional[str] = None
    system_prompt: Optional[str] = None
    arxiv_categories: Optional[List[str]] = None
    providers: Optional[List[Provider]] = None
    pipeline: Optional[PipelineConfig] = None
    proxy_url: Optional[str] = None


def load_settings(row: Optional[AppSettings]) -> AppSettingsRead:
    """Validate a DB row into typed settings, tolerating NULL/legacy JSON columns."""
    if row is None:
        return AppSettingsRead()
    providers = [Provider.model_validate(p) for p in (row.providers or [])]
    if not providers and not row.pipeline:
        providers = default_providers()  # never configured: offer the DeepSeek default
    return AppSettingsRead(
        research_focus=row.research_focus or "",
        research_idea=row.research_idea or "",
        focus_keywords=row.focus_keywords or [],
        system_prompt=row.system_prompt or "",
        arxiv_categories=row.arxiv_categories or ["cs.CV", "cs.LG"],
        providers=providers,
        pipeline=PipelineConfig.model_validate(row.pipeline or {}),
        proxy_url=row.proxy_url or "",
        last_fetch_at=row.last_fetch_at,
    )


def get_provider(settings: AppSettingsRead, provider_id: str) -> Optional[Provider]:
    return next((p for p in settings.providers if p.id == provider_id), None)


# --- Secret masking ------------------------------------------------------------------


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return f"{MASK_PREFIX}{value[-4:]}" if len(value) > 8 else MASK_PREFIX


def is_masked(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(MASK_PREFIX)


def masked(settings: AppSettingsRead) -> AppSettingsRead:
    out = settings.model_copy(deep=True)
    for provider in out.providers:
        provider.api_key = mask_secret(provider.api_key)
    out.pipeline.parser.cloud.token = mask_secret(out.pipeline.parser.cloud.token)
    out.pipeline.parser.local.external_api_key = mask_secret(
        out.pipeline.parser.local.external_api_key
    )
    return out


def unmask_providers(incoming: List[Provider], stored: List[Provider]) -> List[Provider]:
    """A masked api_key in an update means 'unchanged'."""
    by_id = {p.id: p for p in stored}
    result = []
    for provider in incoming:
        provider = provider.model_copy()
        if is_masked(provider.api_key):
            previous = by_id.get(provider.id)
            provider.api_key = previous.api_key if previous else ""
        result.append(provider)
    return result


def unmask_pipeline(incoming: PipelineConfig, stored: PipelineConfig) -> PipelineConfig:
    pipeline = incoming.model_copy(deep=True)
    if is_masked(pipeline.parser.cloud.token):
        pipeline.parser.cloud.token = stored.parser.cloud.token
    if is_masked(pipeline.parser.local.external_api_key):
        pipeline.parser.local.external_api_key = stored.parser.local.external_api_key
    return pipeline
