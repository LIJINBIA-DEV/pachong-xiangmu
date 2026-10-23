import math
import importlib

import httpx
import pytest

from semif_local import SemIfLocalReviewer
from api.schemas.crawler import CrawlerStartRequest
from api.services.crawler_manager import CrawlerManager


@pytest.mark.asyncio
async def test_option_scoring_uses_exact_letter_tokens_only(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"logprobs": {"content": [{"top_logprobs": [
                {"token": "A", "bytes": [65], "logprob": -0.1},
                {"token": "B", "bytes": [66], "logprob": -2.2},
                {"token": "C", "bytes": [67], "logprob": -3.4},
                {"token": "(A", "bytes": [40, 65], "logprob": -12.0},
            ]}]}}],
            "usage": {"prompt_tokens": 42},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reviewer = SemIfLocalReviewer(client)

        async def ready():
            reviewer.port = 12345

        monkeypatch.setattr(reviewer, "_ensure_server", ready)
        choice, confidence = await reviewer.decide(("可爱", "公园"), "这个公园好可爱")

    assert choice == "keep"
    assert confidence == pytest.approx(math.exp(-0.1) / sum(map(math.exp, (-0.1, -2.2, -3.4))))
    assert reviewer.calls == 1
    assert reviewer.input_tokens == 42
    assert len(requests) == 1
    assert requests[0].url.host == "127.0.0.1"
    assert requests[0].headers["Authorization"] == f"Bearer {reviewer.api_key}"


@pytest.mark.asyncio
async def test_local_model_can_start_without_typesafe_key(monkeypatch):
    module = importlib.import_module("api.services.crawler_manager")

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(module, "local_model_ready", lambda: True)
    captured = {}

    class Process:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs["env"]
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    manager = CrawlerManager()
    request = CrawlerStartRequest(
        platform="wb", crawler_type="search", save_option="excel",
        keywords="可爱 公园", keyword_pairs=[("可爱", "公园")],
        semantic_filter=True, semantic_model="semif-qwen3.5-4b-q4",
    )
    assert await manager.start(request)
    assert captured["env"]["MEDIACRAWLER_SEMANTIC_MODEL"] == "semif-qwen3.5-4b-q4"
    assert captured["env"]["TYPESAFE_API_KEY"] == ""
    manager._read_task.cancel()
