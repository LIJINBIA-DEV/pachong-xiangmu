"""Headless official Weibo QR login; no tokens or Cookie values leave this service."""
import asyncio
import base64
import os
from pathlib import Path
import re
import secrets
import time

from playwright.async_api import async_playwright, Error as BrowserError
from media_platform.weibo.session import read_session, save_session

SIGNIN = 'https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog'
MOBILE = 'https://m.weibo.cn'
QR_TTL = 180


class WeiboWebLogin:
    def __init__(self, project_root=None):
        self.root = Path(project_root or Path(__file__).resolve().parents[2])
        self.task = None
        self.state = {'status': 'idle', 'qr_image': None, 'expires_at': None, 'reason': None}

    @property
    def busy(self):
        return bool(self.task and not self.task.done())

    def status(self):
        from api.services.interactive_login import desktop_status
        return {**self.state, 'busy': self.busy, 'saved_session': bool(read_session(self.root)),
                **desktop_status(),
                'supported': os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1'}

    async def start(self, manager, refresh=False, login_environment='auto'):
        from login_environment import resolve_login_environment
        if resolve_login_environment(login_environment) != 'server':
            raise ValueError('web_login_unsupported')
        async with manager._lock:
            if manager.status in {'running', 'stopping'} or (manager.process and manager.process.poll() is None):
                raise ValueError('collection_active')
            from api.services.xhs_login import xhs_web_login
            for other in (weibo_web_login, xhs_web_login):
                if other is not self and other.busy:
                    raise ValueError('other_platform_login_active')
            await self.close()
            self.state = {'status': 'loading', 'qr_image': None, 'expires_at': None, 'reason': None,
                          'attempt_id': secrets.token_hex(8)}
            self.task = asyncio.create_task(self._run(refresh))
            return self.status()

    async def cancel(self, manager):
        async with manager._lock:
            await self.close()
            self.state.update(status='cancelled', qr_image=None, expires_at=None, reason=None)
            return self.status()

    async def close(self):
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def mobile_authenticated(self, context):
        try:
            response = await context.request.get(MOBILE + '/api/config', timeout=8000)
            if response.status != 200:
                return False
            value = await response.json()
            return value.get('ok') == 1 and value.get('data', {}).get('login') in (True, 1)
        except (BrowserError, ValueError, AttributeError, TypeError):
            return False

    async def verification_required(self, page):
        body = await page.locator('body').inner_text(timeout=3000)
        return bool(re.search(r'完成安全验证|滑动.{0,12}验证|请.{0,12}验证身份|账号异常|访问异常|访问频繁', body))

    async def find_qr(self, page):
        # Prefer the site's existing QR image, then known QR-specific image/canvas selectors.
        for selector in ('img.w-full.h-full', 'img[src*="qrcode"],img[alt*="二维码"],canvas'):
            images = page.locator(selector)
            for index in range(await images.count()):
                candidate = images.nth(index)
                if await candidate.is_visible():
                    dimensions = await candidate.evaluate('(e) => [e.tagName === "IMG" ? e.naturalWidth : e.width, e.tagName === "IMG" ? e.naturalHeight : e.height]')
                    if dimensions[0] < 120 or dimensions[1] < 120 or not 0.8 < dimensions[0] / dimensions[1] < 1.2:
                        continue
                    return 'data:image/png;base64,' + base64.b64encode(await candidate.screenshot(timeout=5000)).decode()
        return None

    async def _run(self, refresh):
        from api.services.interactive_login import desktop_enabled, run_interactive_login
        if desktop_enabled():
            await run_interactive_login(self, refresh, 'wb')
            return
        browser = None
        try:
            async with async_playwright() as playwright:
                from login_environment import web_login_browser_channel
                browser = await playwright.chromium.launch(channel=web_login_browser_channel(), headless=True)
                saved = None if refresh else read_session(self.root)
                context = await browser.new_context(storage_state=saved, viewport={'width': 1100, 'height': 800})
                try:
                    if saved and await self.mobile_authenticated(context):
                        save_session(self.root, await context.storage_state())
                        self.state.update(status='authenticated', qr_image=None)
                        return
                    # A stale saved session must not contaminate the fresh QR login.
                    if saved:
                        await context.close()
                        context = await browser.new_context(viewport={'width': 1100, 'height': 800})
                    page = await context.new_page()
                    await page.goto(SIGNIN, wait_until='domcontentloaded', timeout=30000)
                    qr = None
                    for _ in range(30):
                        qr = await self.find_qr(page)
                        if qr:
                            break
                        if await self.verification_required(page):
                            self.state.update(status='verification_required', reason='login_verification_required')
                            return
                        await asyncio.sleep(1)
                    if not qr:
                        self.state.update(status='error', reason='qrcode_unavailable')
                        return
                    expires = time.time() + QR_TTL
                    self.state.update(status='waiting', qr_image=qr, expires_at=expires)
                    bridged = False
                    while time.time() < expires:
                        if await self.mobile_authenticated(context):
                            save_session(self.root, await context.storage_state())
                            self.state.update(status='authenticated', qr_image=None, expires_at=None)
                            return
                        # Official SSO may first set .weibo.com cookies; let the mobile page
                        # perform its own SSO redirect instead of copying domains by hand.
                        if not bridged:
                            cookies = await context.cookies()
                            if any(cookie['name'] == 'SUB' for cookie in cookies):
                                bridged = True
                                self.state.update(status='checking', qr_image=None)
                                await page.goto(MOBILE, wait_until='domcontentloaded', timeout=20000)
                        if await self.verification_required(page):
                            self.state.update(status='verification_required', qr_image=None, reason='login_verification_required')
                            return
                        await asyncio.sleep(2)
                    self.state.update(status='expired', qr_image=None, reason='qrcode_expired')
                finally:
                    await context.close()
                    await browser.close()
                    browser = None
        except asyncio.CancelledError:
            self.state.update(status='cancelled', qr_image=None, expires_at=None)
            raise
        except OSError:
            self.state.update(status='error', qr_image=None, reason='login_save_failed')
        except (BrowserError, ValueError, TypeError):
            self.state.update(status='error', qr_image=None, reason='login_browser_error')
        finally:
            if browser:
                try:
                    await browser.close()
                except BrowserError:
                    pass


weibo_web_login = WeiboWebLogin()
