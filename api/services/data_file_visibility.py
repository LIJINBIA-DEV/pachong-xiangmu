"""Distinguish collection exports from private state and resumable checkpoints."""
import os
from pathlib import Path

from api.services.data_browser import DATA_TYPES


def internal_record(relative: Path) -> bool:
    return any(part.startswith('.') for part in relative.parts) or relative.name.lower().startswith('semantic_checkpoint_')


def collection_files(root: Path):
    root = root.resolve()
    for directory, dirs, filenames in os.walk(root):
        dirs[:] = [name for name in dirs if not name.startswith('.') and name not in {'media', '__pycache__'}]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in DATA_TYPES:
                continue
            try:
                relative = path.resolve().relative_to(root)
            except ValueError:
                continue
            if not internal_record(relative) and 'media' not in relative.parts:
                yield path
