import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from api.services.school_review_settings import SchoolReviewSettings
from api.services.school_review_cache import SchoolReviewCache
from api.services.school_review_profile import aggregate_profile, VERSION
from api.services.school_reviews import SchoolReviewJobs
from collection_tasks import atomic_json, review_progress, review_progress_path


def completed_job(epoch=None):
    posts = [{'post_id': '1', 'title': '体验', 'content': '宿舍有空调', 'url': 'https://example.com/1',
              'comments': [], 'relevance': 'relevant'}]
    return {'job_id': 'a' * 32, 'owner': 'private-owner', 'run_file': '/private/run',
            'school': '贵州大学', 'topic': '计算机体验', 'platform': 'zhihu', 'status': 'COMPLETED',
            'created_epoch': time.time() if epoch is None else epoch, 'created_at': '2026-10-20T03:00:00+0800',
            'analysis_version': VERSION, 'posts': posts, 'screening_status': 'COMPLETED',
            'profile': aggregate_profile(posts, []), 'fetched_count': 1}


class Process:
    returncode = 0
    def poll(self): return self.returncode


class Manager:
    status = 'idle'
    process = Process()
    collection_run = None
    starts = 0
    async def start(self, request, collection_run):
        self.starts += 1
        self.collection_run = collection_run
        return True
    async def stop(self):
        self.process.returncode = -15


def test_default_flags_are_off_and_configuration_is_strict(tmp_path):
    settings = SchoolReviewSettings.load(tmp_path)
    assert not any([settings.progress_enabled, settings.cache_enabled, settings.prewarm_enabled])
    for kwargs in [dict(cache_days=0), dict(cache_days=16), dict(prewarm_enabled=True),
                   dict(progress_enabled='false'), dict(prewarm_hour=24),
                   dict(prewarm_targets=[{'school': '贵州大学,清华', 'topic': '体验', 'platform': 'xhs'}])]:
        with pytest.raises(ValueError): SchoolReviewSettings(**kwargs)


def test_cache_ttl_version_and_no_private_metadata_or_sliding_expiry(tmp_path):
    cache = SchoolReviewCache(tmp_path, 7)
    job = completed_job(1000)
    cache.put(job)
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=1001)
    assert cache.get('贵州大学', '计算机体验', 'bili', now=1001) is None
    assert cache.get('贵州大学', '其他主题', 'zhihu', now=1001) is None
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=1000 + 7 * 86400) is None
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=999) is None
    path = next(cache.directory.glob('*.json'))
    assert 'private-owner' not in path.read_text() and '/private/run' not in path.read_text()
    entry = json.loads(path.read_text()); entry['analysis_version'] = -1; atomic_json(path, entry)
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=1001) is None
    entry['analysis_version'] = VERSION; entry['data']['profile'] = []; atomic_json(path, entry)
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=1001) is None
    path.write_text('broken json')
    assert cache.get('贵州大学', '计算机体验', 'zhihu', now=1001) is None


@pytest.mark.parametrize('change', [{'status': 'EMPTY'}, {'status': 'FAILED'}, {'screening_status': 'UNAVAILABLE'},
                                    {'profile': {'status': 'UNAVAILABLE'}}])
def test_failed_or_unscreened_results_never_poison_long_cache(tmp_path, change):
    cache = SchoolReviewCache(tmp_path, 15); cache.put({**completed_job(), **change})
    assert not cache.directory.exists()


def test_long_cache_reuses_public_material_but_keeps_job_ownership(tmp_path):
    async def run():
        settings = SchoolReviewSettings(cache_enabled=True)
        manager = Manager(); jobs = SchoolReviewJobs(manager, tmp_path, settings=settings)
        jobs.cache.put(completed_job(time.time() - 3 * 86400))
        first = await jobs.start('u1', '贵州大学', '计算机体验', 'zhihu')
        second = await jobs.start('u2', '贵州大学', '计算机体验', 'zhihu')
        assert manager.starts == 0 and first['cache']['ttl_days'] == 7
        assert first['job_id'] != second['job_id']
        assert first['cache']['collected_at'] == '2026-10-20T03:00:00+0800'
        assert 'owner' not in first and 'run_file' not in first
        with pytest.raises(FileNotFoundError): jobs.read(first['job_id'], 'u2')
        assert json.loads(next(jobs.cache.directory.glob('*.json')).read_text())['collected_epoch'] < time.time() - 2 * 86400
        manager.status = 'running'
        assert (await jobs.start('u1', '贵州大学', '计算机体验', 'zhihu', refresh=True))['status'] == 'BUSY'
        expired = jobs.read(first['job_id'], 'u1')
        expired['cache']['expires_epoch'] = time.time() - 1; jobs.save(expired)
        jobs.cache.get = lambda *args, **kwargs: None
        assert (await jobs.start('u1', '贵州大学', '计算机体验', 'zhihu'))['status'] == 'BUSY'
        # Even a previous materialized hit cannot activate the feature once disabled.
        jobs.settings.cache_enabled = False
        assert (await jobs.start('u1', '贵州大学', '计算机体验', 'zhihu'))['status'] == 'BUSY'
        await jobs.close()
    asyncio.run(run())


