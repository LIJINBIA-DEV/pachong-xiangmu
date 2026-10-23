"""Independent Windows relay + reconnecting SSH tunnel, with explicit stop control."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = ROOT / '.local/jev-relay'
PORT = 28181
REMOTE_SOCKET = '/home/jc/mediacrawler-spark/docker/runtime/jev-relay/jev.sock'
NAME = 'Local\\MediaCrawlerJevRelay-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=12']


def token():
    from image_subject_settings import _crypt
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / 'token.dpapi'
    if not path.exists():
        encrypted = _crypt(secrets.token_urlsafe(32).encode())
        with path.open('xb') as output:
            output.write(encrypted)
    return _crypt(path.read_bytes(), decrypt=True).decode()


def setup():
    program = r'''
import json,os,pathlib,sys
root=pathlib.Path('/home/jc/mediacrawler-spark')
assert root.is_dir() and (root/'.env.spark').is_file()
payload=json.load(sys.stdin)
folder=root/'docker/runtime/jev-relay'
folder.mkdir(exist_ok=True)
folder.chmod(0o700)
path=root/'.env.spark'
existing=path.read_text()
backup=root/'deployment/env-before-jev-relay'
if not backup.exists():
    descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as stream: stream.write(existing)
lines=[line for line in existing.splitlines() if not line.startswith(('TYPESAFE_RELAY_TOKEN=','SPARK_JEV_RELAY_DIR='))]
assert '\n' not in payload['token'] and '\r' not in payload['token']
lines.extend(['TYPESAFE_RELAY_TOKEN='+payload['token'],'SPARK_JEV_RELAY_DIR=./docker/runtime/jev-relay'])
temporary=path.with_name('.env.spark.jev-tmp')
descriptor=os.open(temporary,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
with os.fdopen(descriptor,'w') as stream: stream.write('\n'.join(lines)+'\n')
os.replace(temporary,path)
print('PRIVATE_SOCKET_DIRECTORY_AND_TOKEN_CONFIGURED')
'''
    result = subprocess.run([*SSH, 'spark-xiaozhuji', 'python3 -c ' + shlex.quote(program)],
        input=json.dumps({'token': token()}), text=True, capture_output=True, timeout=45, check=True)
    print(result.stdout.strip())


def record(**values):
    from collection_tasks import atomic_json
    atomic_json(STATE / 'status.json', {'pid': os.getpid(), 'port': PORT, 'updated_at': time.time(), **values})


async def serve():
    import uvicorn
    from scripts.jev_relay import create_app
    from scripts.project_session import ProcessJob, windows_api
    import ctypes
    kernel = windows_api()
    ctypes.set_last_error(0)
    mutex = kernel.CreateMutexW(None, True, NAME)
    if not mutex:
        raise OSError('Could not create relay instance lock')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        print('Jev relay already running; no second process started.')
        return
    event = kernel.CreateEventW(None, True, False, NAME + '-Stop')
    if not event:
        kernel.CloseHandle(mutex)
        raise OSError('Could not create relay stop event')
    server = uvicorn.Server(uvicorn.Config(create_app(token()), host='127.0.0.1', port=PORT,
        access_log=False, log_level='warning'))

    async def tunnel():
        while not server.should_exit:
            job = ProcessJob()
            process = None
            try:
                command = [*SSH, '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
                    '-o', 'ServerAliveCountMax=3', '-o', 'StreamLocalBindUnlink=yes',
                    '-o', 'StreamLocalBindMask=0177', '-N', '-T', '-R',
                    REMOTE_SOCKET + ':127.0.0.1:' + str(PORT), 'spark-xiaozhuji']
                with (STATE / 'ssh.log').open('ab', buffering=0) as output:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                        stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
                job.assign(int(process._handle))
                record(tunnel='process_running', ssh_pid=process.pid)
                while process.poll() is None and not server.should_exit:
                    await asyncio.sleep(0.5)
            except Exception as exc:
                record(tunnel='reconnecting', error=type(exc).__name__)
            finally:
                job.close()  # Only this session's SSH child belongs to this job.
                if process:
                    process.wait(timeout=10)
            if not server.should_exit:
                record(tunnel='reconnecting')
                await asyncio.sleep(3)

    async def stop_monitor():
        while not server.should_exit:
            if kernel.WaitForSingleObject(event, 0) == 0:
                server.should_exit = True
                break
            await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(tunnel()), asyncio.create_task(stop_monitor())]
    try:
        print('Jev relay: 127.0.0.1:' + str(PORT) + '; SSH reconnect enabled. Keep this computer awake.', flush=True)
        await server.serve()
    finally:
        server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
        record(tunnel='stopped')
        kernel.CloseHandle(event)
        kernel.CloseHandle(mutex)


def stop():
    from scripts.project_session import windows_api
    kernel = windows_api()
    event = kernel.OpenEventW(0x0002, False, NAME + '-Stop')
    if not event:
        print('Jev relay is not running.')
        return
    try:
        if not kernel.SetEvent(event):
            raise OSError('Could not signal relay stop')
        print('Stop requested for Jev relay only.')
    finally:
        kernel.CloseHandle(event)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('setup', 'start', 'stop', 'status'))
    action = parser.parse_args().action
    if action == 'setup':
        setup()
    elif action == 'stop':
        stop()
    elif action == 'status':
        print((STATE / 'status.json').read_text() if (STATE / 'status.json').exists() else 'Not started')
    else:
        asyncio.run(serve())
