"""Private, opt-in Mihomo configuration for Jev only.

Subscriptions are imported as nodes, never as executable service configuration.
The controller and HTTP proxy stay on container loopback. No API keys are saved.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urljoin, urlsplit

import httpx
import yaml

PROXY_URL = "http://127.0.0.1:17890"
CONTROLLER_URL = "http://127.0.0.1:19090"
GROUP = "JEV-PROXY"
MAX_BYTES = 2 * 1024 * 1024
MAX_NODES = 500
_lock = asyncio.Lock()
_NODE_FIELDS = {
    "name", "type", "server", "port", "cipher", "password", "username",
    "uuid", "alterId", "tls", "skip-cert-verify", "servername", "sni",
    "network", "udp", "packet-encoding", "flow", "client-fingerprint",
    "ws-opts", "grpc-opts", "http-opts", "h2-opts", "reality-opts",
    "plugin", "plugin-opts", "obfs", "obfs-password", "auth-str", "auth",
    "alpn", "up", "down", "ports", "hop-interval", "disable-sni",
    "reduce-rtt", "congestion-controller", "udp-relay-mode",
    "udp-over-stream", "fast-open", "heartbeat-interval", "request-timeout",
    "ip-version", "fingerprint", "tfo", "protocol", "protocol-param", "obfs-param",
}
_NODE_TYPES = {"ss", "ssr", "vmess", "vless", "trojan", "hysteria",
               "hysteria2", "tuic", "http", "socks5"}


class ProxyError(ValueError):
    """Only stable, non-secret codes may cross the HTTP boundary."""


def bundled_available() -> bool:
    return os.environ.get("MEDIACRAWLER_BUNDLED_PROXY") == "1"


def runtime_dir() -> Path:
    return Path(os.environ.get("MEDIACRAWLER_JEV_PROXY_DIR",
                               str(Path(__file__).resolve().parent / "data" / ".jev-proxy")))


def _private_dir() -> Path:
    directory = runtime_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    except OSError:
        raise ProxyError("proxy_storage_error") from None
    return directory


def _atomic_write(path: Path, content: bytes) -> None:
    directory = _private_dir()
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-", delete=False) as stream:
            temp_name = stream.name
            os.chmod(temp_name, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        path.chmod(0o600)
    except OSError:
        raise ProxyError("proxy_storage_error") from None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _bounded_read(path: Path) -> bytes:
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ProxyError("proxy_state_invalid")
    return content


def _empty_state() -> dict:
    return {"enabled": False, "subscription_url": "", "nodes": [], "selected_node": ""}


def _simple_value(value, depth=0):
    if depth > 8:
        raise ProxyError("subscription_invalid")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str) and len(value) <= 8192 and "\0" not in value:
        return value
    if isinstance(value, list) and len(value) <= 256:
        return [_simple_value(item, depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= 128:
        if any(not isinstance(key, str) or len(key) > 200 for key in value):
            raise ProxyError("subscription_invalid")
        return {key: _simple_value(item, depth + 1) for key, item in value.items()}
    raise ProxyError("subscription_invalid")


def _reject_plugin_files(value):
    """Plugin TLS credentials may be file paths in Mihomo; never import them."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            if normalized in {"certificate", "privatekey"}:
                raise ProxyError("subscription_unsupported_node")
            _reject_plugin_files(item)
    elif isinstance(value, list):
        for item in value:
            _reject_plugin_files(item)


