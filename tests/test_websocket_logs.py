from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import websocket
from api.services.crawler_manager import CrawlerManager


def test_reconnect_sends_one_recent_snapshot_instead_of_replaying_hundreds(monkeypatch):
    crawler = CrawlerManager()
    for number in range(550):
        crawler._create_log_entry(f'entry {number}')
    assert len(crawler.logs) == 500
    monkeypatch.setattr(websocket, 'crawler_manager', crawler)
    monkeypatch.setattr(websocket, 'start_broadcaster', lambda: None)
    app = FastAPI()
    app.include_router(websocket.router)
    with TestClient(app) as client:
        for _ in range(2):
            with client.websocket_connect('/ws/logs') as connection:
                snapshot = connection.receive_json()
                assert snapshot['type'] == 'log_snapshot'
                assert snapshot['session_id'] == crawler.log_session_id
                assert [item['id'] for item in snapshot['logs']] == list(range(501, 551))
                assert all(item['session_id'] == crawler.log_session_id for item in snapshot['logs'])
                connection.send_text('ping')
                assert connection.receive_text() == 'pong'


def test_empty_snapshot_identifies_server_restart(monkeypatch):
    first, second = CrawlerManager(), CrawlerManager()
    assert first.log_session_id != second.log_session_id
    monkeypatch.setattr(websocket, 'crawler_manager', second)
    monkeypatch.setattr(websocket, 'start_broadcaster', lambda: None)
    app = FastAPI()
    app.include_router(websocket.router)
    with TestClient(app) as client, client.websocket_connect('/ws/logs') as connection:
        assert connection.receive_json() == {'type': 'log_snapshot', 'session_id': second.log_session_id, 'logs': []}
