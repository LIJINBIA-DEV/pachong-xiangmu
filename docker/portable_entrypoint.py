"""Supervise the isolated desktop and API; fail the container if a child exits."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

# Executing a script by filename otherwise puts /app/docker, not /app, first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    password = os.environ.pop('BROWSER_PASSWORD', '')
    if len(password) != 8 or not password.isascii() or not password.isalnum():
        raise SystemExit('BROWSER_PASSWORD must contain exactly 8 ASCII letters/digits (VNC limit).')
    secret = Path('/tmp/browser-password')
    subprocess.run(['x11vnc', '-storepasswd', password, str(secret)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    secret.chmod(0o600)
    children = []
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def start(command):
        process = subprocess.Popen(command)
        children.append(process)
        return process

    try:
        if os.environ.get('MEDIACRAWLER_BUNDLED_PROXY') == '1':
            from jev_proxy import prepare_runtime, runtime_dir
            proxy_config = prepare_runtime()
            proxy_process = start(['/usr/local/bin/mihomo', '-d', str(runtime_dir()),
                                   '-f', str(proxy_config)])
            for _ in range(100):
                if proxy_process.poll() is not None or stopping:
                    raise RuntimeError('Jev proxy service could not start')
                try:
                    with socket.create_connection(('127.0.0.1', 19090), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Jev proxy service timed out')
        start(['Xvfb', ':99', '-screen', '0', '1280x900x24', '-nolisten', 'tcp'])
        display_process = children[-1]
        for _ in range(100):
            if Path('/tmp/.X11-unix/X99').exists():
                break
            if display_process.poll() is not None or stopping:
                raise RuntimeError('Virtual display could not start')
            time.sleep(.1)
        else:
            raise RuntimeError('Virtual display timed out')
        start(['openbox', '--sm-disable'])
        start(['x11vnc', '-display', ':99', '-rfbauth', str(secret), '-rfbport', '5900',
               '-localhost', '-forever', '-shared', '-noxdamage', '-quiet'])
        start(['/usr/bin/websockify', '--web=/usr/share/novnc', '6080', '127.0.0.1:5900'])
        start([sys.executable, '-m', 'uvicorn', 'api.main:app', '--host', '0.0.0.0',
               '--port', '8080', '--workers', '1'])
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A required desktop/API process exited')
            time.sleep(.5)
    finally:
        # API is last: stop it first so active login/crawler work gets its cleanup.
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        secret.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
