"""Console-owned Windows service trees; closing the console closes both jobs."""
import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_backend_version import check_backend


class BasicLimit(ctypes.Structure):
    _fields_ = [('per_process', ctypes.c_int64), ('per_job', ctypes.c_int64),
                ('flags', W.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                ('active', W.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', W.DWORD), ('scheduling', W.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [('basic', BasicLimit), ('io', IoCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


def windows_api():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    declarations = {
        'CreateJobObjectW': ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
        'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
        'IsProcessInJob': ([W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)], W.BOOL),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'GetExitCodeProcess': ([W.HANDLE, ctypes.POINTER(W.DWORD)], W.BOOL),
        'GetProcessTimes': ([W.HANDLE, ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME)], W.BOOL),
        'ResumeThread': ([W.HANDLE], W.DWORD),
        'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
        'CreateMutexW': ([ctypes.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
        'CreateEventW': ([ctypes.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR], W.HANDLE),
        'OpenEventW': ([W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE),
        'SetEvent': ([W.HANDLE], W.BOOL),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class ProcessJob:
    def __init__(self):
        self.kernel = windows_api()
        self.handle = checked(self.kernel.CreateJobObjectW(None, None))
        self.process_handles = []
        self.adopted_jobs = []
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            checked(self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    def assign(self, handle):
        present = W.BOOL()
        checked(self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(present)))
        if not present:
            checked(self.kernel.AssignProcessToJobObject(self.handle, handle))

    def adopt(self, pid, creation_date=None):
        handle = checked(self.kernel.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid))
        try:
            if creation_date is not None:
                expected = re.fullmatch(r'/Date\((\d+)\)/', creation_date)
                if not expected:
                    raise RuntimeError('无法核实进程创建时间，未接管。')
                created, exited, kernel_time, user_time = (W.FILETIME() for _ in range(4))
                checked(self.kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                                    ctypes.byref(kernel_time), ctypes.byref(user_time)))
                milliseconds = ((created.dwHighDateTime << 32) + created.dwLowDateTime) // 10000 - 11644473600000
                if milliseconds != int(expected.group(1)):
                    raise RuntimeError('进程已发生变化，未接管，请重试。')
            self.assign(handle)
        finally:
            self.kernel.CloseHandle(handle)

    def spawn(self, arguments, cwd, log):
        import _winapi
        import msvcrt
        # Suspend until assigned: children cannot escape the job at startup.
        with open(log, 'ab', buffering=0) as output, open(os.devnull, 'rb') as input_file:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESTDHANDLES
            startup.hStdOutput = startup.hStdError = msvcrt.get_osfhandle(output.fileno())
            startup.hStdInput = msvcrt.get_osfhandle(input_file.fileno())
            for handle in (startup.hStdOutput, startup.hStdInput):
                os.set_handle_inheritable(handle, True)
            hp, ht, pid, _ = _winapi.CreateProcess(
                None, subprocess.list2cmdline([str(arg) for arg in arguments]), None, None, True,
                0x4 | subprocess.CREATE_NO_WINDOW,
                {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'}, str(cwd), startup)
        try:
            self.assign(hp)
            if self.kernel.ResumeThread(ht) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            self.process_handles.append(hp)
            return pid
        except BaseException:
            self.kernel.TerminateProcess(hp, 1)
            self.kernel.CloseHandle(hp)
            raise
        finally:
            self.kernel.CloseHandle(ht)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        for handle in self.process_handles:
            self.kernel.CloseHandle(handle)
        self.process_handles.clear()
        for job in self.adopted_jobs:
            job.close()
        self.adopted_jobs.clear()


def inventory(ports):
    numbers = ','.join(str(port) for port in ports)
    code = ("[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); "
            "$ErrorActionPreference='Stop'; $procs=@(Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate); "
            f"$listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {{$_.LocalPort -in @({numbers})}} | "
            "Select-Object LocalPort,OwningProcess); "
            "@{processes=$procs; listeners=$listeners} | ConvertTo-Json -Depth 4 -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', code], capture_output=True,
                            encoding='utf-8', check=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(result.stdout)


def read_text(url):
    with urlopen(url, timeout=5) as response:
        return response.read().decode('utf-8')


def read_json(url):
    return json.loads(read_text(url))


def owner(snapshot, port):
    pids = {row['OwningProcess'] for row in snapshot['listeners'] if row['LocalPort'] == port}
    if len(pids) > 1:
        raise RuntimeError(f'端口 {port} 被多个进程占用，未接管。')
    return next(iter(pids), None)


def service_roots(root, snapshot, api_port, web_port):
    """Verify both port owners before adopting anything; reject other projects."""
    processes = {row['ProcessId']: row for row in snapshot['processes']}
    api_pid, web_pid = owner(snapshot, api_port), owner(snapshot, web_port)
    if api_pid:
        if not re.search(r'\buvicorn\s+api\.main:app\b', processes[api_pid].get('CommandLine') or '', re.I):
            raise RuntimeError(f'端口 {api_port} 不是本项目后端，未接管。')
        health = read_json(f'http://127.0.0.1:{api_port}/api/health')
        if Path(health.get('project_root', '')).resolve() != root.resolve():
            raise RuntimeError('无法确认现有后端属于本项目，请先关闭旧后端窗口。')
        parent = processes.get(processes[api_pid]['ParentProcessId'])
        if parent and (parent.get('ExecutablePath') or '').lower() == str(root / '.venv/Scripts/python.exe').lower():
            if re.search(r'\buvicorn\s+api\.main:app\b', parent.get('CommandLine') or '', re.I):
                api_pid = parent['ProcessId']
    if web_pid:
        process = processes[web_pid]
        if 'vite' not in (process.get('CommandLine') or '').lower() or Path(process.get('ExecutablePath') or '').name.lower() != 'node.exe':
            raise RuntimeError(f'端口 {web_port} 不是本项目 Vite，未接管。')
        body = read_text(f'http://127.0.0.1:{web_port}/src/App.tsx')
        expected = (root / 'webui/src/App.tsx').resolve().as_posix().lower()
        file_names = re.findall(r'fileName:\s*"([^"]+)"', body)
        if expected not in [name.replace('\\', '/').lower() for name in file_names]:
            raise RuntimeError('无法确认现有前端属于本项目，未接管。')
    return api_pid, web_pid


def descendant_ids(snapshot, root_pid):
    found = {root_pid}
    while True:
        expanded = found | {row['ProcessId'] for row in snapshot['processes'] if row['ParentProcessId'] in found}
        if expanded == found:
            return found
        found = expanded


def adopt_tree(job, snapshot, pid):
    # New children inherit after root assignment; also collect existing children.
    before = {row['ProcessId']: row for row in snapshot['processes']}
    job.adopt(pid, before[pid]['CreationDate'])
    now = {row['ProcessId']: row for row in inventory([])['processes']}
    for child in descendant_ids(snapshot, pid) - {pid}:
        if child in now and before[child]['CreationDate'] == now[child]['CreationDate']:
            try:
                # Python's venv redirector may already own a nested Windows
                # job. Give each existing child an empty job rather than
                # attempting to merge incompatible populated job hierarchies.
                child_job = ProcessJob()
                try:
                    child_job.adopt(child, before[child]['CreationDate'])
                except BaseException:
                    child_job.close()
                    raise
                job.adopted_jobs.append(child_job)
            except OSError as exc:
                if exc.winerror not in (87, 1168):
                    raise


def ensure_idle(api_port):
    from urllib.parse import quote
    base = f'http://127.0.0.1:{api_port}'
    if read_json(base + '/api/crawler/status')['status'] not in ('idle', 'error'):
        raise RuntimeError('正在采集，请先在控制台停止采集，再重启后端。')
    files = read_json(base + '/api/data/files')['files']
    review = next((file for file in files if file['path'].startswith('weibo/') and
                   not re.search('comment|creator|guard_replay|semantic_checkpoint', file['name'])), None)
    if review and read_json(base + '/api/data/image-subject?file=' + quote(review['path']))['busy']:
        raise RuntimeError('正在识别图片，请等待完成后再重启后端。')


def wait_ready(url, check, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check(read_text(url)):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f'服务启动超时：{url}，请查看日志目录。')


def run(args):
    if os.name != 'nt':
        raise RuntimeError('此启动方式只支持 Windows。')
    kernel = windows_api()
    name = 'Local\\MediaCrawler-' + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
    mutex = checked(kernel.CreateMutexW(None, False, name))
    duplicate = ctypes.get_last_error() == 183
    event = api_job = web_job = None
    try:
        if duplicate:
            if args.restart_backend:
                event = checked(kernel.OpenEventW(2, False, name + '-restart'))
                checked(kernel.SetEvent(event))
                print('已向原启动窗口发送重启请求；项目仍由原窗口管理。', flush=True)
                return 0
            raise RuntimeError('项目已由另一个 CMD 管理，请保留原窗口；关闭原窗口后再启动。')
        event = checked(kernel.CreateEventW(None, False, False, name + '-restart'))
        python, vite = ROOT / '.venv/Scripts/python.exe', ROOT / 'webui/node_modules/vite/bin/vite.js'
        node = shutil.which('node.exe')
        if not python.is_file() or not vite.is_file() or not node:
            raise RuntimeError('缺少项目 Python、Node.js 或前端依赖。')
        snapshot = inventory([args.api_port, args.web_port])
        api_pid, web_pid = service_roots(ROOT, snapshot, args.api_port, args.web_port)
        if api_pid and args.restart_backend:
            ensure_idle(args.api_port)
        if api_pid and not args.restart_backend and check_backend(f'http://127.0.0.1:{args.api_port}', ROOT) != 0:
            raise RuntimeError('现有后端版本过旧，请双击“重启后端.cmd”。')
        log_dir = ROOT / 'artifacts/startup' / time.strftime('%Y%m%d-%H%M%S')
        log_dir.mkdir(parents=True, exist_ok=True)
        print(f'日志目录：{log_dir}', flush=True)
        api_job, web_job = ProcessJob(), ProcessJob()
        if api_pid:
            adopt_tree(api_job, snapshot, api_pid)
        if web_pid:
            adopt_tree(web_job, snapshot, web_pid)

        def start_api():
            return api_job.spawn([python, '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1',
                                  '--port', str(args.api_port)], ROOT, log_dir / 'api.log')

        def restart_api():
            nonlocal api_job, api_pid
            ensure_idle(args.api_port)
            api_job.close()
            api_job = ProcessJob()
            for _ in range(40):
                try:
                    read_json(f'http://127.0.0.1:{args.api_port}/api/health')
                except OSError:
                    break
                time.sleep(0.1)
            api_pid = start_api()
            wait_ready(f'http://127.0.0.1:{args.api_port}/api/health', lambda body: json.loads(body)['status'] == 'ok')
            if check_backend(f'http://127.0.0.1:{args.api_port}', ROOT) != 0:
                raise RuntimeError('后端版本检查未通过。')
            print('后端已重启，仍由本 CMD 管理。', flush=True)

        if api_pid and args.restart_backend:
            restart_api()
        elif not api_pid:
            api_pid = start_api()
        if not web_pid:
            web_pid = web_job.spawn([node, vite, '--host', '127.0.0.1', '--port', str(args.web_port), '--strictPort'], ROOT / 'webui', log_dir / 'web.log')
        wait_ready(f'http://127.0.0.1:{args.api_port}/api/health', lambda body: json.loads(body)['status'] == 'ok')
        wait_ready(f'http://127.0.0.1:{args.web_port}/', lambda body: 'MediaCrawler - Command Center' in body)
        if check_backend(f'http://127.0.0.1:{args.api_port}', ROOT) != 0:
            raise RuntimeError('后端版本检查未通过，请重启。')
        print(f'项目已启动：http://127.0.0.1:{args.web_port}/', flush=True)
        print('本窗口管理前端、后端及其子任务。关闭本窗口，项目将一起停止。', flush=True)
        print('按 Ctrl+C 也可停止项目；请等待审核标记保存后再关闭。', flush=True)
        if not args.no_open:
            webbrowser.open(f'http://127.0.0.1:{args.web_port}/')
        while True:
            if kernel.WaitForSingleObject(event, 500) == 0:
                try:
                    restart_api()
                except (RuntimeError, OSError) as exc:
                    print(f'重启未完成：{exc}', flush=True)
            for pid in (api_pid, web_pid):
                handle = kernel.OpenProcess(0x1000, False, pid)
                if not handle:
                    raise RuntimeError(f'服务进程 {pid} 已退出，请查看日志目录。')
                try:
                    code = W.DWORD()
                    checked(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                    if code.value != 259:
                        raise RuntimeError(f'服务进程 {pid} 已退出，请查看日志目录。')
                finally:
                    kernel.CloseHandle(handle)
    except KeyboardInterrupt:
        print('\n正在停止项目……', flush=True)
        return 0
    finally:
        for job in (api_job, web_job):
            if job:
                job.close()
        if event:
            kernel.CloseHandle(event)
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--restart-backend', action='store_true')
    parser.add_argument('--api-port', type=int, default=18080)
    parser.add_argument('--web-port', type=int, default=5173)
    try:
        sys.exit(run(parser.parse_args()))
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'启动失败：{exc}', flush=True)
        sys.exit(1)
