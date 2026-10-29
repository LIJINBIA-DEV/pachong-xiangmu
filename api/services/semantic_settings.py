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
    model: str | None = Field(default=None, max_length=120)


def runtime_key(root):
    with _lock:
        path = directory(root) / 'jev.json'
        if path.is_symlink():
            raise ValueError('semantic_settings_storage_failed')
        if not path.exists():
            return (os.environ.get('MEDIACRAWLER_SEMANTIC_API_KEY') or
                    os.environ.get('TYPESAFE_API_KEY') or
                    os.environ.get('OPENAI_API_KEY') or
                    os.environ.get('AI_API_KEY', '')).strip()
        saved = json.loads(path.read_text(encoding='utf-8'))
        value = saved.get('encrypted_key')
        return cipher(root).decrypt(value.encode()).decode() if value else ''


def public_settings(root):
    result = {'key_configured': bool(runtime_key(root))}
    path = directory(root) / 'jev.json'
    if path.exists():
        model = json.loads(path.read_text(encoding='utf-8')).get('model')
        if model:
            result['model'] = model
    return result


def save_settings(root, change):
    with _lock:
        from semantic_filter import SUPPORTED_MODELS
        if change.model is not None and change.model not in SUPPORTED_MODELS:
            raise ValueError('unsupported_semantic_model')
        supplied = change.api_key.get_secret_value().strip() if change.api_key else ''
        key = '' if change.clear_key else valid_key(supplied) if supplied else runtime_key(root)
        folder = directory(root, True)
        path = folder / 'jev.json'
        if path.is_symlink():
            raise ValueError('semantic_settings_storage_failed')
        encrypted = cipher(root, True).encrypt(key.encode()).decode() if key else ''
        model = change.model or public_settings(root).get('model')
        atomic_json(path, {'encrypted_key': encrypted, **({'model': model} if model else {})})
        return public_settings(root)