def sanitize_nodes(nodes) -> list[dict]:
    if not isinstance(nodes, list) or not nodes:
        raise ProxyError("subscription_no_nodes")
    if len(nodes) > MAX_NODES:
        raise ProxyError("subscription_too_large")
    result, names = [], set()
    for item in nodes:
        if not isinstance(item, dict):
            raise ProxyError("subscription_invalid")
        name, node_type = item.get("name"), item.get("type")
        if (not isinstance(name, str) or not name.strip() or len(name) > 200
                or any(ord(char) < 32 for char in name)
                or name in {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE", GLOBAL_NAME, GROUP}
                or name in names):
            raise ProxyError("subscription_invalid")
        if node_type not in _NODE_TYPES:
            raise ProxyError("subscription_unsupported_node")
        server, port = item.get("server"), item.get("port")
        if not isinstance(server, str) or not server or len(server) > 253 or any(char.isspace() for char in server):
            raise ProxyError("subscription_invalid")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ProxyError("subscription_invalid")
        if item.get("plugin") not in (None, "", "obfs", "v2ray-plugin", "shadow-tls", "restls"):
            raise ProxyError("subscription_unsupported_node")
        # These options are connection settings. Routing, listeners, processes,
        # providers, dialer proxies, interface names and file paths are discarded.
        clean = {key: _simple_value(value) for key, value in item.items() if key in _NODE_FIELDS}
        _reject_plugin_files(clean.get("plugin-opts"))
        names.add(name)
        result.append(clean)
    return result


GLOBAL_NAME = "GLOBAL"


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ProxyError("subscription_invalid")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def parse_subscription(content: bytes) -> list[dict]:
    if len(content) > MAX_BYTES:
        raise ProxyError("subscription_too_large")
    try:
        text = content.decode("utf-8-sig")
        # No aliases/anchors: avoid cyclic graphs and expansion bombs before load.
        depth = 0
        for token in yaml.scan(text):
            if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)):
                raise ProxyError("subscription_invalid")
            if isinstance(token, (yaml.tokens.FlowSequenceStartToken, yaml.tokens.FlowMappingStartToken,
                                  yaml.tokens.BlockSequenceStartToken, yaml.tokens.BlockMappingStartToken)):
                depth += 1
                if depth > 16:
                    raise ProxyError("subscription_invalid")
            elif isinstance(token, (yaml.tokens.FlowSequenceEndToken, yaml.tokens.FlowMappingEndToken,
                                    yaml.tokens.BlockEndToken)):
                depth -= 1
        value = yaml.load(text, Loader=_UniqueSafeLoader)
        if not isinstance(value, dict):
            raise ProxyError("subscription_invalid")
        return sanitize_nodes(value.get("proxies"))
    except ProxyError:
        raise
    except (UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError):
        raise ProxyError("subscription_invalid") from None


