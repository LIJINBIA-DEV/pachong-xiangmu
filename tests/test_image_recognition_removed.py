"""Removing the controls must also prevent old configs from starting inference."""
from types import SimpleNamespace
import asyncio
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import data as data_router
from api.schemas.crawler import CrawlerStartRequest
from api.services.crawler_manager import CrawlerManager


def test_removed_image_endpoints_do_not_start_jobs_or_write_keys(monkeypatch):
    from api.services.image_subject import image_subject_jobs
    async def unexpected(*args, **kwargs):
        pytest.fail('Removed feature started inference')
    monkeypatch.setattr(image_subject_jobs, 'start', unexpected)
    app = FastAPI()
    app.include_router(data_router.router,prefix='/api')
    client = TestClient(app)
    assert client.get('/api/data/image-subject', params={'file':'old.xlsx'}).status_code == 410
    assert client.get('/api/data/image-subject/settings').status_code == 410
    response = client.post('/api/data/image-subject',json={'file':'old.xlsx'})
    assert response.status_code == 410
    response = client.put('/api/data/image-subject/settings',json={'provider':'local'})
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_old_config_and_environment_cannot_enable_automatic_recognition(tmp_path,monkeypatch):
    import config
    monkeypatch.setattr(config,'SAVE_DATA_PATH',str(tmp_path))
    monkeypatch.setenv('MEDIACRAWLER_IMAGE_SUBJECT','1')
    monkeypatch.setenv('MEDIACRAWLER_IMAGES_ONLY','1')
    monkeypatch.setenv('SILICONFLOW_API_KEY','test-unused-secret')
    module = importlib.import_module('api.services.crawler_manager')
    captured = {}
    def launch(command,**kwargs):
        captured.update(command=command,env=kwargs['env'])
        return SimpleNamespace(poll=lambda:None)
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    async def no_output(): pass
    manager = CrawlerManager()
    monkeypatch.setattr(manager,'_read_output',no_output)
    request = CrawlerStartRequest(platform='wb',save_option='excel',keywords='查询内容',login_type='cookie',cookies='test-cookie',image_subject_recognition=True,enable_media=False)
    assert await manager.start(request)
    await manager._read_task
    assert captured['env']['MEDIACRAWLER_IMAGE_SUBJECT']=='0'
    assert captured['env']['MEDIACRAWLER_IMAGES_ONLY']=='0'
    assert captured['env']['SILICONFLOW_API_KEY']==''
    assert captured['command'][captured['command'].index('--get_media')+1]=='false'
