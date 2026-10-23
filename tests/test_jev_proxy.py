import json
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import jev_proxy as proxy
from jev_transport import BundledJevTransport, create_semantic_client, jev_request_target


def node(name="Hong Kong", **values):
    return {"name": name, "type": "http", "server": "proxy.example.test",
            "port": 443, "username": "private-user", "password": "private-node-secret", **values}


@pytest.fixture
def private_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIACRAWLER_BUNDLED_PROXY", "1")
    monkeypatch.setenv("MEDIACRAWLER_JEV_PROXY_DIR", str(tmp_path / ".jev-proxy"))
    monkeypatch.setattr(proxy, "_lock", __import__("asyncio").Lock())
    proxy.prepare_runtime()
    calls = []

    async def controller(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            config = yaml.safe_load((proxy.runtime_dir() / "runtime.yaml").read_text("utf-8"))
            return {"now": config["proxy-groups"][0]["proxies"][0]}
        return {}

    monkeypatch.setattr(proxy, "_controller", controller)
    monkeypatch.setattr(proxy, "_validate_runtime", AsyncMock())
    monkeypatch.setattr(proxy, "fetch_subscription", AsyncMock(return_value=[node(), node("Japan")]))
    return calls


def test_subscription_imports_nodes_only_and_disables_arbitrary_settings():
    payload = {"external-controller": "0.0.0.0:9090", "allow-lan": True,
               "tun": {"enable": True}, "proxy-providers": {"other": {"url": "http://internal/secret"}},
               "rules": ["MATCH,DIRECT"], "proxies": [node(**{"dialer-proxy": "DIRECT",
               "interface-name": "eth0", "routing-mark": 123})]}
    nodes = proxy.parse_subscription(yaml.safe_dump(payload).encode())
    assert nodes == [node()]
    config = proxy.build_config({"enabled": True, "nodes": nodes, "selected_node": "Hong Kong"}, "private-token")
    assert config["allow-lan"] is False
    assert config["external-controller"] == "127.0.0.1:19090"
    assert config["rules"] == ["MATCH,JEV-PROXY"]
    assert config["proxy-groups"][0]["proxies"] == ["Hong Kong"]
    assert config["proxy-groups"][0]["empty-fallback"] == "REJECT"
    assert config["tun"] == {"enable": False}
    assert "proxy-providers" not in config


@pytest.mark.parametrize("payload", [
    b"proxies: &nodes [*nodes]",
    b"proxies: []\nproxies: []",
    b"!!python/object/apply:os.system ['echo should-not-execute']",
    b"<html>Subscription expired</html>",
    b"proxies: []",
    b'proxies: [{name: "DIRECT", type: http, server: x, port: 80}]',
    b'proxies: [{name: "a", type: direct, server: x, port: 80}]',
    b'proxies: [{name: "a", type: http, server: x, port: -1}]',
    b'proxies: [{name: "a", type: http, server: x, port: true}]',
])
def test_bad_subscriptions_are_rejected_without_echoing_content(payload):
    with pytest.raises(proxy.ProxyError) as caught:
        proxy.parse_subscription(payload)
    assert str(caught.value).startswith("subscription_")
    assert payload.decode() not in str(caught.value)


def test_subscription_size_is_bounded():
    with pytest.raises(proxy.ProxyError, match="subscription_too_large"):
        proxy.parse_subscription(b"a" * (proxy.MAX_BYTES + 1))


def test_ssr_connection_parameters_are_preserved():
    ssr = node(type="ssr", protocol="auth_aes128_md5", **{"protocol-param": "required-value",
               "obfs": "tls1.2_ticket_auth", "obfs-param": "host.example"})
    assert proxy.parse_subscription(yaml.safe_dump({"proxies": [ssr]}).encode()) == [ssr]


@pytest.mark.parametrize("field", ["certificate", "private-key", "Private_Key"])
def test_plugin_file_credentials_are_rejected(field):
    payload = {"proxies": [node(type="ss", cipher="aes-128-gcm",
               plugin="v2ray-plugin", **{"plugin-opts": {"tls": True, field: "/app/private-secret"}})]}
    with pytest.raises(proxy.ProxyError, match="subscription_unsupported_node"):
        proxy.parse_subscription(yaml.safe_dump(payload).encode())


def test_websocket_and_plugin_paths_and_headers_are_preserved():
    payload = node(type="ss", cipher="aes-128-gcm", plugin="v2ray-plugin", **{
        "plugin-opts": {"tls": True, "host": "proxy.example", "path": "/ws"},
        "ws-opts": {"path": "/ws", "headers": {"Host": "proxy.example"}},
    })
    assert proxy.parse_subscription(yaml.safe_dump({"proxies": [payload]}).encode()) == [payload]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://a:secret@host.test/",
                                "https://host.test/#private", "https://host.test:bad/",
                                "http://host.test/\nvalue", "https://",
                                "https://example.com/\x00PRIVATE", "https://example.com/\x7fPRIVATE",
                                "https://\ud800.example.com/private", "\x00https://example.com/private"])
