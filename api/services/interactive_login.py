"""Optional container desktop login; human verification stays in the same context."""
import asyncio
import os
import time

from playwright.async_api import async_playwright, Error as BrowserError

LOGIN_TIMEOUT = 600


def desktop_enabled():
    return (os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1'
            and os.environ.get('MEDIACRAWLER_DESKTOP_LOGIN') == '1'
            and bool(os.environ.get('DISPLAY')))


def desktop_status():
    return {'desktop_available': desktop_enabled(),
            'desktop_port': int(os.environ.get('DESKTOP_PUBLIC_PORT', '6080'))}


async def run_interactive_login(service, refresh, platform):
    """Only persist after platform authentication, never just after clearing a challenge."""
    if platform == 'wb':
        from media_platform.weibo.session import read_session, save_session
        from api.services.weibo_login import SIGNIN, MOBILE
        start_url = SIGNIN
    else:
        from media_platform.xhs.session import read_session, save_session
        from api.services.xhs_login import HOME
        start_url = HOME
    from login_environment import web_login_browser_channel

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel=web_login_browser_channel(), headless=False)
            try:
                saved = None if refresh else read_session(service.root)
                context = await browser.new_context(storage_state=saved, viewport={'width': 1100, 'height': 760})
                page = await context.new_page()
                await page.goto(start_url, wait_until='domcontentloaded', timeout=30000)
                if saved:
                    valid = (await service.mobile_authenticated(context) if platform == 'wb'
                             else await service.authenticated(page, context))
                    if valid:
                        save_session(service.root, await context.storage_state())
                        service.state.update(status='authenticated', qr_image=None, expires_at=None, reason=None)
                        return
                    # Discard stale credentials from the *new* attempt, not the saved file.
                    await context.close()
                    context = await browser.new_context(viewport={'width': 1100, 'height': 760})
                    page = await context.new_page()
                    await page.goto(start_url, wait_until='domcontentloaded', timeout=30000)
                expires = time.time() + LOGIN_TIMEOUT
                service.state.update(expires_at=expires)
                bridged = False
                opened = False
                while time.time() < expires:
                    if platform == 'wb':
                        authenticated = await service.mobile_authenticated(context)
                    else:
                        authenticated = await service.authenticated(page, context)
                    if authenticated:
                        save_session(service.root, await context.storage_state())
                        service.state.update(status='authenticated', qr_image=None, expires_at=None, reason=None)
                        return
                    if await service.verification_required(page):
                        service.state.update(status='verification_required', qr_image=None,
                                             reason=service.state.get('reason') or 'login_verification_required')
                        # Leave this exact page/context alive for human interaction.
                        await asyncio.sleep(2)
                        continue
                    if platform == 'wb' and not bridged:
                        cookies = await context.cookies()
                        if any(c['name'] == 'SUB' for c in cookies):
                            bridged = True
                            await page.goto(MOBILE, wait_until='domcontentloaded', timeout=20000)
                            continue
                    if platform == 'xhs' and not opened:
                        await service.open_login(page)
                        opened = True
                    qr = await service.find_qr(page)
                    service.state.update(status='waiting', qr_image=qr, reason=None)
                    await asyncio.sleep(2)
                service.state.update(status='expired', qr_image=None, expires_at=None, reason='qrcode_expired')
            finally:
                await browser.close()
    except asyncio.CancelledError:
        service.state.update(status='cancelled', qr_image=None, expires_at=None, reason=None)
        raise
    except OSError:
        service.state.update(status='error', qr_image=None, expires_at=None, reason='login_save_failed')
    except (BrowserError, ValueError, TypeError):
        service.state.update(status='error', qr_image=None, expires_at=None, reason='login_browser_error')
