"""Display the official Xiaohongshu QR in the workbench; keep credentials private."""
import asyncio
import base64
import os
import re
import time

from playwright.async_api import async_playwright, Error as BrowserError

from api.services.weibo_login import WeiboWebLogin
from media_platform.xhs.session import read_session, save_session

HOME = 'https://www.xiaohongshu.com/explore'
QR_TTL = 120
PROFILE = "xpath=//a[contains(@href, '/user/profile/')]//span[normalize-space(text())='我']"


class XhsWebLogin(WeiboWebLogin):
    # Reuse the task/lock/cancellation lifecycle, not Weibo's authentication logic.
    def status(self):
        from api.services.interactive_login import desktop_status
        return {**self.state, 'busy': self.busy, 'saved_session': bool(read_session(self.root)),
                **desktop_status(),
                'supported': os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1'}

    async def authenticated(self, page, context):
        # Guest web_session cookies exist too: require the site's signed-in profile UI.
        if not await page.locator(PROFILE).first.is_visible():
            return False
        cookies = await context.cookies(['https://www.xiaohongshu.com'])
        return any(c.get('name') == 'web_session' and c.get('value') for c in cookies)

    async def verification_required(self, page):
        body = await page.locator('body').inner_text(timeout=3000)
        if re.search(r'IP at risk|300012|网络环境存在风险', body, re.I):
            self.state['reason'] = 'login_network_restricted'
            return True
        return bool(re.search(r'请通过验证|完成安全验证|滑动.{0,12}验证|请.{0,12}验证身份|账号异常|访问异常|访问频繁', body))

    async def find_qr(self, page):
        images = page.locator('img.qrcode-img')
        for index in range(await images.count()):
            candidate = images.nth(index)
            if await candidate.is_visible():
                dimensions = await candidate.evaluate('(e) => [e.naturalWidth, e.naturalHeight]')
                if min(dimensions) >= 100 and 0.8 < dimensions[0] / dimensions[1] < 1.2:
                    return 'data:image/png;base64,' + base64.b64encode(await candidate.screenshot(timeout=5000)).decode()
        return None

    async def open_login(self, page):
        button = page.get_by_role('button', name='登录', exact=True).first
        if await button.is_visible():
            await button.click(timeout=3000)

    async def _run(self, refresh):
        from api.services.interactive_login import desktop_enabled, run_interactive_login
        if desktop_enabled():
            await run_interactive_login(self, refresh, 'xhs')
            return
        browser = None
        try:
            async with async_playwright() as playwright:
                from login_environment import web_login_browser_channel
                browser = await playwright.chromium.launch(channel=web_login_browser_channel(), headless=True)
                saved = None if refresh else read_session(self.root)
                context = await browser.new_context(storage_state=saved, viewport={'width': 1280, 'height': 900})
                try:
                    page = await context.new_page()
                    await page.goto(HOME, wait_until='domcontentloaded', timeout=30000)
                    if await self.verification_required(page):
                        self.state.update(status='verification_required', qr_image=None,
                                          reason=self.state.get('reason') or 'login_verification_required')
                        return
                    if saved:
                        for _ in range(5):
                            if await self.authenticated(page, context):
                                save_session(self.root, await context.storage_state())
                                self.state.update(status='authenticated', qr_image=None, expires_at=None)
                                return
                            await asyncio.sleep(1)
                        await context.close()
                        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
                        page = await context.new_page()
                        await page.goto(HOME, wait_until='domcontentloaded', timeout=30000)
                    qr = None
                    for attempt in range(30):
                        if await self.verification_required(page):
                            self.state.update(status='verification_required', qr_image=None, expires_at=None,
                                              reason=self.state.get('reason') or 'login_verification_required')
                            return
                        qr = await self.find_qr(page)
                        if qr:
                            break
                        if attempt in (2, 10):
                            await self.open_login(page)
                        await asyncio.sleep(1)
                    if not qr:
                        self.state.update(status='error', reason='qrcode_unavailable')
                        return
                    expires = time.time() + QR_TTL
                    self.state.update(status='waiting', qr_image=qr, expires_at=expires)
                    while time.time() < expires:
                        if await self.verification_required(page):
                            self.state.update(status='verification_required', qr_image=None, expires_at=None,
                                              reason=self.state.get('reason') or 'login_verification_required')
                            return
                        if await self.authenticated(page, context):
                            save_session(self.root, await context.storage_state())
                            self.state.update(status='authenticated', qr_image=None, expires_at=None)
                            return
                        # Reflect a refreshed QR displayed by the site without extending our TTL.
                        current_qr = await self.find_qr(page)
                        if current_qr:
                            self.state['qr_image'] = current_qr
                        body = await page.locator('body').inner_text(timeout=3000)
                        if re.search(r'二维码.{0,6}(过期|失效)', body):
                            break
                        await asyncio.sleep(2)
                    self.state.update(status='expired', qr_image=None, expires_at=None, reason='qrcode_expired')
                finally:
                    await context.close()
                    await browser.close()
                    browser = None
        except asyncio.CancelledError:
            self.state.update(status='cancelled', qr_image=None, expires_at=None)
            raise
        except OSError:
            self.state.update(status='error', qr_image=None, expires_at=None, reason='login_save_failed')
        except (BrowserError, ValueError, TypeError):
            self.state.update(status='error', qr_image=None, expires_at=None, reason='login_browser_error')
        finally:
            if browser:
                try:
                    await browser.close()
                except BrowserError:
                    pass


xhs_web_login = XhsWebLogin()