def test_progress_only_counts_saved_unique_posts_for_opted_in_runs(tmp_path, monkeypatch):
    run = tmp_path / 'run.json'; monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    review_progress('SEARCHING')
    assert not review_progress_path(run).exists()
    atomic_json(review_progress_path(run), {'stage': 'OPENING_BROWSER', 'current': 0, 'total': 5, 'ids': []})
    review_progress('SEARCHING'); review_progress('CRAWLING', 'n1'); review_progress('CRAWLING', 'n1')
    review_progress('CRAWLING', 'n2'); review_progress('SEARCHING')
    result = json.loads(review_progress_path(run).read_text())
    assert result['stage'] == 'CRAWLING' and result['current'] == 2
    jobs = SchoolReviewJobs(Manager(), tmp_path, settings=SchoolReviewSettings(progress_enabled=True))
    job = {'job_id': 'b' * 32, 'owner': 'u', 'status': 'RUNNING', 'run_file': str(run)}
    jobs.sync_progress(job)
    assert jobs.public(job)['progress'] == {'stage': 'CRAWLING', 'current': 2, 'total': 5}
    assert 'ids' not in jobs.public(job)['progress']
    jobs.settings.progress_enabled = False
    assert 'progress' not in jobs.public(job)


def test_real_watch_pipeline_emits_only_observed_stages_and_populates_cache(tmp_path, monkeypatch):
    import api.services.school_reviews as module
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    posts = completed_job()['posts']
    monkeypatch.setattr(module, 'extract_posts', lambda *args: posts)
    observed = []
    async def classify(*args):
        observed.append(json.loads(next((tmp_path / 'data/.ragent-reviews').glob('*.json')).read_text())['progress'])
        return posts, 'COMPLETED'
    async def profile(*args):
        observed.append(json.loads(next((tmp_path / 'data/.ragent-reviews').glob('*.json')).read_text())['progress'])
        return aggregate_profile(posts, [])
    monkeypatch.setattr(module, 'classify_posts', classify); monkeypatch.setattr(module, 'build_profile', profile)
    async def run():
        jobs = SchoolReviewJobs(Manager(), tmp_path, settings=SchoolReviewSettings(progress_enabled=True, cache_enabled=True))
        result = await jobs.start('u', '贵州大学', '计算机体验', 'zhihu')
        await jobs.tasks[result['job_id']]
        assert jobs.cache.get('贵州大学', '计算机体验', 'zhihu')
        assert observed == [{'stage': 'FILTERING', 'current': 0, 'total': 1}, {'stage': 'PROFILING'}]
        assert jobs.read(result['job_id'], 'u')['progress']['stage'] == 'COMPLETED'
        await jobs.close()
    asyncio.run(run())


def test_prewarm_is_opt_in_never_immediate_and_does_not_preempt_workbench(tmp_path):
    async def run():
        manager = Manager(); jobs = SchoolReviewJobs(manager, tmp_path)
        jobs.start_prewarm(); await jobs.run_prewarm_once()
        assert jobs.scheduler is None and manager.starts == 0
        settings = SchoolReviewSettings(cache_enabled=True, prewarm_enabled=True,
            prewarm_targets=[{'school': '贵州大学', 'topic': '计算机体验', 'platform': 'zhihu'}])
        jobs = SchoolReviewJobs(manager, tmp_path, settings=settings)
        jobs.start_prewarm(); await asyncio.sleep(0)
        assert jobs.prewarm_state['status'] == 'WAITING' and manager.starts == 0
        assert jobs.prewarm_state['next_run'].endswith('+08:00')
        manager.status = 'running'
        await jobs.run_prewarm_once()
        assert jobs.prewarm_state['status'] == 'BUSY' and manager.starts == 0
        manager.status = 'idle'; jobs.cache.put(completed_job())
        await jobs.run_prewarm_once()
        assert jobs.prewarm_state == {'status': 'COMPLETED', 'completed': 0, 'skipped': 1}
        assert manager.starts == 0
        await jobs.close(); assert jobs.scheduler is None
    asyncio.run(run())


