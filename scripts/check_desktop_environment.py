"""Check a distributed desktop installation without account login or collection."""
import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def check_browser(channel):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=channel, headless=True)
        try:
            page = await browser.new_page()
            await page.goto('about:blank')
        finally:
            await browser.close()
    print(f'Browser OK: {channel}')


def initialize():
    # Import the real application and crawler; never start either in this probe.
    import api.main
    import main
    import execjs
    assert execjs.eval('1 + 1') == 2
    from image_subject_settings import settings_path, save_settings
    from image_subject import model_ready
    root = ROOT / 'data'
    root.mkdir(exist_ok=True)
    if not settings_path(root).exists() and not model_ready():
        save_settings(root, 'siliconflow')
    print('Application imports and JavaScript runtime OK; existing settings preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser-only', action='store_true')
    parser.add_argument('--channel', default='chromium')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--check-python-env', action='store_true')
    args = parser.parse_args()
    try:
        if args.check_python_env:
            assert sys.version_info[:2] == (3, 11)
            assert Path(sys.prefix).resolve() == (ROOT / '.venv').resolve()
        elif args.browser_only:
            asyncio.run(check_browser(args.channel))
        elif args.initialize:
            initialize()
    except Exception as exc:
        print(f'Environment check failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
