"""Exercise real Windows job cleanup without touching the running project."""
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.request import urlopen

import pytest

from scripts.project_session import (ProcessJob, ROOT, adopt_tree, descendant_ids,
                                     inventory, service_roots, windows_api)

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows console lifecycle')


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError('Lifecycle condition timed out')


def alive(pid):
    kernel = windows_api()
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def connectable(port):
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def test_refuses_other_project_before_adoption(tmp_path):
    snapshot = {'listeners': [{'LocalPort': 18080, 'OwningProcess': 1}],
                'processes': [{'ProcessId': 1, 'ParentProcessId': 0,
                               'CommandLine': 'python -m uvicorn api.main:app'}]}
    with patch('scripts.project_session.read_json', return_value={'project_root': str(tmp_path / 'other')}):
        with pytest.raises(RuntimeError, match='无法确认'):
            service_roots(tmp_path, snapshot, 18080, 5173)


def test_refuses_other_vite_directory(tmp_path):
    snapshot = {'listeners': [{'LocalPort': 5173, 'OwningProcess': 1}],
                'processes': [{'ProcessId': 1, 'ParentProcessId': 0,
                               'CommandLine': 'node vite.js', 'ExecutablePath': r'C:\node.exe'}]}
    with patch('scripts.project_session.read_text', return_value='fileName: "C:/another/webui/src/App.tsx"'):
        with pytest.raises(RuntimeError, match='无法确认'):
            service_roots(tmp_path, snapshot, 18080, 5173)


def test_descendants_do_not_include_other_processes():
    snapshot = {'processes': [{'ProcessId': 1, 'ParentProcessId': 0},
                              {'ProcessId': 2, 'ParentProcessId': 1},
                              {'ProcessId': 3, 'ParentProcessId': 2},
                              {'ProcessId': 4, 'ParentProcessId': 0}]}
    assert descendant_ids(snapshot, 1) == {1, 2, 3}


def child_worker(tmp_path):
    report = tmp_path / 'tree.json'
    child = tmp_path / 'child.py'
    child.write_text(
        'import socket,time,json,os,sys\n'
        's=socket.socket();s.bind(("127.0.0.1",0));s.listen()\n'
        'open(sys.argv[1],"w").write(json.dumps({"child":os.getpid(),"port":s.getsockname()[1]}))\n'
        'time.sleep(300)\n', encoding='utf-8')
    parent = tmp_path / 'parent.py'
    parent.write_text(
        'import subprocess,sys,time\n'
        f'subprocess.Popen([sys.executable,{str(child)!r},{str(report)!r}])\n'
        'time.sleep(300)\n', encoding='utf-8')
    return parent, report


def read_report(report):
    wait_for(lambda: report.exists() and report.stat().st_size > 0)
    value = json.loads(report.read_text())
    wait_for(lambda: connectable(value['port']))
    return value


def test_close_job_stops_new_child_tree_and_releases_port(tmp_path):
    parent, report = child_worker(tmp_path)
    job = ProcessJob()
    try:
        pid = job.spawn([sys.executable, parent], tmp_path, tmp_path / 'log.txt')
        value = read_report(report)
        assert alive(pid) and alive(value['child'])
        job.close()
        wait_for(lambda: not alive(pid) and not alive(value['child']) and not connectable(value['port']))
    finally:
        job.close()


def test_forced_owner_exit_cleans_tree_without_python_finally(tmp_path):
    parent, report = child_worker(tmp_path)
    owner_file = tmp_path / 'owner.py'
    owner_file.write_text(
        'import sys,time\n'
        f'sys.path.insert(0,{str(ROOT)!r})\n'
        'from scripts.project_session import ProcessJob\n'
        'job=ProcessJob()\n'
        f'job.spawn([sys.executable,{str(parent)!r}],{str(tmp_path)!r},{str(tmp_path / "log.txt")!r})\n'
        'time.sleep(300)\n', encoding='utf-8')
    owner = subprocess.Popen([sys.executable, owner_file], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        value = read_report(report)
        owner.kill()  # No graceful shutdown/finally: equivalent handle loss on console close.
        owner.wait(timeout=5)
        wait_for(lambda: not alive(value['child']) and not connectable(value['port']))
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_adopts_existing_tree_and_leaves_unrelated_process_alone(tmp_path):
    parent, report = child_worker(tmp_path)
    original = subprocess.Popen([sys.executable, parent], creationflags=subprocess.CREATE_NO_WINDOW)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], creationflags=subprocess.CREATE_NO_WINDOW)
    job = ProcessJob()
    try:
        value = read_report(report)
        adopt_tree(job, inventory([]), original.pid)
        job.close()
        wait_for(lambda: not alive(original.pid) and not alive(value['child']) and not connectable(value['port']))
        assert unrelated.poll() is None
    finally:
        job.close()
        for process in (original, unrelated):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_real_services_restart_and_close_on_isolated_ports(tmp_path):
    from scripts.project_session import owner

    def free_port():
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]

    api, web = free_port(), free_port()
    while api == web:
        web = free_port()
    log = tmp_path / 'supervisor.log'
    args = [str(ROOT / '.venv/Scripts/python.exe'), '-u', str(ROOT / 'scripts/project_session.py'),
            '--no-open', '--api-port', str(api), '--web-port', str(web)]
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    with log.open('wb') as output:
        supervisor = subprocess.Popen(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                      env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            def message_present(message):
                text = log.read_text(encoding='utf-8')
                if supervisor.poll() is not None:
                    raise AssertionError(text)
                return message in text
            wait_for(lambda: message_present('本窗口管理前端'), timeout=60)
            with urlopen(f'http://127.0.0.1:{api}/api/health') as response:
                assert json.load(response)['status'] == 'ok'
            with urlopen(f'http://127.0.0.1:{web}/') as response:
                assert response.status == 200
            first_api = owner(inventory([api]), api)
            duplicate = subprocess.run(args, cwd=ROOT, capture_output=True, env=environment, timeout=15)
            assert duplicate.returncode == 1
            request = subprocess.run(args + ['--restart-backend'], cwd=ROOT, capture_output=True, env=environment, timeout=15)
            assert request.returncode == 0
            wait_for(lambda: message_present('后端已重启，仍由本 CMD 管理。'), timeout=45)
            assert owner(inventory([api]), api) != first_api
            supervisor.kill()
            supervisor.wait(timeout=5)
            wait_for(lambda: not connectable(api) and not connectable(web))
            snapshot = inventory([api, web])
            assert owner(snapshot, api) is None and owner(snapshot, web) is None
        finally:
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.wait(timeout=5)