@pytest.mark.parametrize('quality', ['COMPLETED', 'UNAVAILABLE'])
def test_prewarm_collects_missing_entries_but_stops_after_analysis_failure(tmp_path, monkeypatch, quality):
    import api.services.school_reviews as module
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    posts = completed_job()['posts']
    monkeypatch.setattr(module, 'extract_posts', lambda *args: posts)
    monkeypatch.setattr(module, 'classify_posts', AsyncMock(return_value=(posts, quality)))
    monkeypatch.setattr(module, 'build_profile', AsyncMock(return_value=aggregate_profile(posts, [])))
    async def run():
        manager = Manager()
        targets = [{'school': school, 'topic': '计算机体验', 'platform': 'zhihu'} for school in ['贵州大学', '四川大学']]
        jobs = SchoolReviewJobs(manager, tmp_path, settings=SchoolReviewSettings(cache_enabled=True, prewarm_enabled=True, prewarm_targets=targets))
        await jobs.run_prewarm_once()
        if quality == 'COMPLETED':
            assert manager.starts == 2 and jobs.prewarm_state['completed'] == 2
            assert jobs.prewarm_state['status'] == 'COMPLETED'
            assert all(jobs.cache.get(**target) for target in targets)
        else:
            assert manager.starts == 1 and jobs.prewarm_state['status'] == 'FAILED'
            assert not any(jobs.cache.get(**target) for target in targets)
        await jobs.close()
    asyncio.run(run())


def test_shutdown_during_prewarm_stops_its_crawler_instead_of_orphaning_it(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    async def run():
        manager = Manager(); manager.process = Process(); manager.process.returncode = None
        jobs = SchoolReviewJobs(manager, tmp_path, settings=SchoolReviewSettings(cache_enabled=True, prewarm_enabled=True,
            prewarm_targets=[{'school': '贵州大学', 'topic': '体验', 'platform': 'zhihu'}]))
        jobs.scheduler = asyncio.create_task(jobs.run_prewarm_once())
        for _ in range(20):
            await asyncio.sleep(0)
            if jobs.tasks: break
        assert jobs.tasks and manager.process.poll() is None
        await jobs.close()
        assert manager.process.poll() == -15 and not jobs.tasks and jobs.scheduler is None
        saved = json.loads(next(jobs.directory.glob('*.json')).read_text())
        assert saved['status'] == 'CANCELLED'
    asyncio.run(run())


def test_corrupt_job_files_do_not_block_other_queries_or_ownership(tmp_path):
    async def run():
        jobs = SchoolReviewJobs(Manager(), tmp_path, settings=SchoolReviewSettings(cache_enabled=True))
        jobs.directory.mkdir(parents=True)
        (jobs.directory / ('b' * 32 + '.json')).write_text('broken json')
        (jobs.directory / ('c' * 32 + '.json')).write_text('[]')
        jobs.cache.put(completed_job(time.time() - 86400))
        result = await jobs.start('u', '贵州大学', '计算机体验', 'zhihu')
        assert result['status'] == 'COMPLETED' and result['cache']['layer'] == 'long_term'
        for identity in ['b' * 32, 'c' * 32]:
            with pytest.raises(FileNotFoundError): jobs.read(identity, 'u')
        await jobs.close()
    asyncio.run(run())


def test_failed_analysis_is_not_reused_as_a_successful_short_cache(tmp_path):
    async def run():
        manager = Manager(); manager.status = 'running'
        jobs = SchoolReviewJobs(manager, tmp_path)
        job = completed_job(); job['screening_status'] = 'UNAVAILABLE'; jobs.save(job)
        result = await jobs.start('private-owner', '贵州大学', '计算机体验', 'zhihu')
        assert result['status'] == 'BUSY' and not result.get('reused')
        job['screening_status'] = 'COMPLETED'; job['profile']['status'] = 'UNAVAILABLE'; jobs.save(job)
        assert (await jobs.start('private-owner', '贵州大学', '计算机体验', 'zhihu'))['status'] == 'BUSY'
        await jobs.close()
    asyncio.run(run())


def test_timeout_also_bounds_analysis_after_crawler_has_finished(tmp_path, monkeypatch):
    import api.services.school_reviews as module
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    monkeypatch.setattr(module, 'extract_posts', lambda *args: completed_job()['posts'])
    async def stalled_analysis(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(module, 'classify_posts', stalled_analysis)
    async def run():
        jobs = SchoolReviewJobs(Manager(), tmp_path, timeout=.05)
        result = await jobs.start('u', '贵州大学', '计算机体验', 'zhihu')
        await asyncio.wait_for(jobs.tasks[result['job_id']], timeout=1)
        assert jobs.read(result['job_id'], 'u')['status'] == 'TIMED_OUT'
        assert not jobs.tasks
    asyncio.run(run())
