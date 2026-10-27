"""API for the bundled Jev-only proxy. Private values are write-only."""

from fastapi import APIRouter, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr

import jev_proxy
from semantic_filter import check_jev_connection

class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Pydantic's normal validation detail can include the raw input,
                # including a malformed subscription URL or API key value.
                raise HTTPException(status_code=422, detail="proxy_request_invalid") from None
        return private_handler


router = APIRouter(prefix="/jev-proxy", tags=["jev-proxy"], route_class=PrivateInputRoute)


class ProxySettingsRequest(BaseModel):
    enabled: bool
    subscription_url: SecretStr | None = None
    clear_subscription: bool = False


class NodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TestRequest(BaseModel):
    api_key: SecretStr | None = None


def _error(exc):
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def get_proxy(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await jev_proxy.status()


@router.put("")
async def put_proxy(request: ProxySettingsRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await jev_proxy.update_settings(
            request.enabled,
            request.subscription_url.get_secret_value() if request.subscription_url else "",
            request.clear_subscription)
    except jev_proxy.ProxyError as exc:
        raise _error(exc) from None


@router.post("/refresh")
async def refresh_proxy(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await jev_proxy.refresh_subscription()
    except jev_proxy.ProxyError as exc:
        raise _error(exc) from None


@router.put("/node")
async def put_node(request: NodeRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await jev_proxy.select_node(request.name)
    except jev_proxy.ProxyError as exc:
        raise _error(exc) from None


@router.post("/test")
async def test_proxy(request: TestRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not jev_proxy.bundled_available():
        raise HTTPException(status_code=400, detail="proxy_unavailable")
    from api.routers.data import data_root
    from api.services.semantic_settings import runtime_key
    key = (request.api_key.get_secret_value() if request.api_key else "") or runtime_key(data_root())
    return await check_jev_connection(key.strip())
