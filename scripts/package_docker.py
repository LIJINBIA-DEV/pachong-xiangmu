"""Sanitized, allowlisted Docker source delivery. Never copy runtime directories."""
import argparse
from pathlib import Path
import re
import zipfile

from package_windows import sources, public_content, ROOT

DOCKER_FILES = ('Dockerfile.portable', 'portable_entrypoint.py', 'portable_health.py',
                'install_mihomo.py', 'check_runtime.py', 'start-portable.ps1', 'PORTABLE.md',
                'IMAGE-ONLY.md')


def build(output):
    files = {p for p in sources(ROOT) if p.suffix != '.cmd'
             and p.name != '使用说明-一键启动.txt' and p.parent.name != 'scripts'}
    # Explicitly keep only app runtime helpers, not old machine deployment scripts.
    files.update(ROOT / 'scripts' / name for name in ('project_session.py', 'check_backend_version.py'))
    files.update(ROOT / 'docker' / name for name in DOCKER_FILES)
    files.update(ROOT / name for name in ('compose.portable.yaml', '.env.portable.example',
                                         '.dockerignore', '启动Docker.cmd', '启动Docker.sh', 'Docker使用说明.txt'))
    report = ROOT / 'docker' / 'PORTABLE-VALIDATION.md'
    if report.exists():
        files.add(report)
    payload = []
    for path in sorted(files):
        content = public_content(path, ROOT)
        if re.search(rb'\bapikey_[0-9a-f]{20,}', content):
            raise ValueError(f'Credential-like content in {path.relative_to(ROOT)}')
        payload.append((path.relative_to(ROOT).as_posix(), content))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload:
            archive.writestr('MediaCrawler/' + name, content)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    print(f'Created {output}: {len(payload)} files')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
