"""Small, cached review previews; collection images remain untouched."""
import hashlib
import os
from pathlib import Path
import tempfile
from threading import BoundedSemaphore

from PIL import Image, ImageOps

MAX_EDGE = 960
_generation_slots = BoundedSemaphore(2)


def source_signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def preview_path(root: Path, source: Path) -> Path:
    relative = source.resolve().relative_to(root.resolve()).as_posix()
    signature = source_signature(source)
    key = hashlib.sha256(f'webp-v1:{MAX_EDGE}:{relative}:{signature}'.encode()).hexdigest()
    target = root / '.media-previews' / (key + '.webp')
    if target.is_file() and target.stat().st_size:
        return target
    with _generation_slots:
        if target.is_file() and target.stat().st_size:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=target.parent, suffix='.tmp')
        try:
            with os.fdopen(descriptor, 'wb') as output, Image.open(source) as image:
                # JPEG decoder downsampling avoids decoding a full camera frame.
                image.draft('RGB', (MAX_EDGE, MAX_EDGE))
                scaled = ImageOps.exif_transpose(image)
                scaled.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                if scaled.mode not in {'RGB', 'RGBA'}:
                    scaled = scaled.convert('RGBA' if 'transparency' in scaled.info else 'RGB')
                options = {'icc_profile': image.info['icc_profile']} if image.info.get('icc_profile') else {}
                scaled.save(output, 'WEBP', quality=82, method=4, **options)
                output.flush()
                os.fsync(output.fileno())
            if source_signature(source) != signature:
                raise OSError('Image changed while preparing preview')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return target
