"""Test an arXiv search query: how many papers it finds and what they look like.

Used by the research-direction agent to check its keywords against the live arXiv API
before they are saved. Respects arXiv's request spacing (one call every 3 seconds).
"""

import asyncio
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from app.services.errors import PipelineError
from app.services.network import USER_AGENT

API_URL = "https://export.arxiv.org/api/query"
FETCH_SIZE = 50          # the daily fetch also reads at most 50 papers per week
REQUEST_SPACING = 3.0    # seconds between arXiv API calls
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_lock = asyncio.Lock()
_last_request = 0.0


@dataclass
class ProbePaper:
    title: str
    abstract: str
    published: datetime


@dataclass
class ProbeResult:
    query: str
    total: int                                    # all-time matches
    weekly: int                                   # matches submitted in the last 7 days
    weekly_capped: bool                           # weekly >= FETCH_SIZE (true count is higher)
    papers: List[ProbePaper] = field(default_factory=list)  # newest first


def _text(element: Optional[ET.Element]) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def parse_feed(query: str, xml_text: str, now: Optional[datetime] = None) -> ProbeResult:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise PipelineError("llm_error", f"arXiv 返回了无法解析的结果: {e}")
    entries = root.findall("atom:entry", NS)
    # Malformed queries come back as a single entry pointing at /api/errors
    if len(entries) == 1 and "/api/errors" in _text(entries[0].find("atom:id", NS)):
        raise PipelineError("config_error", f"arXiv 检索式语法错误: {_text(entries[0].find('atom:summary', NS))}")

    papers = []
    for entry in entries:
        published_raw = _text(entry.find("atom:published", NS))
        try:
            published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        papers.append(ProbePaper(
            title=_text(entry.find("atom:title", NS)),
            abstract=_text(entry.find("atom:summary", NS)),
            published=published,
        ))
    total_raw = _text(root.find("opensearch:totalResults", NS))
    total = int(total_raw) if total_raw.isdigit() else len(papers)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=7)
    weekly = sum(1 for paper in papers if paper.published >= cutoff)
    return ProbeResult(
        query=query,
        total=total,
        weekly=weekly,
        weekly_capped=weekly >= FETCH_SIZE,
        papers=papers,
    )


ATTEMPTS = 3  # the arXiv API drops connections now and then


async def _get(query: str) -> httpx.Response:
    global _last_request
    async with _lock:
        wait = REQUEST_SPACING - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                return await client.get(API_URL, params={
                    "search_query": query,
                    "start": 0,
                    "max_results": FETCH_SIZE,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                })
        finally:
            _last_request = time.monotonic()


async def probe_query(query: str) -> ProbeResult:
    """Run `query` against arXiv (newest first) and summarize the result."""
    last_error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = await _get(query)
        except httpx.HTTPError as e:
            last_error = str(e) or e.__class__.__name__
        else:
            if response.status_code < 400:
                return parse_feed(query, response.text)
            last_error = f"HTTP {response.status_code}"
            if response.status_code < 500 and response.status_code != 429:
                break  # a client error won't fix itself
        if attempt < ATTEMPTS:
            await asyncio.sleep(REQUEST_SPACING * attempt)
    raise PipelineError("download_error", f"无法访问 arXiv（已重试 {ATTEMPTS} 次）: {last_error}")