def validate_subscription_url(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProxyError("subscription_url_invalid")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (len(value) > 4096 or parsed.scheme not in {"http", "https"}
                or not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                or any(char.isspace() for char in value)):
            raise ValueError()
        _ = parsed.port
        # urllib accepts some malformed IDNA and character combinations that
        # HTTPX rejects later. Validate with the client parser before any fetch.
        if not httpx.URL(value).host:
            raise ValueError()
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise ProxyError("subscription_url_invalid") from None
    return value


def load_state() -> dict:
    path = runtime_dir() / "settings.json"
    try:
        state = json.loads(_bounded_read(path))
        if not isinstance(state, dict) or type(state.get("enabled")) is not bool:
            raise ValueError()
        if not isinstance(state.get("subscription_url"), str) or not isinstance(state.get("selected_node"), str):
            raise ValueError()
        nodes = sanitize_nodes(state["nodes"]) if state.get("nodes") else []
        if not isinstance(state.get("nodes"), list):
            raise ValueError()
        if state["enabled"] and (not nodes or state["selected_node"] not in {node["name"] for node in nodes}):
            raise ValueError()
        return {**_empty_state(), **state, "nodes": nodes}
    except FileNotFoundError:
        return _empty_state()
    except (OSError, ValueError, TypeError, KeyError):
        raise ProxyError("proxy_state_invalid") from None


def proxy_enabled() -> bool:
    """Read on each Jev request; corrupt state fails closed."""
    return bundled_available() and load_state()["enabled"]


def controller_token() -> str:
    path = runtime_dir() / "controller.token"
    try:
        token = _bounded_read(path).decode("ascii").strip()
        if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
            raise ProxyError("proxy_state_invalid")
        return token
    except FileNotFoundError:
        token = secrets.token_hex(32)
        _atomic_write(path, token.encode("ascii"))
        return token
    except (OSError, UnicodeError):
        raise ProxyError("proxy_state_invalid") from None


def build_config(state: dict, token: str) -> dict:
    nodes = state["nodes"] if state["enabled"] else []
    names = [node["name"] for node in nodes]
    selected = state["selected_node"]
    if selected in names:
        names.remove(selected)
        names.insert(0, selected)
    return {
        "mixed-port": 17890, "allow-lan": False, "bind-address": "127.0.0.1",
        "external-controller": "127.0.0.1:19090", "secret": token,
        "mode": "rule", "log-level": "silent", "ipv6": False,
        "profile": {"store-selected": False, "store-fake-ip": False},
        "tun": {"enable": False}, "dns": {"enable": False},
        "sniffer": {"enable": False}, "proxies": nodes,
        "proxy-groups": [{"name": GROUP, "type": "select", "proxies": names or ["REJECT"],
                          "empty-fallback": "REJECT"}],
        "rules": [f"MATCH,{GROUP}"],
    }


def prepare_runtime() -> Path:
    """Entrypoint helper: start `mihomo -d runtime_dir() -f prepare_runtime()`.

    Uses cached nodes only; startup never downloads a subscription.
    """
    path = runtime_dir() / "runtime.yaml"
    state = load_state()
    config = build_config(state, controller_token())
    _atomic_write(path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode("utf-8"))
    return path


async def fetch_subscription(url: str) -> list[dict]:
    current = validate_subscription_url(url)
    try:
        # Downloads use the current node when already enabled; the first import
        # is direct and never installs arbitrary provider URLs from YAML.
        proxy = PROXY_URL if proxy_enabled() else None
        async with asyncio.timeout(35):
            async with httpx.AsyncClient(proxy=proxy, trust_env=False, timeout=15, follow_redirects=False) as client:
                for _ in range(4):
                    async with client.stream("GET", current, headers={"User-Agent": "clash.meta/MediaCrawler"}) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ProxyError("subscription_fetch_failed")
                            current = validate_subscription_url(urljoin(current, location))
                            continue
                        if response.status_code != 200:
                            raise ProxyError("subscription_fetch_failed")
                        chunks, length = [], 0
                        async for chunk in response.aiter_bytes():
                            length += len(chunk)
                            if length > MAX_BYTES:
                                raise ProxyError("subscription_too_large")
                            chunks.append(chunk)
                        return parse_subscription(b"".join(chunks))
    except ProxyError:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, OSError, TimeoutError):
        raise ProxyError("subscription_fetch_failed") from None
    raise ProxyError("subscription_fetch_failed")


async def _controller(method: str, path: str, **kwargs) -> dict:
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=8) as client:
            response = await client.request(method, CONTROLLER_URL + path,
                headers={"Authorization": "Bearer " + controller_token()}, **kwargs)
            if response.status_code >= 400:
                raise ProxyError("proxy_controller_unavailable")
            return response.json() if response.content else {}
    except ProxyError:
        raise
    except (httpx.HTTPError, OSError, ValueError):
        raise ProxyError("proxy_controller_unavailable") from None


