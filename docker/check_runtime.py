"""Build-time checks against the code and browser actually copied into the image.

No crawling, external requests, model calls, or changes to collection/review data.
"""
import asyncio
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


def check_application():
    from api.main import app
    from api.services.review_export import HEADERS, TIMEZONE, export_review
    from image_subject_settings import CLOUD_MODEL, runtime_settings
    from media_platform.weibo.core import WeiboCrawler
    import config

    root = Path(__file__).resolve().parents[1]
    assert config.LOGIN_TYPE == 'cookie' and config.HEADLESS and not config.ENABLE_CDP_MODE
    assert runtime_settings(root / 'data')['provider'] == 'siliconflow'
    assert CLOUD_MODEL == 'Qwen/Qwen3.5-4B'
    assert TIMEZONE == ZoneInfo('Asia/Shanghai')
    assert len(HEADERS) == 16 and callable(export_review) and callable(WeiboCrawler)
    routes = {route.path for route in app.routes}
    assert {'/api/health', '/api/crawler/weibo-login', '/api/data/review/export', '/api/data/media/{file_path:path}'} <= routes

    web = root / 'api' / 'webui'
    html = (web / 'index.html').read_text(encoding='utf-8')
    assets = re.findall(r'''(?:src|href)=["'](/assets/[^"']+)["']''', html)
    assert assets and any(asset.endswith('.js') for asset in assets)
    assert all((web / asset.lstrip('/')).is_file() for asset in assets)
    print('Application, review export, timezone and built web assets: OK')


def check_key_storage():
    """Exercise the container OS credential path with disposable synthetic data."""
    from image_subject_settings import runtime_settings, save_settings, settings_path

    secret = 'synthetic-docker-build-credential'
    with TemporaryDirectory() as temporary:
        saved = save_settings(temporary, 'siliconflow', secret)
        assert saved['key_configured'] and saved['ready']
        assert secret not in str(saved)
        assert secret not in settings_path(temporary).read_text(encoding='utf-8')
        assert runtime_settings(temporary)['api_key'] == secret
        save_settings(temporary, 'siliconflow')
        assert runtime_settings(temporary)['api_key'] == secret
        save_settings(temporary, 'siliconflow', clear_key=True)
        assert not runtime_settings(temporary)['api_key']
    print('Container credential save, reload, redaction and clear: OK')


def check_weibo_media():
    """Catch dictionary-index URLs and truncated search previews in each image."""
    from media_downloader import MediaDownloader
    from media_platform.weibo.media import build_media_items
    from media_platform.weibo.metadata import merge_detail

    photos = [{"url": f"https://wx1.sinaimg.cn/orj360/photo-{i}.jpg"}
              for i in range(18)]
    search = {"id": "build-check", "pic_num": 18,
              "pics": {str(i): photo for i, photo in enumerate(photos[:9])}}
    search["pics"][""] = {"type": "livephoto"}
    detail = {"id": "build-check", "pic_num": 18, "pics": photos}
    preview = build_media_items(search)
    complete = build_media_items(merge_detail(search, detail))
    assert len(preview) == 9 and len(complete) == 18
    assert [item.stem for item in complete] == [f"{i:03d}" for i in range(1, 19)]
    assert all(MediaDownloader.is_supported_url(item.url) for item in complete)
    assert [item.url for item in preview] == [item.url for item in complete[:9]]
    print('Weibo dictionary images, ordered 18-photo detail completion: OK')


async def check_browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel='chromium', headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('<html><head><title>Container check</title></head><body>OK</body></html>')
            assert await page.title() == 'Container check'
        finally:
            await browser.close()
    print('Chromium launch and local page rendering: OK')


if __name__ == '__main__':
    check_application()
    check_key_storage()
    check_weibo_media()
    asyncio.run(check_browser())
