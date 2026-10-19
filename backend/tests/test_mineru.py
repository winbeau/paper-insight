import io
import json
import zipfile

import httpx
import pytest
import respx

from app.schemas import MineruCloudConfig
from app.services.errors import PipelineError
from app.services.parsers import ParseRequest, load_cached
from app.services.parsers.base import normalize_zip, figures_from_markdown
from app.services.parsers.mineru_cloud import MineruCloudParser

API = "https://mineru.test/api/v4"
IMAGE = b"\xff\xd8\xff" + b"0" * 8000  # big enough to count as a figure


def make_zip(with_content_list: bool = True, prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{prefix}full.md", "# Title\n\nBody text.\n\n![](images/fig1.jpg)\nFigure 1: Speedup.\n")
        zf.writestr(f"{prefix}images/fig1.jpg", IMAGE)
        zf.writestr(f"{prefix}images/tab1.jpg", IMAGE)
        if with_content_list:
            zf.writestr(f"{prefix}x_content_list.json", json.dumps([
                {"type": "text", "text": "We measure latency.", "page_idx": 0},
                {"type": "image", "img_path": "images/fig1.jpg", "image_caption": ["Figure 1: Speedup."], "page_idx": 1},
                {"type": "table", "img_path": "images/tab1.jpg", "table_caption": ["Table 1: Results"],
                 "table_body": "<table></table>", "page_idx": 2},
            ]))
    return buffer.getvalue()


def test_normalize_zip_with_content_list(tmp_path):
    doc = normalize_zip(make_zip(prefix="nested/"), tmp_path / "out", "mineru_cloud")
    assert doc.markdown.startswith("# Title")
    assert [(f.n, f.kind, f.caption, f.page) for f in doc.figures] == [
        (1, "image", "Figure 1: Speedup.", 2),
        (2, "table", "Table 1: Results", 3),
    ]
    assert doc.figures[0].context == "We measure latency."
    assert doc.figure_path(doc.figures[0]).read_bytes() == IMAGE

    cached = load_cached(tmp_path / "out")
    assert cached is not None and cached.from_cache and len(cached.figures) == 2


def test_normalize_zip_without_content_list_uses_markdown(tmp_path):
    doc = normalize_zip(make_zip(with_content_list=False), tmp_path / "out", "mineru_local")
    assert [(f.caption, f.path) for f in doc.figures] == [("Figure 1: Speedup.", "images/fig1.jpg")]


def test_zip_slip_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../evil.md", "x")
    with pytest.raises(PipelineError):
        normalize_zip(buffer.getvalue(), tmp_path / "out", "mineru_cloud")


def test_markdown_figures_skip_remote_images():
    figures = figures_from_markdown("![](https://x/y.png)\n\n![](images/a.png)\nTable 2: Ablation")
    assert [(f.path, f.kind) for f in figures] == [("images/a.png", "table")]


def _request(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    return ParseRequest(
        arxiv_id="2401.00001v1", title="T", pdf_url="https://arxiv.org/pdf/2401.00001v1",
        pdf_path=pdf, out_dir=tmp_path / "parsed",
    )


async def _noop(_message):
    pass


@respx.mock
async def test_cloud_flow_upload_poll_download(tmp_path):
    batch = respx.post(f"{API}/file-urls/batch").mock(return_value=httpx.Response(200, json={
        "code": 0, "data": {"batch_id": "b1", "file_urls": ["https://oss.test/upload/1"]},
    }))
    upload = respx.put("https://oss.test/upload/1").mock(return_value=httpx.Response(200))
    respx.get(f"{API}/extract-results/batch/b1").side_effect = [
        httpx.Response(200, json={"code": 0, "data": {"extract_result": [
            {"file_name": "2401.00001v1.pdf", "state": "running", "data_id": "2401.00001v1",
             "extract_progress": {"extracted_pages": 1, "total_pages": 9}},
        ]}}),
        httpx.Response(200, json={"code": 0, "data": {"extract_result": [
            {"file_name": "2401.00001v1.pdf", "state": "done", "data_id": "2401.00001v1",
             "full_zip_url": "https://cdn.test/r.zip"},
        ]}}),
    ]
    respx.get("https://cdn.test/r.zip").mock(return_value=httpx.Response(200, content=make_zip()))

    messages = []

    async def progress(message):
        messages.append(message)

    parser = MineruCloudParser(MineruCloudConfig(token="tok"), api_base=API, poll_interval=0)
    doc = await parser.parse(_request(tmp_path), progress)

    body = json.loads(batch.calls[0].request.content)
    assert body["files"][0]["data_id"] == "2401.00001v1" and body["model_version"] == "vlm"
    assert batch.calls[0].request.headers["authorization"] == "Bearer tok"
    assert upload.calls[0].request.content == b"%PDF-1.4 test"
    assert "content-type" not in upload.calls[0].request.headers
    assert any("1/9" in m for m in messages)
    assert len(doc.figures) == 2 and doc.engine == "mineru_cloud"


@respx.mock
async def test_cloud_failed_state_raises_parse_error(tmp_path):
    respx.post(f"{API}/file-urls/batch").mock(return_value=httpx.Response(200, json={
        "code": 0, "data": {"batch_id": "b1", "file_urls": ["https://oss.test/upload/1"]},
    }))
    respx.put("https://oss.test/upload/1").mock(return_value=httpx.Response(200))
    respx.get(f"{API}/extract-results/batch/b1").mock(return_value=httpx.Response(200, json={
        "code": 0, "data": {"extract_result": [{"state": "failed", "err_msg": "bad pdf", "data_id": "2401.00001v1"}]},
    }))
    parser = MineruCloudParser(MineruCloudConfig(token="tok"), api_base=API, poll_interval=0)
    with pytest.raises(PipelineError) as info:
        await parser.parse(_request(tmp_path), _noop)
    assert info.value.code == "parse_error" and "bad pdf" in info.value.message


@respx.mock
async def test_cloud_bad_token_is_config_error(tmp_path):
    respx.post(f"{API}/file-urls/batch").mock(return_value=httpx.Response(401, json={"msg": "unauthorized"}))
    parser = MineruCloudParser(MineruCloudConfig(token="tok"), api_base=API, poll_interval=0)
    with pytest.raises(PipelineError) as info:
        await parser.parse(_request(tmp_path), _noop)
    assert info.value.code == "config_error"


@respx.mock
async def test_cloud_nonzero_code_is_parse_error(tmp_path):
    respx.post(f"{API}/file-urls/batch").mock(return_value=httpx.Response(200, json={"code": -60005, "msg": "file too large"}))
    parser = MineruCloudParser(MineruCloudConfig(token="tok"), api_base=API, poll_interval=0)
    with pytest.raises(PipelineError) as info:
        await parser.parse(_request(tmp_path), _noop)
    assert info.value.code == "parse_error" and "file too large" in info.value.message


def test_cloud_without_token_is_config_error():
    with pytest.raises(PipelineError) as info:
        MineruCloudParser(MineruCloudConfig(token=""))
    assert info.value.code == "config_error"


def test_markdown_figures_mineru4_layout():
    markdown = (
        "Some intro paragraph that explains the latency measurements in detail.\n\n$$\nx = y\n$$\n\n"
        "![](images/page_3_image_0.jpg)\n\nFigure 2: Pipeline overview.\n\n"
        "![](images/page_7_chart_1.jpg)\n(a) Single-stage v.s. Two-stage\n"
    )
    first, second = figures_from_markdown(markdown)
    assert (first.caption, first.page) == ("Figure 2: Pipeline overview.", 4)
    assert first.context.startswith("Some intro paragraph")
    assert (second.caption, second.context, second.page) == ("", "(a) Single-stage v.s. Two-stage", 8)
