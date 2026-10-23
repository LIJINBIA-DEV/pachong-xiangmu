"""Download only the verified visual projector; no production model changes."""
import hashlib
from pathlib import Path
import time
import httpx

out = Path(__file__).resolve().parents[1] / 'artifacts/model-compare-20261013'
out.mkdir(parents=True, exist_ok=True)
dest = out / 'mmproj-F16.gguf'
expected = 'eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45'
url = 'https://huggingface.co/unsloth/Qwen3.6-27B-GGUF/resolve/main/mmproj-F16.gguf'
if not dest.exists():
    tmp = dest.with_suffix('.part')
    total, last = 0, time.monotonic()
    with httpx.stream('GET', url, follow_redirects=True, timeout=90) as response:
        response.raise_for_status()
        with tmp.open('wb') as stream:
            for chunk in response.iter_bytes(1024 * 1024):
                stream.write(chunk)
                total += len(chunk)
                if time.monotonic() - last > 10:
                    print('downloaded_mb=' + str(total // 1000000), flush=True)
                    last = time.monotonic()
    assert tmp.stat().st_size == 927607360
    assert hashlib.file_digest(tmp.open('rb'), 'sha256').hexdigest() == expected
    tmp.replace(dest)
assert hashlib.file_digest(dest.open('rb'), 'sha256').hexdigest() == expected
print('projector_verified=True', flush=True)
