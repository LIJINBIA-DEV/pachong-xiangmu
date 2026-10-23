"""Exit 0 for current, 2 for stale, 1 for unavailable; never restart a process."""
import argparse
import json
from pathlib import Path
import sys
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from api.services.backend_version import source_revision


def check_backend(url, root, timeout=3):
    try:
        with urlopen(url.rstrip('/') + '/api/health', timeout=timeout) as response:
            health = json.load(response)
        if health.get('status') != 'ok':
            return 1
        if health.get('source_revision') != source_revision(root):
            return 2
        if Path(health.get('project_root', '')).resolve() != Path(root).resolve():
            return 1
        return 0
    except (OSError, ValueError, TypeError):
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    args = parser.parse_args()
    sys.exit(check_backend(args.url, REPO))
