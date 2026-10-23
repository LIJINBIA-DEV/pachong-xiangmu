"""Local SemIf-style constrained choice scoring with a quantized Qwen model."""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from typing import Any

import httpx
from semantic_rules import relation_instructions


MODEL_ID = "semif-qwen3.5-4b-q4"
MODEL_BYTES = 3_013_027_808
PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_ROOT / "models" / MODEL_ID / "Qwen_Qwen3.5-4B-Q4_K_M.gguf"
SERVER_PATH = PROJECT_ROOT / "models" / "runtime" / "llama-b11233-vulkan" / "llama-server.exe"


def local_model_ready() -> bool:
    return MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == MODEL_BYTES and SERVER_PATH.is_file()


class SemIfLocalReviewer:
    """Read the three option-token probabilities; keep the server local to this crawl."""

    model = MODEL_ID

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient()
        self._own_client = client is None
        self._lock = asyncio.Lock()
        self.process: subprocess.Popen | None = None
        self._log_file: Any = None
        self.port: int | None = None
        self.api_key = secrets.token_urlsafe(32)
        self.calls = 0
        self.input_tokens = 0
        self.cache: dict[tuple[tuple[str, str], str], tuple[str, float]] = {}
        self.failure: str | None = None

    async def _ensure_server(self) -> None:
        if self.process is not None:
            if self.process.poll() is not None:
                raise RuntimeError(f"Local SemIf server exited with code {self.process.returncode}; see models/runtime/semif-server.log")
            return
        async with self._lock:
            if self.process is not None:
                return
            if not local_model_ready():
                raise RuntimeError(f"SemIf model or runtime missing/incomplete: {MODEL_PATH}")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                self.port = sock.getsockname()[1]
            log_path = PROJECT_ROOT / "models" / "runtime" / "semif-server.log"
            self._log_file = open(log_path, "a", encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                [str(SERVER_PATH), "--model", str(MODEL_PATH), "--host", "127.0.0.1",
                 "--port", str(self.port), "--ctx-size", "4096", "--n-gpu-layers", "99",
                 "--parallel", "1", "--jinja", "--no-webui", "--api-key", self.api_key,
                 "--cors-origins", "http://127.0.0.1:0"],
                cwd=str(SERVER_PATH.parent), stdout=self._log_file, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            url = f"http://127.0.0.1:{self.port}/health"
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Local SemIf server exited with code {self.process.returncode}; see {log_path}")
                try:
                    response = await self.client.get(url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=3)
                    if response.status_code == 200:
                        print(f"[Semantic] Local SemIf model ready on 127.0.0.1:{self.port}", flush=True)
                        return
                except httpx.RequestError:
                    pass
                await asyncio.sleep(1)
            raise RuntimeError(f"Local SemIf model load timed out; see {log_path}")

    async def decide(self, pair: tuple[str, str], text: str) -> tuple[str, float | None]:
        key = (pair, text)
        if key in self.cache:
            return self.cache[key]
        await self._ensure_server()
        assert self.port is not None
        first, second = pair
        user = (
            f"State:\n{text}\n\nQuestion:\n"
            f"keyword1={first}; keyword2={second}。" + relation_instructions(second)
            + "\n\nAllowed options:\n"
            f"A. 是，明确用“{first}”评价“{second}”对应范围内允许的空间对象。\n"
            "B. 否，形容其他对象、否定描述或没有直接描述关系。\n"
            "C. 无法确定，指代不清或上下文不足。\n\n"
            "Reply with exactly one option letter from: A, B, C."
        )
        payload = {
            "model": MODEL_PATH.name,
            "messages": [
                {"role": "system", "content": "Make the requested decision from the supplied state. Follow the output format exactly."},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1, "temperature": 1, "top_k": 0, "top_p": 1,
            "grammar": 'root ::= "A" | "B" | "C"',
            "logprobs": True, "top_logprobs": 20,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        self.calls += 1
        try:
            response = await self.client.post(
                f"http://127.0.0.1:{self.port}/v1/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            scored = result["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
            scores = {}
            for item in scored:
                for letter in "ABC":
                    if item.get("token") == letter or item.get("bytes") == [ord(letter)]:
                        scores[letter] = float(item["logprob"])
            if not all(letter in scores for letter in "ABC"):
                raise ValueError(f"Incomplete SemIf option probabilities: {list(scores)}")
            normalizer = sum(math.exp(scores[letter]) for letter in "ABC")
            probs = {letter: math.exp(scores[letter]) / normalizer for letter in "ABC"}
            winner = max(probs, key=probs.get)
            choice = {"A": "keep", "B": "reject", "C": "review"}[winner]
            # Uncertain options are reviewed, never silently treated as matches.
            if probs[winner] < 0.65:
                choice = "review"
            self.input_tokens += int(result.get("usage", {}).get("prompt_tokens") or 0)
            decision = (choice, probs[winner])
            self.cache[key] = decision
            print(f"[Semantic] SemIf {choice} (A={probs['A']:.3f}, B={probs['B']:.3f}, C={probs['C']:.3f})", flush=True)
            return decision
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            self.failure = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(f"Local SemIf inference failed: {self.failure}") from exc

    async def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        if self._log_file is not None:
            self._log_file.close()
        if self._own_client:
            await self.client.aclose()
