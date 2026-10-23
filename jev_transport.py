"""Optional SSH Unix-socket transport, scoped to Jev requests only."""
import os
from pathlib import PurePosixPath

import httpx
import jev_proxy


class BundledJevTransport(httpx.AsyncBaseTransport):
    """Re-evaluate saved routing at each request, including already-running jobs."""

    def __init__(self):
        self.direct = httpx.AsyncHTTPTransport(trust_env=False)
        # A CONNECT tunnel must not pin an already-selected old node after the
        # user switches nodes in the UI. Each request gets a new proxy tunnel.
        self.proxy = httpx.AsyncHTTPTransport(proxy=jev_proxy.PROXY_URL, trust_env=False,
                                              limits=httpx.Limits(max_keepalive_connections=0))

    async def handle_async_request(self, request):
        try:
            transport = self.proxy if jev_proxy.proxy_enabled() else self.direct
        except jev_proxy.ProxyError:
            raise httpx.ConnectError("Jev proxy settings are unavailable", request=request) from None
        return await transport.handle_async_request(request)

    async def aclose(self):
        await self.direct.aclose()
        await self.proxy.aclose()


def relay_settings():
    socket = os.environ.get('TYPESAFE_RELAY_SOCKET', '').strip()
    if not socket:
        return None
    token = os.environ.get('TYPESAFE_RELAY_TOKEN', '')
    if not PurePosixPath(socket).is_absolute() or '\0' in socket:
        raise ValueError('Invalid Jev relay socket path')
    if not token or any(character.isspace() for character in token):
        raise ValueError('Jev relay token missing or invalid')
    return socket, token


def create_semantic_client(model='jev-1.13.0'):
    if model == 'jev-1.13.0' and jev_proxy.bundled_available():
        return httpx.AsyncClient(transport=BundledJevTransport(), trust_env=False)
    relay = relay_settings() if model == 'jev-1.13.0' else None
    if relay:
        return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=relay[0]), trust_env=False)
    proxy = os.environ.get('TYPESAFE_PROXY_URL', '').strip() if model == 'jev-1.13.0' else ''
    if proxy:
        return httpx.AsyncClient(proxy=proxy, trust_env=False)
    return httpx.AsyncClient()


def jev_request_target(direct_url):
    if jev_proxy.bundled_available():
        return direct_url, {}
    relay = relay_settings()
    if relay:
        return 'http://jev-relay/v1/systemone', {'X-Jev-Relay-Token': relay[1]}
    return direct_url, {}