def test_bad_subscription_urls_are_rejected_without_echo(url):
    with pytest.raises(proxy.ProxyError, match="subscription_url_invalid"):
        proxy.validate_subscription_url(url)


def test_local_test_subscription_url_is_supported():
    assert proxy.validate_subscription_url("http://host.docker.internal:23456/nodes") == "http://host.docker.internal:23456/nodes"


@pytest.mark.asyncio
async def test_disabled_runtime_rejects_instead_of_leaking_to_direct(private_proxy):
    config = yaml.safe_load((proxy.runtime_dir() / "runtime.yaml").read_text("utf-8"))
    assert config["proxies"] == []
    assert config["proxy-groups"][0]["proxies"] == ["REJECT"]
    assert config["rules"] == ["MATCH,JEV-PROXY"]
    assert (await proxy.status())["status"] == "disabled"
    assert not proxy.proxy_enabled()


@pytest.mark.asyncio
async def test_save_blank_preserve_select_restart_and_refresh(private_proxy, monkeypatch):
    url = "https://subscription.example.test/nodes?token=private-subscription-token"
    result = await proxy.update_settings(True, url)
    assert result["status"] == "ready"
    assert result["selected_node"] == "Hong Kong"
    assert result["nodes"] == ["Hong Kong", "Japan"]
    assert result["subscription_configured"] is True
    assert "private" not in json.dumps(result)
    assert proxy.proxy_enabled()
    await proxy.select_node("Japan")
    await proxy.update_settings(True, "")
    assert proxy.load_state()["subscription_url"] == url
    restarted = yaml.safe_load(proxy.prepare_runtime().read_text("utf-8"))
    assert restarted["proxy-groups"][0]["proxies"] == ["Japan", "Hong Kong"]
    monkeypatch.setattr(proxy, "fetch_subscription", AsyncMock(return_value=[node("Other")]))
    refreshed = await proxy.refresh_subscription()
    assert refreshed["selected_node"] == "Other"
    assert proxy.load_state()["subscription_url"] == url
    assert not list(proxy.runtime_dir().glob(".write-*"))
    assert not (proxy.runtime_dir() / "candidate.yaml").exists()
    assert len((proxy.runtime_dir() / "controller.token").read_text()) == 64


@pytest.mark.asyncio
async def test_clear_removes_private_url_and_nodes(private_proxy):
    await proxy.update_settings(True, "https://subscription.example.test/secret")
    result = await proxy.update_settings(False, clear_subscription=True)
    assert result["status"] == "disabled"
    assert result["subscription_configured"] is False
    assert result["nodes"] == []
    assert "private-node-secret" not in (proxy.runtime_dir() / "runtime.yaml").read_text()
    assert "subscription.example.test" not in (proxy.runtime_dir() / "settings.json").read_text()
    with pytest.raises(proxy.ProxyError, match="subscription_required"):
        await proxy.update_settings(True)


@pytest.mark.asyncio
async def test_refresh_failure_preserves_working_nodes_and_route(private_proxy, monkeypatch):
    await proxy.update_settings(True, "https://subscription.example.test/secret")
    before = {name: (proxy.runtime_dir() / name).read_bytes() for name in ["settings.json", "runtime.yaml"]}
    monkeypatch.setattr(proxy, "fetch_subscription", AsyncMock(side_effect=proxy.ProxyError("subscription_fetch_failed")))
    with pytest.raises(proxy.ProxyError, match="subscription_fetch_failed"):
        await proxy.refresh_subscription()
    assert all((proxy.runtime_dir() / name).read_bytes() == content for name, content in before.items())
    assert proxy.proxy_enabled()


