"""Backend-only image provider settings. Never return a stored API credential."""
import base64
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import stat
import tempfile

from cryptography.fernet import Fernet, InvalidToken

from collection_tasks import atomic_json

CLOUD_MODEL = 'Qwen/Qwen3.5-4B'
CLOUD_URL = 'https://api.siliconflow.cn/v1/chat/completions'


def settings_path(root):
    return Path(root) / '.image-subject/settings.json'


def _private_directory(root):
    directory = settings_path(root).parent
    if directory.is_symlink():
        raise ValueError('image_subject_key_storage_failed')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _read_posix_key(path):
    # Never follow a substituted key-file symlink or accept partial/invalid keys.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('image_subject_key_storage_failed')
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'rb', closefd=False) as file:
            value = file.read(128)
        return Fernet(value)
    finally:
        os.close(descriptor)


def _posix_cipher(root, create=False):
    directory = _private_directory(root)
    path = directory / 'credential.key'
    try:
        return _read_posix_key(path)
    except FileNotFoundError:
        if not create:
            raise
    # Publish a complete file without replacing another process's key. Using
    # O_EXCL directly on the final path could expose an empty file to a reader.
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'wb') as file:
            file.write(Fernet.generate_key())
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return _read_posix_key(path)
    finally:
        os.unlink(temporary)


def _decrypt_posix(root, encrypted):
    return _posix_cipher(root).decrypt(encrypted.encode('ascii')).decode('utf-8')


@contextmanager
def _settings_write_lock(root):
    if os.name != 'posix':
        yield
        return
    import fcntl
    descriptor = os.open(
        _private_directory(root) / '.credential.lock',
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('image_subject_key_storage_failed')
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _crypt(value, decrypt=False):
    # DPAPI binds credentials to the current Windows login, not the repository.
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, target = Blob(len(value), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('image_subject_key_storage_failed')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def _read(root):
    try:
        value = json.loads(settings_path(root).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def runtime_settings(root):
    stored = _read(root)
    provider = os.environ.get('MEDIACRAWLER_IMAGE_PROVIDER') or stored.get('provider', 'local')
    if provider not in {'local', 'siliconflow'}:
        raise ValueError('image_subject_provider_invalid')
    key = os.environ.get('SILICONFLOW_API_KEY', '').strip()
    if not key and stored.get('encrypted_key') and os.name == 'nt':
        try:
            key = _crypt(base64.b64decode(stored['encrypted_key']), decrypt=True).decode()
        except (ValueError, OSError, UnicodeError):
            key = ''
    if not key and stored.get('encrypted_key_fernet') and os.name == 'posix':
        try:
            key = _decrypt_posix(root, stored['encrypted_key_fernet'])
        except (ValueError, OSError, UnicodeError, InvalidToken, AttributeError, TypeError):
            key = ''
    return {'provider': provider, 'api_key': key, 'model': CLOUD_MODEL if provider == 'siliconflow' else 'Qwen3.5-4B Q4_K_M'}


def public_settings(root):
    from image_subject import model_ready
    options = runtime_settings(root)
    configured = bool(options['api_key'])
    return {'provider': options['provider'], 'model': options['model'], 'key_configured': configured,
            'key_from_environment': bool(os.environ.get('SILICONFLOW_API_KEY')),
            'local_ready': model_ready(), 'ready': configured if options['provider'] == 'siliconflow' else model_ready()}


def save_settings(root, provider, api_key=None, clear_key=False):
    if provider not in {'local', 'siliconflow'}:
        raise ValueError('image_subject_provider_invalid')
    key = api_key.strip() if api_key is not None else ''
    if len(key) > 512 or any(c.isspace() for c in key):
        raise ValueError('image_subject_key_invalid')
    try:
        with _settings_write_lock(root):
            return _save_settings(root, provider, key, clear_key)
    except (ValueError, OSError, UnicodeError, InvalidToken, AttributeError, TypeError):
        raise ValueError('image_subject_key_storage_failed') from None


def _save_settings(root, provider, key, clear_key):
    stored = _read(root)
    stored['provider'] = provider
    if clear_key:
        stored.pop('encrypted_key', None)
        stored.pop('encrypted_key_fernet', None)
    if key:
        if os.name == 'nt':
            stored['encrypted_key'] = base64.b64encode(_crypt(key.encode())).decode()
            stored.pop('encrypted_key_fernet', None)
        elif os.name == 'posix':
            if stored.get('encrypted_key_fernet'):
                # A missing/wrong master key must not silently destroy an
                # existing credential. Explicit clear permits starting over.
                _decrypt_posix(root, stored['encrypted_key_fernet'])
            stored['encrypted_key_fernet'] = _posix_cipher(root, create=True).encrypt(key.encode()).decode('ascii')
            stored.pop('encrypted_key', None)
        else:
            raise ValueError('image_subject_key_storage_failed')
    atomic_json(settings_path(root), stored)
    if clear_key and not key and os.name == 'posix':
        # Delete only after the clear was committed, under the same writer
        # lock. This also lets a deliberately cleared, damaged store recover.
        (settings_path(root).parent / 'credential.key').unlink(missing_ok=True)
    return public_settings(root)
