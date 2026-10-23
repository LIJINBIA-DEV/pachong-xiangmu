"""Loopback-only Jev relay. Never log authentication headers or request bodies."""
from contextlib import asynccontextmanager
import hmac
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
import httpx

UPSTREAM = 'https://api.typesafe.ai/v1/systemone'
BODY_LIMIT = 2 * 1024 * 1024


def create_app(token, transport=None):
    if not token:
        raise ValueError('Relay authentication token required')

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(19, connect=8), transport=transport) as client:
            app.state.upstream = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'service': 'jev-relay'}

    @app.post('/v1/systemone')
    async def forward(request: Request):
        if not hmac.compare_digest(request.headers.get('X-Jev-Relay-Token', '').encode(), token.encode()):
            raise HTTPException(401, detail='relay_authentication_required')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > BODY_LIMIT:
                raise HTTPException(413, detail='relay_request_too_large')
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, detail='relay_invalid_json')
        if not isinstance(payload, dict) or payload.get('model') != 'jev-1.13.0':
            raise HTTPException(400, detail='relay_model_not_allowed')
        headers = {'Content-Type': 'application/json'}
        if request.headers.get('Authorization'):
            headers['Authorization'] = request.headers['Authorization']
        try:
            upstream = await app.state.upstream.post(UPSTREAM, content=bytes(body), headers=headers)
        except httpx.HTTPError:
            raise HTTPException(502, detail='relay_upstream_unavailable')
        return Response(upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get('Content-Type', 'application/json'))

    return app