async def _validate_runtime(path: Path) -> None:
    """Let the bundled core validate protocol-specific fields without logging secrets."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            os.environ.get("MEDIACRAWLER_MIHOMO_BIN", "mihomo"),
            "-t", "-d", str(runtime_dir()), "-f", str(path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await asyncio.wait_for(process.wait(), 15) != 0:
            raise ProxyError("proxy_config_rejected")
    except ProxyError:
        raise
    except (OSError, TimeoutError):
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise ProxyError("proxy_config_rejected") from None


async def _install_state(state: dict) -> None:
    """Validate, reload, then commit. A failed reload never becomes saved routing."""
    directory = _private_dir()
    candidate = directory / "candidate.yaml"
    runtime = directory / "runtime.yaml"
    config = yaml.safe_dump(build_config(state, controller_token()), allow_unicode=True, sort_keys=False).encode("utf-8")
    serialized_state = json.dumps(state, ensure_ascii=False).encode("utf-8")
    if len(config) > MAX_BYTES or len(serialized_state) > MAX_BYTES:
        raise ProxyError("subscription_too_large")
    _atomic_write(candidate, config)
    try:
        await _validate_runtime(candidate)
        old_config = _bounded_read(runtime) if runtime.exists() else None
        _atomic_write(runtime, config)
        try:
            await _controller("PUT", "/configs?force=true", json={"path": str(runtime.resolve())})
            if state["enabled"]:
                await _controller("PUT", f"/proxies/{GROUP}", json={"name": state["selected_node"]})
            _atomic_write(directory / "settings.json", serialized_state)
        except BaseException:
            # Restoring the config on disk also gives a safe state after restart.
            if old_config is not None:
                _atomic_write(runtime, old_config)
                try:
                    await _controller("PUT", "/configs?force=true", json={"path": str(runtime.resolve())})
                except ProxyError:
                    pass
            raise
    finally:
        candidate.unlink(missing_ok=True)


def _require_available():
    if not bundled_available():
        raise ProxyError("proxy_unavailable")


async def status() -> dict:
    result = {"available": bundled_available(), "enabled": False,
              "subscription_configured": False, "nodes": [], "selected_node": "",
              "status": "unavailable", "message": "当前环境未启用内置 Jev 代理。"}
    if not result["available"]:
        return result
    try:
        state = load_state()
        result.update(enabled=state["enabled"],
                      subscription_configured=bool(state["subscription_url"]),
                      nodes=[node["name"] for node in state["nodes"]],
                      selected_node=state["selected_node"])
        if not state["enabled"]:
            result.update(status="disabled", message="内置代理已关闭；Jev 使用直连。")
        else:
            group = await _controller("GET", f"/proxies/{GROUP}")
            if group.get("now") != state["selected_node"]:
                raise ProxyError("proxy_controller_unavailable")
            result.update(status="ready", message="Jev 已配置为通过所选节点访问；请测试 API 确认可用。")
    except ProxyError:
        result.update(status="error", message="内置代理暂不可用，请刷新订阅或检查容器状态。")
    return result


async def update_settings(enabled: bool, subscription_url: str = "", clear_subscription: bool = False) -> dict:
    _require_available()
    async with _lock:
        state = load_state()
        if clear_subscription:
            if enabled:
                raise ProxyError("subscription_required")
            state = _empty_state()
        else:
            if subscription_url.strip():
                state["subscription_url"] = validate_subscription_url(subscription_url)
                state["nodes"] = await fetch_subscription(state["subscription_url"])
            names = [node["name"] for node in state["nodes"]]
            if state["selected_node"] not in names:
                state["selected_node"] = names[0] if names else ""
            if enabled and not names:
                raise ProxyError("subscription_required")
            state["enabled"] = enabled
        await _install_state(state)
    return await status()


async def refresh_subscription() -> dict:
    _require_available()
    async with _lock:
        state = load_state()
        if not state["subscription_url"]:
            raise ProxyError("subscription_required")
        state["nodes"] = await fetch_subscription(state["subscription_url"])
        names = [node["name"] for node in state["nodes"]]
        if state["selected_node"] not in names:
            state["selected_node"] = names[0]
        await _install_state(state)
    return await status()


async def select_node(name: str) -> dict:
    _require_available()
    async with _lock:
        state = load_state()
        if name not in {node["name"] for node in state["nodes"]}:
            raise ProxyError("node_not_found")
        state["selected_node"] = name
        await _install_state(state)
    return await status()
