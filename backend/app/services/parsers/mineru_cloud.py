"""MinerU cloud parser (https://mineru.net, precision API v4).

Flow: request a signed upload URL for the cached PDF (/file-urls/batch) → PUT the file →
poll /extract-results/batch/{batch_id} → download `full_zip_url` → normalize.
Uploading the local file (rather than passing the arXiv URL) means MinerU never has to
reach arxiv.org itself.
"""

import asyncio
import time

import httpx

from app.logging_config import get_logger
from app.schemas import MineruCloudConfig
from app.services.parsers.base import (
    ParsedDocument,
    ParseRequest,
    ProgressFn,
    normalize_zip,
    parse_error,
)
from app.services.errors import PipelineError

logger = get_logger("services.parsers.mineru_cloud")

API_BASE = "https://mineru.net/api/v4"
POLL_INTERVAL = 3.0
TASK_TIMEOUT = 30 * 60  # seconds


class MineruCloudParser:
    engine = "mineru_cloud"

    def __init__(self, config: MineruCloudConfig, api_base: str = API_BASE, poll_interval: float = POLL_INTERVAL):
        if not config.token:
            raise PipelineError("config_error", "未配置 MinerU 云端 API Token（设置 → 解析流程）")
        self.config = config
        self.api_base = api_base.rstrip("/")
        self.poll_interval = poll_interval

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.token}", "Content-Type": "application/json"}

    @staticmethod
    def _check(response: httpx.Response, action: str) -> dict:
        if response.status_code in (401, 403):
            raise PipelineError("config_error", f"MinerU Token 无效或已过期 ({action}: HTTP {response.status_code})")
        if response.status_code == 429:
            raise PipelineError("rate_limit", f"MinerU 请求过于频繁 ({action})")
        if response.status_code >= 400:
            raise parse_error(f"MinerU {action} 失败: HTTP {response.status_code} {response.text[:200]}")
        try:
            body = response.json()
        except ValueError:
            raise parse_error(f"MinerU {action} 返回了无法解析的响应")
        if body.get("code") not in (0, "0", None):
            raise parse_error(f"MinerU {action} 失败: {body.get('msg') or body.get('code')}")
        return body.get("data") or {}

    async def parse(self, request: ParseRequest, progress: ProgressFn) -> ParsedDocument:
        cfg = self.config
        filename = f"{request.arxiv_id.replace('/', '_')}.pdf"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
            # 1. Signed upload URL
            response = await client.post(
                f"{self.api_base}/file-urls/batch",
                headers=self._headers(),
                json={
                    "files": [{"name": filename, "is_ocr": cfg.is_ocr, "data_id": request.arxiv_id}],
                    "model_version": cfg.model_version,
                    "enable_formula": cfg.enable_formula,
                    "enable_table": cfg.enable_table,
                    "language": cfg.language,
                },
            )
            data = self._check(response, "创建上传任务")
            batch_id = data.get("batch_id")
            file_urls = data.get("file_urls") or []
            if not batch_id or not file_urls:
                raise parse_error("MinerU 未返回上传地址")

            # 2. Upload (MinerU docs: do not set Content-Type)
            await progress("上传 PDF 到 MinerU 云端...")
            pdf_bytes = await asyncio.to_thread(request.pdf_path.read_bytes)
            upload = await client.put(file_urls[0], content=pdf_bytes)
            if upload.status_code >= 400:
                raise parse_error(f"上传 PDF 到 MinerU 失败: HTTP {upload.status_code}")

            # 3. Poll
            deadline = time.monotonic() + TASK_TIMEOUT
            zip_url = None
            last_message = ""
            while time.monotonic() < deadline:
                await asyncio.sleep(self.poll_interval)
                response = await client.get(
                    f"{self.api_base}/extract-results/batch/{batch_id}", headers=self._headers()
                )
                data = self._check(response, "查询解析进度")
                results = data.get("extract_result") or []
                result = next(
                    (r for r in results if r.get("data_id") == request.arxiv_id or r.get("file_name") == filename),
                    results[0] if results else None,
                )
                if not result:
                    continue
                state = result.get("state")
                if state == "done":
                    zip_url = result.get("full_zip_url")
                    break
                if state == "failed":
                    raise parse_error(f"MinerU 解析失败: {result.get('err_msg') or 'unknown error'}")
                extract_progress = result.get("extract_progress") or {}
                if extract_progress.get("total_pages"):
                    message = (
                        f"MinerU 云端解析中 {extract_progress.get('extracted_pages', 0)}"
                        f"/{extract_progress['total_pages']} 页"
                    )
                else:
                    message = f"MinerU 云端排队中 ({state})"
                if message != last_message:
                    await progress(message)
                    last_message = message
            if not zip_url:
                raise PipelineError("timeout", "MinerU 云端解析超时")

            # 4. Download + normalize
            await progress("下载解析结果...")
            archive = await client.get(zip_url, follow_redirects=True)
            if archive.status_code >= 400:
                raise parse_error(f"下载 MinerU 结果失败: HTTP {archive.status_code}")

        return await asyncio.to_thread(normalize_zip, archive.content, request.out_dir, self.engine)
