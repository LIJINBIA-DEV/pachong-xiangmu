"""Bound the official Playwright download, including its child processes."""
import argparse
import os
import subprocess
import sys


def install(timeout=600):
    command = [sys.executable, '-m', 'playwright', 'install', 'chromium']
    # The Job Object kills only this installer's descendants on timeout/exit.
    if os.name == 'nt':
        from project_session import ProcessJob
        job = ProcessJob()
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        assigned = False
        try:
            job.adopt(process.pid)
            assigned = True
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print('Browser download timed out. Check network access to the Playwright CDN, '
                  'or install Chrome/Edge and retry.', file=sys.stderr)
            return 1
        finally:
            job.close()
            if not assigned and process.poll() is None:
                process.kill()
            process.wait(timeout=10)
    return subprocess.run(command, timeout=timeout).returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    sys.exit(install(args.timeout))
