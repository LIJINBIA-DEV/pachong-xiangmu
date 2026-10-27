"""Write-only, encrypted Jev credential shared by collection and connection checks."""
import json
import os
from threading import RLock

from pydantic import BaseModel, Field, SecretStr

from collection_tasks import atomic_json
from api.services.ai_settings import cipher, directory, valid_key

_lock = RLock()


class SemanticSettingsUpdate(BaseModel):
    api_key: SecretStr | None = Field(default=None, max_length=512)
    clear_key: bool = False


def runtime_key(root):
    with _lock:
        path = directory(root) / 'jev.json'
        if path.is_symlink():
            raise ValueError('semantic_settings_storage_failed')
        if not path.exists():
            return os.environ.get('TYPESAFE_API_KEY', '').strip()
        saved = json.loads(path.read_text(encoding='utf-8'))
        value = saved.get('encrypted_key')
        return cipher(root).decrypt(value.encode()).decode() if value else ''


def public_settings(root):
    return {'key_configured': bool(runtime_key(root))}


def save_settings(root, change):
    with _lock:
        supplied = change.api_key.get_secret_value().strip() if change.api_key else ''
        key = '' if change.clear_key else valid_key(supplied) if supplied else runtime_key(root)
        folder = directory(root, True)
        path = folder / 'jev.json'
        if path.is_symlink():
            raise ValueError('semantic_settings_storage_failed')
        encrypted = cipher(root, True).encrypt(key.encode()).decode() if key else ''
        atomic_json(path, {'encrypted_key': encrypted})
        return public_settings(root)
