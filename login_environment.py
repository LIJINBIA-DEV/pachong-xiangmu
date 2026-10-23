"""Resolve UI login modes without changing the backend host or parent environment."""
import os
import sys


def default_login_environment():
    return 'server' if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1' else 'local'


def local_login_available():
    return os.environ.get('MEDIACRAWLER_CONTAINER_MODE') != '1' and (
        sys.platform in ('win32', 'darwin') or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')))


def resolve_login_environment(value='auto'):
    mode = default_login_environment() if value == 'auto' else value
    if mode not in ('local', 'server'):
        raise ValueError('未知登录环境')
    if mode == 'local' and not local_login_available():
        raise ValueError('当前后端没有本机桌面，请选择服务器版登录。')
    return mode


def login_process_environment(mode):
    return {'MEDIACRAWLER_LOGIN_ENVIRONMENT': mode,
            'MEDIACRAWLER_CONTAINER_MODE': '1' if mode == 'server' else '0'}


def web_login_browser_channel():
    configured = os.environ.get('MEDIACRAWLER_BROWSER_CHANNEL')
    if configured:
        return configured
    if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1':
        return 'chromium'
    from tools.browser_launcher import BrowserLauncher
    paths = BrowserLauncher().detect_browser_paths()
    for path in paths:
        if 'chrome' in path.lower():
            return 'chrome'
        if 'msedge' in path.lower():
            return 'msedge'
    return 'chromium'
