"""Provider-neutral summary settings; credentials never leave the backend API."""
import ipaddress
import json
import os
from pathlib import Path
import stat
import tempfile
from threading import RLock
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, SecretStr, field_validator
from typing import Literal
from collection_tasks import atomic_json

DEFAULT_BASE = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'
_lock = RLock()


def endpoint(value):
    try:
        value = value.strip()
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError()
        url = urlsplit(value)
        address = None
        try:
            address = ipaddress.ip_address(url.hostname or '')
        except ValueError:
            pass
        if not url.hostname or url.username or url.password or url.query or url.fragment or url.port == 0:
            raise ValueError()
        if address and (address.is_link_local or address.is_multicast or address.is_unspecified):
            raise ValueError()
        if url.scheme != 'https' and not (url.scheme == 'http' and (url.hostname == 'localhost' or address and address.is_loopback)):
            raise ValueError()
        path = url.path.rstrip('/')
        if not path.endswith('/chat/completions'):
            path += '/chat/completions'
        return urlunsplit((url.scheme, url.netloc, path, '', ''))
    except (ValueError, TypeError):
        raise ValueError('summary_invalid_endpoint') from None


def valid_key(key):
    if len(key) > 512 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('summary_invalid_key')
    return key


class AISettingsUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    scope: Literal['retained', 'available'] = 'retained'
    include_comments: bool = False
    max_posts: int = Field(default=100, ge=1, le=500)
    api_key: SecretStr | None = Field(default=None, max_length=512)
    clear_key: bool = False

    @field_validator('base_url')
    @classmethod
    def validate_endpoint(cls, value):
        endpoint(value)
        return value.strip().rstrip('/')


def directory(root, create=False):
    path = Path(root) / '.ai-settings'
    if path.is_symlink():
        raise ValueError('summary_settings_storage_failed')
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
    return path


def read(root):
    path = directory(root) / 'settings.json'
    if path.is_symlink():
        raise ValueError('summary_settings_storage_failed')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def cipher(root, create=False):
    folder = directory(root, create)
    path = folder / 'credential.key'
    if create and not path.exists():
        fd, temporary = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(Fernet.generate_key()); file.flush(); os.fsync(file.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('summary_settings_storage_failed')
        return Fernet(os.read(fd, 128))
    finally:
        os.close(fd)


def runtime_settings(root):
    with _lock:
        saved = read(root)
        if saved is not None:
            settings = AISettingsUpdate(**saved).model_dump(exclude={'api_key', 'clear_key'})
            key = cipher(root).decrypt(saved['encrypted_key'].encode()).decode() if saved.get('encrypted_key') else ''
            # Saving an empty credential is intentional; never revive an unrelated environment key.
            return {**settings, 'api_key': key, 'key_from_environment': False}
        legacy = bool(os.environ.get('DEEPSEEK_API_KEY', '').strip())
        return {'base_url': os.environ.get('AI_BASE_URL', DEFAULT_BASE if legacy else '').strip(),
                'model': os.environ.get('AI_MODEL', DEFAULT_MODEL if legacy else '').strip(),
                'scope': 'retained', 'max_posts': 100, 'include_comments': False,
                'api_key': os.environ.get('AI_API_KEY', os.environ.get('DEEPSEEK_API_KEY', '') if not os.environ.get('AI_BASE_URL') else '').strip(),
                'key_from_environment': bool(os.environ.get('AI_API_KEY') or legacy and not os.environ.get('AI_BASE_URL'))}


def public_settings(root):
    settings = runtime_settings(root)
    key = settings.pop('api_key')
    return {**settings, 'key_configured': bool(key), 'ready': bool(key and settings['base_url'] and settings['model'])}


def save_settings(root, change):
    with _lock:
        old = runtime_settings(root)
        values = change.model_dump(exclude={'api_key', 'clear_key'})
        # Bind retained credentials to their exact endpoint, so changing providers cannot forward an old key.
        same = bool(old['base_url']) and endpoint(old['base_url']) == endpoint(change.base_url)
        key = '' if change.clear_key or not same else old['api_key']
        supplied = change.api_key.get_secret_value().strip() if change.api_key else ''
        if supplied:
            key = valid_key(supplied)
        folder = directory(root, True)
        values['encrypted_key'] = cipher(root, True).encrypt(key.encode()).decode() if key else ''
        atomic_json(folder / 'settings.json', values)
        return public_settings(root)
