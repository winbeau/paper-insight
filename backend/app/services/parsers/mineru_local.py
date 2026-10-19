"""Local MinerU parser: talks to a MinerU 4.x `mineru-kit api-server` (V1 HTTP API).

The server is either managed by the app (services.mineru_runtime) or external.
`POST /v1/file_parse` is used with `response_format=zip`; a 202 response means the job
outlived `wait_timeout` and is polled via its status/result URLs.
"""

import asyncio
import base64
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import httpx

from app.logging_config import get_logger
from app.schemas import MineruLocalConfig
from app.services.errors import PipelineError
from app.services.parsers.base import (
    ParsedDocument,
    ParseRequest,
    ProgressFn,
    normalize_output_dir,
    normalize_zip,
    parse_error,
)

logger = get_logger("services.parsers.mineru_local")

WAIT_TIMEOUT = 1800       # seconds the server may hold the sync request
TASK_TIMEOUT = 2 * 3600   # overall cap (large papers on CPU/MPS are slow)
POLL_INTERVAL = 3.0


class MineruLocalParser:
    engine = "mineru_local"

    def __init__(self, config: MineruLocalConfig):
        self.config = config

    async def _base_url(self, progress: ProgressFn) -> tuple[str, Dict[str, str]]:
        if self.config.mode == "external":
            if not self.config.external_url:
                raise PipelineError("config_error", "未配置外部 MinerU 服务地址")
            headers = {}
            if self.config.external_api_key:
                headers["Authorization"] = f"Bearer {self.config.external_api_key}"
            return self.config.external_url.rstrip("/"), headers

        from app.services.mineru_runtime import get_mineru_runtime

        runtime = get_mineru_runtime()
        if not runtime.is_installed():
            raise PipelineError("config_error", "本地 MinerU 尚未安装，请在 设置 → 解析流程 中安装并拉取模型")
        await progress("启动本地 MinerU 服务（首次加载模型可能需要几分钟）...")
        return await runtime.ensure_server(self.config.tier), {}

    async def parse(self, request: ParseRequest, progress: ProgressFn) -> ParsedDocument:
        base_url, headers = await self._base_url(progress)

        from app.services.mineru_runtime import get_mineru_runtime

        runtime = get_mineru_runtime() if self.config.mode == "managed" else None
        if runtime:
            runtime.mark_busy(True)
        try:
            await progress(f"本地 MinerU 解析中 (tier={self.config.tier})...")
            return await self._parse_with(base_url, headers, request, progress)
        except httpx.ConnectError as e:
            raise parse_error(f"无法连接本地 MinerU 服务 {base_url}: {e}")
        except httpx.TimeoutException:
            raise PipelineError("timeout", "本地 MinerU 解析超时")
        finally:
            if runtime:
                runtime.mark_busy(False)

    async def _parse_with(
        self, base_url: str, headers: Dict[str, str], request: ParseRequest, progress: ProgressFn
    ) -> ParsedDocument:
        timeout = httpx.Timeout(WAIT_TIMEOUT + 60, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, headers=headers, trust_env=False) as client:
            pdf_bytes = await asyncio.to_thread(request.pdf_path.read_bytes)
            response = await client.post(
                f"{base_url}/v1/file_parse",
                params={
                    "tier": self.config.tier,
                    "response_format": "zip",
                    "wait_timeout": WAIT_TIMEOUT,
                },
                files={"files": (request.pdf_path.name, pdf_bytes, "application/pdf")},
            )

            if response.status_code == 202:
                response = await self._poll(client, base_url, response.json(), progress)

            if response.status_code >= 400:
                raise parse_error(
                    f"本地 MinerU 解析失败: HTTP {response.status_code} {response.text[:300]}"
                )
            return await self._materialize(client, base_url, response, request.out_dir)

    async def _poll(
        self, client: httpx.AsyncClient, base_url: str, accepted: Dict[str, Any], progress: ProgressFn
    ) -> httpx.Response:
        task_id = accepted.get("task_id")
        status_url = urljoin(base_url + "/", accepted.get("status_url") or f"v1/tasks/{task_id}")
        result_url = accepted.get("result_url")
        deadline = time.monotonic() + TASK_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            status = await client.get(status_url)
            if status.status_code >= 400:
                raise parse_error(f"查询本地 MinerU 任务失败: HTTP {status.status_code}")
            body = status.json()
            state = body.get("status") or body.get("state")
            if state in ("completed", "partial"):
                result_url = body.get("result_url") or result_url
                if not result_url:
                    return status  # result inlined in the status payload
                return await client.get(
                    urljoin(base_url + "/", result_url),
                    params={"response_format": "zip"},
                    follow_redirects=True,
                )
            if state in ("failed", "canceled"):
                raise parse_error(f"本地 MinerU 任务{state}: {body.get('error') or body.get('message') or ''}")
            await progress(f"本地 MinerU 解析中 ({state or 'running'})...")
        raise PipelineError("timeout", "本地 MinerU 解析超时")

    async def _materialize(
        self, client: httpx.AsyncClient, base_url: str, response: httpx.Response, out_dir: Path
    ) -> ParsedDocument:
        content = response.content
        if content[:2] == b"PK":
            return await asyncio.to_thread(normalize_zip, content, out_dir, self.engine)

        try:
            body = response.json()
        except ValueError:
            raise parse_error("本地 MinerU 返回了无法识别的结果")

        # JSON response: write inlined output files to disk, fetch referenced ones
        with tempfile.TemporaryDirectory(prefix="mineru-local-") as tmp:
            raw_dir = Path(tmp)
            written = 0
            for file_entry in body.get("files") or []:
                if file_entry.get("status") == "failed":
                    raise parse_error(f"本地 MinerU 解析失败: {file_entry.get('error') or ''}")
                for output in file_entry.get("output_files") or []:
                    written += await self._write_output(client, base_url, output, raw_dir)
            if not written:
                raise parse_error(f"本地 MinerU 结果为空: {json.dumps(body)[:300]}")
            return await asyncio.to_thread(normalize_output_dir, raw_dir, out_dir, self.engine)

    async def _write_output(
        self, client: httpx.AsyncClient, base_url: str, output: Dict[str, Any], raw_dir: Path
    ) -> int:
        rel = str(output.get("path") or output.get("name") or output.get("filename") or "")
        rel = rel.lstrip("/").replace("..", "_")
        if not rel:
            return 0
        target = raw_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        data: Optional[bytes] = None
        if "content" in output and output["content"] is not None:
            value = output["content"]
            if output.get("encoding") == "base64":
                data = base64.b64decode(value)
            elif isinstance(value, (dict, list)):
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            else:
                data = str(value).encode("utf-8")
        elif output.get("file_id") or output.get("url"):
            url = output.get("url") or f"/v1/files/{output['file_id']}/content"
            fetched = await client.get(urljoin(base_url + "/", url), follow_redirects=True)
            if fetched.status_code < 400:
                data = fetched.content
        if data is None:
            return 0
        if data[:2] == b"PK" and rel.endswith(".zip"):
            from app.services.parsers.base import safe_extract_zip

            safe_extract_zip(data, raw_dir)
        else:
            target.write_bytes(data)
        return 1
