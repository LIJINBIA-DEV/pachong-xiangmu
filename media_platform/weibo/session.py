"""Private browser login state shared by the web login and crawler processes."""
import json
import os
from pathlib import Path
import secrets
import time


def session_path(project_root):
    return Path(project_root) / 'browser_data' / '.weibo-login.json'


def read_session(project_root):
    try:
        state = json.loads(session_path(project_root).read_text(encoding='utf-8'))
        cookies = [cookie for cookie in state['cookies'] if isinstance(cookie, dict)
            and (str(cookie.get('domain', '')).lstrip('.') in {'weibo.cn', 'weibo.com'}
                 or str(cookie.get('domain', '')).endswith(('.weibo.cn', '.weibo.com')))
            and isinstance(cookie.get('expires', -1), (int, float))
            and (cookie.get('expires', -1) == -1 or cookie['expires'] > time.time())]
        return {**state, 'cookies': cookies} if cookies else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(project_root, state):
    path = session_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(state, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def restore_session(context, project_root):
    state = read_session(project_root)
    if not state:
        return False
    await context.add_cookies(state['cookies'])
    return True
