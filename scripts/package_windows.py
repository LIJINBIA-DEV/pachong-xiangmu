"""Build a source-only Windows handoff ZIP from an explicit allowlist."""
import argparse
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ('api', 'base', 'cache', 'cmd_arg', 'config', 'constant', 'database',
             'libs', 'media_downloader', 'media_platform', 'model', 'proxy',
             'resources', 'store', 'tools')
CODE_SUFFIXES = {'.py', '.js', '.json', '.txt', '.md', '.sql'}
SCRIPTS = ('bootstrap_windows.ps1', 'check_desktop_environment.py',
           'install_desktop_browser.py', 'project_session.py', 'check_backend_version.py')
TOP_FILES = ('pyproject.toml', 'uv.lock', '.python-version', 'LICENSE',
             'README.md', '一键启动.cmd', '使用说明-一键启动.txt')
WEB_FILES = ('index.html', 'package.json', 'package-lock.json', 'postcss.config.js',
             'tailwind.config.ts', 'tsconfig.json', 'vite.config.ts', 'LICENSE')
FORBIDDEN_PARTS = {'__pycache__', 'node_modules', 'test', 'tests', 'test_data',
                   'data', 'browser_data', '.git', '.local', '.runtime', '.venv',
                   'models', 'artifacts', 'webui'}


def sources(root):
    files = set(root.glob('*.py'))
    files.update(root / name for name in TOP_FILES)
    files.update(root / 'scripts' / name for name in SCRIPTS)
    for folder in CODE_DIRS:
        for path in (root / folder).rglob('*'):
            rel = path.relative_to(root)
            if not path.is_file() or path.is_symlink() or set(rel.parts) & FORBIDDEN_PARTS:
                continue
            if path.suffix in CODE_SUFFIXES or path.name == 'LICENSE':
                files.add(path)
    files.update(root / 'webui' / name for name in WEB_FILES)
    for folder in ('src', 'public'):
        files.update(p for p in (root / 'webui' / folder).rglob('*') if p.is_file() and not p.is_symlink())
    return sorted(files)


def public_content(path, root):
    data = path.read_bytes()
    # Runtime configuration is deliberately blank in the recipient's copy.
    if path == root / 'config/base_config.py':
        text = data.decode('utf-8-sig')
        for field in ('COOKIES', 'STATIC_PROXY_URL', 'CUSTOM_BROWSER_PATH'):
            text = re.sub(rf'(?m)^{field}\s*=.*$', f'{field} = ""', text)
        data = text.encode('utf-8')
    # Refuse typical embedded credentials; errors name files, never values.
    if re.search(rb'\bsk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----', data):
        raise ValueError(f'Possible credential in {path.relative_to(root)}; package not created.')
    return data


def build_package(root, output):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite: {output}')
    # Validate all sources before creating the archive.
    payload = [(p.relative_to(root).as_posix(), public_content(p, root)) for p in sources(root)]
    # Old launcher name remains usable in the distributed folder as an alias.
    payload.append(('启动项目.cmd', b'@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + '一键启动.cmd'.encode('utf-8') + b'" %*\r\n'))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, content in payload:
            z.writestr('MediaCrawler/' + name, content)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
    return len(payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    count = build_package(ROOT, args.output)
    print(f'Created {args.output.resolve()}: {count} files, {args.output.stat().st_size / 1024**2:.2f} MiB')
