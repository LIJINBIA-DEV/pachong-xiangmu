"""Use the project's existing Xiaohongshu profile for local login and collection."""
from pathlib import Path

from login_environment import web_login_browser_channel


async def launch_local_context(playwright, project_root):
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(Path(project_root) / 'browser_data' / 'xhs_user_data_dir'),
        channel=web_login_browser_channel(),
        headless=False,
        viewport={'width': 1920, 'height': 1080},
    )
