"""Explicit grounded mock responses for integration tests, not accuracy tests."""

import json
import httpx


def grounded_response(request, choice="keep", *, kind="place", relation="target_itself", source=None, confidence=0.9):
    payload = json.loads(request.content)
    if "support" in payload["questions"]:
        return httpx.Response(200, json={"answers": {"support": {"choice": "supported", "confidence": 0.95}}, "usage": {"input_tokens": 20}})
    options = payload["questions"]["evidence_text"]["criteria"]
    first = payload["state"].get("keyword1", payload["state"].get("evaluation"))
    second = payload["state"].get("keyword2", payload["state"].get("target"))
    evaluation = next((key for key, value in options.items() if first in value and (not source or value.startswith(f"[{source},"))), "unclear")
    location = next((key for key, value in options.items() if second in value), "unclear")
    return httpx.Response(200, json={"answers": {
        "relation": {"choice": choice, "confidence": confidence},
        "object_type": {"choice": kind}, "target_relation": {"choice": relation},
        "evidence_text": {"choice": evaluation}, "target_evidence": {"choice": location},
    }, "usage": {"input_tokens": 20}})