@pytest.mark.asyncio
async def test_invalid_core_config_and_reload_failures_never_commit(private_proxy, monkeypatch):
    await proxy.update_settings(True, "https://subscription.example.test/secret")
    before = {name: (proxy.runtime_dir() / name).read_bytes() for name in ["settings.json", "runtime.yaml"]}
    validator = AsyncMock(side_effect=proxy.ProxyError("proxy_config_rejected"))
    monkeypatch.setattr(proxy, "_validate_runtime", validator)
    with pytest.raises(proxy.ProxyError, match="proxy_config_rejected"):
        await proxy.select_node("Japan")
    assert all((proxy.runtime_dir() / name).read_bytes() == content for name, content in before.items())
    monkeypatch.setattr(proxy, "_validate_runtime", AsyncMock())
    controller = AsyncMock(side_effect=proxy.ProxyError("proxy_controller_unavailable"))
    monkeypatch.setattr(proxy, "_controller", controller)
    with pytest.raises(proxy.ProxyError, match="proxy_controller_unavailable"):
        await proxy.select_node("Japan")
    assert controller.await_count == 2  # attempted reload and rollback
    assert all((proxy.runtime_dir() / name).read_bytes() == content for name, content in before.items())
    assert not (proxy.runtime_dir() / "candidate.yaml").exists()


@pytest.mark.asyncio
async def test_serialized_state_size_checked_before_runtime_mutation(private_proxy, monkeypatch):
    before = (proxy.runtime_dir() / "runtime.yaml").read_bytes()
    monkeypatch.setattr(proxy, "MAX_BYTES", 1000)
    monkeypatch.setattr(proxy, "fetch_subscription", AsyncMock(return_value=[node(password="\\" * 800)]))
    with pytest.raises(proxy.ProxyError, match="subscription_too_large"):
        await proxy.update_settings(True, "https://subscription.example.test/secret")
    assert (proxy.runtime_dir() / "runtime.yaml").read_bytes() == before
    assert not (proxy.runtime_dir() / "settings.json").exists()


@pytest.mark.asyncio
async def test_corrupted_settings_fail_closed(private_proxy):
    (proxy.runtime_dir() / "settings.json").write_text('{"enabled":"false"}', "utf-8")
    with pytest.raises(proxy.ProxyError, match="proxy_state_invalid"):
        proxy.proxy_enabled()
    assert (await proxy.status())["status"] == "error"
    transport = BundledJevTransport()
    transport.direct.handle_async_request = AsyncMock()
    transport.proxy.handle_async_request = AsyncMock()
    try:
        with pytest.raises(httpx.ConnectError, match="settings are unavailable"):
            await transport.handle_async_request(httpx.Request("GET", "https://api.typesafe.ai/v1/systemone"))
        transport.direct.handle_async_request.assert_not_called()
        transport.proxy.handle_async_request.assert_not_called()
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_routing_changes_apply_to_existing_clients_and_never_fall_back(private_proxy):
    transport = BundledJevTransport()
    request = httpx.Request("GET", "https://api.typesafe.ai/v1/systemone")
    transport.direct.handle_async_request = AsyncMock(return_value=httpx.Response(200))
    transport.proxy.handle_async_request = AsyncMock(side_effect=httpx.ConnectError("node offline", request=request))
    try:
        assert (await transport.handle_async_request(request)).status_code == 200
        await proxy.update_settings(True, "https://subscription.example.test/secret")
        with pytest.raises(httpx.ConnectError, match="node offline"):
            await transport.handle_async_request(request)
        assert transport.direct.handle_async_request.await_count == 1
        assert transport.proxy.handle_async_request.await_count == 1
        await proxy.update_settings(False)
        assert (await transport.handle_async_request(request)).status_code == 200
        assert transport.direct.handle_async_request.await_count == 2
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_bundled_route_overrides_legacy_relay_only_for_jev(private_proxy, monkeypatch):
    monkeypatch.setenv("TYPESAFE_RELAY_SOCKET", "/private/old-socket")
    monkeypatch.setenv("TYPESAFE_RELAY_TOKEN", "old-secret")
    monkeypatch.setenv("TYPESAFE_PROXY_URL", "http://old-proxy:7897")
    client = create_semantic_client()
    other = create_semantic_client("semif-local")
    try:
        assert isinstance(client._transport, BundledJevTransport)
        assert not isinstance(other._transport, BundledJevTransport)
        assert jev_request_target("https://api.typesafe.ai/v1/systemone") == ("https://api.typesafe.ai/v1/systemone", {})
    finally:
        await client.aclose()
        await other.aclose()
    monkeypatch.delenv("MEDIACRAWLER_BUNDLED_PROXY")
    assert jev_request_target("https://api.typesafe.ai/v1/systemone") == (
        "http://jev-relay/v1/systemone", {"X-Jev-Relay-Token": "old-secret"})
    assert (await proxy.status())["available"] is False


