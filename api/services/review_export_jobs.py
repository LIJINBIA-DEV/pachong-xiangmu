"""Bounded export preparation and cancellable, expiring disk-backed downloads."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, RLock, Thread
import time
from uuid import uuid4
from fastapi.responses import FileResponse

from api.services.review_export import TIMEZONE
from api.services.review_package import build_package, safe_component


class ReviewExportJobs:
    def __init__(self):
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='review-export')
        self.jobs = {}
        self.ttl = 3600
        self.roots = set()
        self.stopped = Event()
        Thread(target=self._reap, name='review-export-cleanup', daemon=True).start()

    def _reap(self):
        while not self.stopped.wait(60):
            try:
                with self.lock:
                    self._cleanup()
            except OSError:
                pass  # Retry on the next tick; never expand cleanup outside owned outputs.

    def _cleanup(self):
        now = time.time()
        for key, job in list(self.jobs.items()):
            if job['status'] not in {'queued', 'preparing'} and not job['downloads'] and now - job['updated'] > self.ttl:
                job['output'].unlink(missing_ok=True)
                self.jobs.pop(key)
        active = {p for j in self.jobs.values() for p in (j['output'], j['output'].with_suffix('.xlsx'))}
        for root in self.roots:
            directory = root / '.review-exports'
            if directory.is_symlink():
                continue
            for old in directory.glob('*'):
                if old.suffix in {'.zip', '.xlsx'} and len(old.stem) == 32 and all(c in '0123456789abcdef' for c in old.stem) and old not in active and now - old.stat().st_mtime > self.ttl:
                    old.unlink(missing_ok=True)

    def public(self, job):
        return {'id': job['id'], 'status': job['status'], 'processed': job['processed'],
                'total': job['total'], 'error': job['error'], 'counts': dict(job['counts']),
                'download_url': f"/api/data/review/export/jobs/{job['id']}/download" if job['status'] == 'ready' else None,
                'filename': job['filename']}

    def start(self, root, path):
        root = root.resolve()
        with self.lock:
            self.roots.add(root)
            self._cleanup()
            for job in self.jobs.values():
                if job['status'] in {'queued', 'preparing'}:
                    if job['root'] == root and job['source'] == path:
                        return self.public(job)
                    raise ValueError('review_export_busy')
            directory = root / '.review-exports'
            if directory.is_symlink():
                raise ValueError('review_export_invalid_storage')
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.resolve().relative_to(root)
            if sum(j['root'] == root and j['status'] == 'ready' for j in self.jobs.values()) >= 3:
                raise ValueError('review_export_capacity')
            identity = uuid4().hex
            job = {'id': identity, 'root': root, 'source': path, 'status': 'queued', 'output': directory / (identity + '.zip'),
                   'cancel': Event(), 'processed': 0, 'total': 0, 'error': None, 'counts': {}, 'downloads': 0,
                   'filename': safe_component(path.stem) + '_审核结果_' + datetime.now(TIMEZONE).strftime('%Y%m%d_%H%M%S') + '.zip',
                   'updated': time.time()}
            self.jobs[identity] = job
            self.executor.submit(self._prepare, job)
            return self.public(job)

    def _prepare(self, job):
        def progress(done, total):
            with self.lock:
                job.update(processed=done, total=total, updated=time.time())
        try:
            with self.lock:
                job['status'] = 'preparing'
            counts = build_package(job['root'], job['source'], job['output'], job['cancel'], progress)
            with self.lock:
                if job['cancel'].is_set():
                    raise ValueError('review_export_cancelled')
                job.update(status='ready', counts=counts, updated=time.time())
        except Exception as exc:
            try:
                job['output'].unlink(missing_ok=True)
            except OSError:
                pass  # The periodic reaper retries this owned partial output.
            with self.lock:
                code = str(exc)
                job.update(status='cancelled' if job['cancel'].is_set() else 'failed',
                           error=code if code in {'review_export_empty', 'review_export_cancelled'} else 'review_export_failed', updated=time.time())

    def get(self, root, identity):
        with self.lock:
            self._cleanup()
            job = self.jobs.get(identity)
            if job is None or job['root'] != root.resolve():
                raise LookupError('review_export_not_found')
            return job

    def status(self, root, identity):
        with self.lock:
            return self.public(self.get(root, identity))

    def list(self, root):
        with self.lock:
            self._cleanup()
            return [self.public(job) for job in reversed(list(self.jobs.values())) if job['root'] == root.resolve()]

    def acquire(self, root, identity):
        with self.lock:
            job = self.get(root, identity)
            if job['status'] != 'ready' or not job['output'].is_file():
                raise ValueError('review_export_not_ready')
            job['downloads'] += 1
            job['updated'] = time.time()
            return job['output'], job['filename']

    def release(self, root, identity):
        with self.lock:
            job = self.jobs.get(identity)
            if job and job['root'] == root.resolve():
                job['downloads'] = max(0, job['downloads'] - 1)
                job['updated'] = time.time()

    def cancel(self, root, identity):
        with self.lock:
            job = self.get(root, identity)
            if job['downloads']:
                raise ValueError('review_export_downloading')
            job['cancel'].set()
            if job['status'] not in {'queued', 'preparing'}:
                job['output'].unlink(missing_ok=True)
                job.update(status='cancelled', updated=time.time())
            return self.public(job)


review_export_jobs = ReviewExportJobs()


class ReviewPackageResponse(FileResponse):
    """Release the lease even when ASGI sending fails or is cancelled."""
    def __init__(self, root, identity):
        self.root, self.identity = root, identity
        output, filename = review_export_jobs.acquire(root, identity)
        try:
            super().__init__(output, media_type='application/zip', filename=filename,
                             headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        except BaseException:
            review_export_jobs.release(root, identity)
            raise

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            review_export_jobs.release(self.root, self.identity)
