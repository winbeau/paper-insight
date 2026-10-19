"""PDF parsing engines (MinerU cloud / local) behind one interface + cache."""

from app.schemas import ParserConfig
from app.services.parsers.base import (
    Figure,
    ParsedDocument,
    ParseRequest,
    PdfParser,
    ProgressFn,
    clear_cache,
    load_cached,
)
from app.services.parsers.mineru_cloud import MineruCloudParser
from app.services.parsers.mineru_local import MineruLocalParser

__all__ = [
    "Figure",
    "ParsedDocument",
    "ParseRequest",
    "PdfParser",
    "clear_cache",
    "get_parser",
    "parse_document",
    "validate_parser_config",
]

def validate_parser_config(config: ParserConfig) -> None:
    """Fail fast (before downloading anything) when the parse engine can't run."""
    get_parser(config)  # constructors validate tokens/URLs
    if config.engine == "mineru_local" and config.local.mode == "managed":
        from app.services.errors import PipelineError
        from app.services.mineru_runtime import get_mineru_runtime

        if not get_mineru_runtime().is_installed():
            raise PipelineError("config_error", "本地 MinerU 尚未安装，请在 设置 → 解析流程 中安装并拉取模型")


def get_parser(config: ParserConfig) -> PdfParser:
    if config.engine == "mineru_local":
        return MineruLocalParser(config.local)
    return MineruCloudParser(config.cloud)


async def parse_document(
    config: ParserConfig, request: ParseRequest, progress: ProgressFn
) -> ParsedDocument:
    """Parse a PDF with the configured engine, reusing a previous result if cached.

    Concurrency (how many documents MinerU sees at once) is governed by services.parse_queue.
    """
    cached = load_cached(request.out_dir)
    if cached is not None:
        return cached
    return await get_parser(config).parse(request, progress)