@pytest.mark.asyncio
async def test_fetch_bounds_and_error_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIACRAWLER_JEV_PROXY_DIR", str(tmp_path / ".jev-proxy"))
    monkeypatch.delenv("MEDIACRAWLER_BUNDLED_PROXY", raising=False)
    original_client = httpx.AsyncClient
    url = "https://subscription.example.test/nodes?token=VERY-PRIVATE"
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text=str(req.url)))
    monkeypatch.setattr(proxy.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs))
    with pytest.raises(proxy.ProxyError, match="^subscription_fetch_failed$"):
        await proxy.fetch_subscription(url)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"a" * (proxy.MAX_BYTES + 1)))
    with pytest.raises(proxy.ProxyError, match="^subscription_too_large$"):
        await proxy.fetch_subscription(url)
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={"Location": "file:///private"}))
    with pytest.raises(proxy.ProxyError, match="^subscription_url_invalid$"):
        await proxy.fetch_subscription(url)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=yaml.safe_dump({"proxies": [node()]}).encode()))
    assert await proxy.fetch_subscription(url) == [node()]


def test_api_never_echoes_subscription_key_or_node_credentials(private_proxy, monkeypatch):
    from api.routers import jev_proxy as routes
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    check = AsyncMock(return_value={"ok": False, "reason": "request_rejected", "http_status": 451})
    monkeypatch.setattr(routes, "check_jev_connection", check)
    with TestClient(app) as client:
        response = client.put("/api/jev-proxy", json={
            "enabled": True, "subscription_url": "https://subscription.example.test/private-subscription"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert "private-subscription" not in response.text and "private-node-secret" not in response.text
        assert response.json()["nodes"] == ["Hong Kong", "Japan"]
        response = client.post("/api/jev-proxy/test", json={"api_key": "private-api-key"})
        assert response.json() == {"ok": False, "reason": "request_rejected", "http_status": 451}
        check.assert_awaited_once_with("private-api-key")
        assert "private-api-key" not in response.text
        assert "private-api-key" not in (proxy.runtime_dir() / "settings.json").read_text()
        response = client.put("/api/jev-proxy", json={
            "enabled": True, "subscription_url": "file:///private-subscription"})
        assert response.json() == {"detail": "subscription_url_invalid"}
        assert "private-subscription" not in response.text
        response = client.put("/api/jev-proxy/node", json={"name": "not-there"})
        assert response.json() == {"detail": "node_not_found"}
        response = client.put("/api/jev-proxy", json={
            "enabled": True, "subscription_url": {"private-subscription": "secret"}})
        assert response.status_code == 422
        assert response.json() == {"detail": "proxy_request_invalid"}
        assert "secret" not in response.text
        response = client.post("/api/jev-proxy/test", json={"api_key": {"secret": "private-api-key"}})
        assert response.json() == {"detail": "proxy_request_invalid"}


def test_private_config_is_not_exposed_by_data_routes(private_proxy, monkeypatch):
    from api.routers import data
    import config
    monkeypatch.setattr(config, "SAVE_DATA_PATH", "")
    monkeypatch.setattr(data, "DATA_DIR", proxy.runtime_dir().parent)
    app = FastAPI()
    app.include_router(data.router, prefix="/api")
    with TestClient(app) as client:
        for name in ("settings.json", "controller.token", "runtime.yaml"):
            for endpoint in ("download", "files"):
                response = client.get(f"/api/data/{endpoint}/.jev-proxy/{name}")
                assert response.status_code == 403
        assert client.get("/api/data/files").json()["files"] == []
