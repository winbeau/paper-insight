import json

import httpx
import pytest
import respx

from app.schemas import Provider
from app.services.errors import PipelineError
from app.services.llm_client import ThinkTagSplitter, clear_client_cache, stream_chat

BASE = "https://llm.test/v1"
PROVIDER = Provider(id="p1", name="test", base_url=BASE, api_key="sk-test-123456789")


def _sse(chunks):
    lines = []
    for delta in chunks:
        payload = {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        lines.append(f"data: {json.dumps(payload)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


@pytest.fixture(autouse=True)
def _clients():
    clear_client_cache()
    yield
    clear_client_cache()


def _collect(splitter, pieces):
    out = []
    for piece in pieces:
        out += splitter.feed(piece)
    out += splitter.flush()
    merged = {"thinking": "", "answer": ""}
    for kind, text in out:
        merged[kind] += text
    return merged


@pytest.mark.parametrize(
    "pieces",
    [
        ["<think>abc</think>{\"a\":1}"],
        ["<thi", "nk>ab", "c</th", "ink>{\"a\"", ":1}"],
        list("<think>abc</think>{\"a\":1}"),
    ],
)
def test_think_splitter_across_chunk_boundaries(pieces):
    assert _collect(ThinkTagSplitter(), pieces) == {"thinking": "abc", "answer": '{"a":1}'}


def test_think_splitter_passes_plain_text_and_lone_angle_brackets():
    assert _collect(ThinkTagSplitter(), ["a < b", " and <tag>"]) == {"thinking": "", "answer": "a < b and <tag>"}


@respx.mock
async def test_stream_reasoning_content_and_reasoning_fields():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse([
                {"role": "assistant", "reasoning_content": "思考1"},
                {"reasoning": "思考2"},
                {"content": "答"},
                {"content": "案"},
            ]),
        )
    )
    out = [item async for item in stream_chat(PROVIDER, "m", [{"role": "user", "content": "hi"}])]
    assert out == [("thinking", "思考1"), ("thinking", "思考2"), ("answer", "答"), ("answer", "案")]


@respx.mock
async def test_unsupported_max_tokens_is_retried_as_max_completion_tokens():
    route = respx.post(f"{BASE}/chat/completions")
    route.side_effect = [
        httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_tokens'", "type": "invalid_request_error"}}),
        httpx.Response(200, headers={"content-type": "text/event-stream"}, text=_sse([{"content": "ok"}])),
    ]
    out = [item async for item in stream_chat(PROVIDER, "m", [], max_tokens=100)]
    assert out == [("answer", "ok")]
    second = json.loads(route.calls[1].request.content)
    assert "max_tokens" not in second and second["max_completion_tokens"] == 100


@pytest.mark.parametrize(
    "status, code",
    [(401, "config_error"), (404, "config_error"), (429, "rate_limit"), (413, "entity_too_large"), (500, "llm_error")],
)
@respx.mock
async def test_http_errors_are_mapped(status, code):
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(status, json={"error": {"message": "boom"}})
    )
    provider = PROVIDER.model_copy()
    with pytest.raises(PipelineError) as info:
        async for _ in stream_chat(provider, "m", []):
            pass
    assert info.value.code == code


@respx.mock
async def test_truncated_output_is_reported():
    body = _sse([{"content": "{\"paper_essence\": \"x"}]).replace(
        '"finish_reason": null}]}\n\ndata: [DONE]', '"finish_reason": "length"}]}\n\ndata: [DONE]'
    )
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )
    with pytest.raises(PipelineError) as info:
        async for _ in stream_chat(PROVIDER, "m", []):
            pass
    assert info.value.code == "llm_error"
    assert "tokens" in info.value.message
