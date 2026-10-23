"""Background local inference for previously saved collection files."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
from datetime import datetime, timezone

from collection_tasks import atomic_json
from image_subject import cached_prediction, image_catalog, inference_busy, model_ready, recognize_files, valid_prediction, fingerprint
from image_subject_settings import public_settings, runtime_settings


class ImageSubjectJobs:
    def __init__(self):
        self.task = None
        self.key = None

    @property
    def running(self):
        return self.task is not None and not self.task.done()

    def state_path(self, root, path):
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        return root / '.image-subject/jobs' / (hashlib.sha256(relative.encode()).hexdigest() + '.json')

    def status(self, root, path):
        images, missing = image_catalog(root, [path])
        options = runtime_settings(root)
        predictions = [cached_prediction(root, image, fingerprint(provider=options['provider'])) for image in images.values()]
        value = {'status': 'idle', 'total': len(images), 'completed': sum(p.get('status') == 'recognized' and valid_prediction(p) and p.get('policy_status') != 'pending' and p.get('consistency_status') != 'pending' for p in predictions), 'failed': sum(p.get('status') == 'error' for p in predictions), 'not_downloaded': missing}
        saved = self.state_path(root, path)
        if saved.exists():
            try:
                prior = json.loads(saved.read_text(encoding='utf-8'))
                if prior.get('provider', 'local') == options['provider']:
                    value.update({k: prior[k] for k in ('status', 'error', 'updated_at', 'cached') if k in prior})
                if prior.get('force') and prior.get('provider', 'local') == options['provider']:
                    # Existing cached predictions are not progress for a fresh run.
                    value.update({k: prior[k] for k in ('total', 'completed', 'failed', 'not_downloaded', 'force', 'audit') if k in prior})
            except (OSError, ValueError, TypeError):
                pass
        busy = self.running or inference_busy(root)
        if value['status'] in {'queued', 'loading', 'running'} and not busy:
            value['status'] = 'interrupted'
        if value['status'] in {'completed', 'completed_with_errors'} and value['completed'] + value['failed'] < value['total']:
            value['status'] = 'idle'
        return {**value, 'busy': busy, **public_settings(root)}

    async def start(self, root, path, manager, force=False):
        async with manager._lock:
            if manager.status in {'running', 'stopping'} or (manager.process and manager.process.poll() is None):
                raise ValueError('collection_active')
            if self.running or inference_busy(root):
                raise ValueError('image_subject_busy')
            options = runtime_settings(root)
            if options['provider'] == 'local' and not model_ready():
                raise ValueError('image_subject_model_missing')
            if options['provider'] == 'siliconflow' and not options['api_key']:
                raise ValueError('image_subject_key_missing')
            state = await asyncio.to_thread(self.status, root, path)
            if state['total'] == 0:
                raise ValueError('image_subject_no_downloads')
            self.key = str(path)
            state.update(status='queued', error=None, force=force)
            if force:
                state.update(completed=0, failed=0, cached=0)
            atomic_json(self.state_path(root, path), state)
            self.task = asyncio.create_task(self._run(root, path, force=force, options=options))
            return {**state, 'busy': True}

    async def _run(self, root, path, force=False, options=None):
        run_kwargs = {'options': options} if options else {}
        state_path = self.state_path(root, path)
        audit = None
        def progress(state):
            if audit:
                state = {**state, 'audit': str(audit), 'force': force}
            atomic_json(state_path, state)
        try:
            if force:
                from api.services.image_subject_audit import prepare_rerun, finish_rerun
                audit = root / '.image-subject/reruns' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4))
                await asyncio.to_thread(prepare_rerun, root, path, audit, options)
            result = await recognize_files(root, [path], progress=progress, force=force, **run_kwargs)
            if force and result['failed']:
                # Retry only failures after every image has had a fresh pass.
                initial_failed = result['failed']
                result = await recognize_files(root, [path], progress=progress, **run_kwargs)
                result.update(force=True, initial_failed=initial_failed, retry_passes=1)
                progress(result)
            if audit:
                await asyncio.to_thread(finish_rerun, root, path, audit, result)
        except asyncio.CancelledError:
            prior = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            progress({**prior, 'status': 'interrupted'})
            raise
        except Exception as exc:
            prior = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            progress({**prior, 'status': 'error', 'error': str(exc) if str(exc).startswith('image_subject_') else type(exc).__name__})

    async def close(self):
        if self.running:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


image_subject_jobs = ImageSubjectJobs()
