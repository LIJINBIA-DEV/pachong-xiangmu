# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/services/crawler_manager.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import json
import subprocess
import signal
import os
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from ..schemas import CrawlerStartRequest, LogEntry
from semantic_filter import MODEL, SUPPORTED_MODELS
from semif_local import MODEL_ID as SEMIF_MODEL, local_model_ready


class CrawlerManager:
    """Crawler process manager"""

    def __init__(self):
        import uuid
        self.log_session_id = uuid.uuid4().hex
        self._lock = asyncio.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.status = "idle"
        self.stage = "idle"
        self.started_at: Optional[datetime] = None
        self.current_config: Optional[CrawlerStartRequest] = None
        self._log_id = 0
        self._logs: List[LogEntry] = []
        self._read_task: Optional[asyncio.Task] = None
        # Project root directory
        self._project_root = Path(__file__).parent.parent.parent
        # Log queue - for pushing to WebSocket
        self._log_queue: Optional[asyncio.Queue] = None
        self.collection_run: Optional[Path] = None
        self.task_credentials: dict = {}  # Session only; never written to metadata.

    @property
    def logs(self) -> List[LogEntry]:
        return self._logs

    def get_log_queue(self) -> asyncio.Queue:
        """Get or create log queue"""
        if self._log_queue is None:
            self._log_queue = asyncio.Queue()
        return self._log_queue

    def _create_log_entry(self, message: str, level: str = "info") -> LogEntry:
        """Create log entry"""
        self._log_id += 1
        entry = LogEntry(
            id=self._log_id,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
            session_id=self.log_session_id,
        )
        self._logs.append(entry)
        # Keep last 500 logs
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
        return entry

    async def _push_log(self, entry: LogEntry):
        """Push log to queue"""
        if self._log_queue is not None:
            try:
                self._log_queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def _parse_log_level(self, line: str) -> str:
        """Parse log level"""
        line_upper = line.upper()
        if "ERROR" in line_upper or "FAILED" in line_upper:
            return "error"
        elif "WARNING" in line_upper or "WARN" in line_upper:
            return "warning"
        elif "SUCCESS" in line_upper or "完成" in line or "成功" in line:
            return "success"
        elif "DEBUG" in line_upper:
            return "debug"
        return "info"

    async def start(self, config: CrawlerStartRequest, collection_run: Optional[Path] = None) -> bool:
        """Start crawler process"""
        async with self._lock:
            if self.process and self.process.poll() is None:
                return False
            from login_environment import resolve_login_environment, login_process_environment
            login_mode = resolve_login_environment(config.login_environment)
            from api.services.weibo_login import weibo_web_login
            from api.services.xhs_login import xhs_web_login
            if weibo_web_login.busy or xhs_web_login.busy:
                raise ValueError('请先完成或取消扫码登录，再开始采集。')
            config = config.model_copy(update={'login_environment': login_mode, 'headless': login_mode == 'server', 'image_subject_recognition': False})
            if config.semantic_filter:
                from semantic_filter import COMMENT_SAMPLE_LIMIT
                config = config.model_copy(update={
                    'enable_sub_comments': False,
                    'max_comments_count': min(config.max_comments_count or COMMENT_SAMPLE_LIMIT, COMMENT_SAMPLE_LIMIT),
                })
            web_qr = config.login_type.value == 'qrcode' and config.platform.value in {'wb', 'xhs'}
            if web_qr:
                from media_platform.weibo.session import read_session as read_weibo_session
                from media_platform.xhs.session import read_session as read_xhs_session
                read_session = read_xhs_session if config.platform.value == 'xhs' else read_weibo_session
                if not read_session(self._project_root):
                    raise ValueError('请先在配置页完成所选平台的扫码登录，再开始采集。')
            if login_mode == 'server':
                if config.login_type.value == 'qrcode':
                    if config.platform.value not in {'wb', 'xhs'}:
                        raise ValueError('网页扫码支持微博和小红书，其他平台请使用 Cookie。')
                elif not config.cookies.strip():
                    raise ValueError('容器采集需要填写有效 Cookie；失效后请更新 Cookie 再继续。')
                config = config.model_copy(update={'headless': True})
            api_key = ""
            if config.semantic_filter:
                if config.crawler_type.value != "search" or config.platform.value not in ("wb", "xhs") or config.save_option.value != "excel":
                    raise ValueError("Semantic filtering requires Weibo/Xiaohongshu search with Excel output")
                if config.semantic_model not in SUPPORTED_MODELS:
                    raise ValueError("Unsupported semantic model")
                if config.semantic_rule == 'topic' and config.semantic_model != MODEL:
                    raise ValueError('主题相关筛选目前需要选择 Jev 模型。')
                from api.routers.data import data_root
                from api.services.semantic_settings import runtime_key
                api_key = (config.semantic_api_key.get_secret_value() if config.semantic_api_key else "") or runtime_key(data_root())
                if config.semantic_model == MODEL and not api_key.strip():
                    raise ValueError("Enter a TypeSafe API Key in the web form or set TYPESAFE_API_KEY on the server")
                if config.semantic_model == SEMIF_MODEL and not local_model_ready():
                    raise ValueError("Local SemIf model or runtime is missing/incomplete; wait for the model download")
                if not config.enable_comments:
                    raise ValueError("Enable comment extraction for semantic filtering")
                if not config.keyword_pairs or [" ".join(part for part in (a, b) if part).strip() for a, b in config.keyword_pairs] != config.keywords.split(","):
                    raise ValueError("采集主题与搜索内容不一致，请重新填写主题卡片。")
                if any(not a.strip() or (config.semantic_rule == 'scene' and not b.strip()) for a, b in config.keyword_pairs):
                    raise ValueError('请填写完整采集主题；主题评价需要同时填写评价词和评价对象。')

            from publication_time import PublicationWindow
            publication_window = PublicationWindow.resolve(config.publish_time_range, config.publish_start_date, config.publish_end_date)
            if collection_run:
                from collection_tasks import read_task
                run_metadata = json.loads(Path(collection_run).read_text(encoding='utf-8'))
                original = read_task(Path(run_metadata['root']), run_metadata['task_id'])['config'].get('publication_window')
                if original:
                    publication_window = PublicationWindow(**original)

            # Clear old logs
            import uuid
            self.log_session_id = uuid.uuid4().hex
            self._logs = []
            self._log_id = 0

            # Clear pending queue (don't replace object to avoid WebSocket broadcast coroutine holding old queue reference)
            if self._log_queue is None:
                self._log_queue = asyncio.Queue()
            else:
                try:
                    while True:
                        self._log_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            # Build command line arguments
            cmd = self._build_command(config)
            import config as crawler_config
            from collection_tasks import create_task, prepare_run
            task_config = config.model_dump(mode='json', exclude={'semantic_api_key', 'cookies'})
            task_config['publication_window'] = publication_window.as_dict()
            task_config['max_notes_count'] = config.max_notes_count or crawler_config.CRAWLER_MAX_NOTES_COUNT
            task_config['max_comments_count'] = config.max_comments_count if config.max_comments_count is not None else crawler_config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
            if 'weibo_search_type' not in config.model_fields_set:
                task_config['weibo_search_type'] = crawler_config.WEIBO_SEARCH_TYPE
            if collection_run is None and config.platform.value in {'wb', 'xhs'} and config.crawler_type.value == 'search' and config.save_option.value == 'excel':
                root = Path(crawler_config.SAVE_DATA_PATH or self._project_root / 'data')
                root = (root if root.is_absolute() else self._project_root / root).resolve()
                targets = {keyword: task_config['max_notes_count'] for keyword in config.keywords.split(',') if keyword.strip()}
                task = create_task(root, task_config, targets)
                collection_run = prepare_run(root, task, targets)

            # Log start information
            display_cmd = list(cmd)
            if '--cookies' in display_cmd:
                display_cmd[display_cmd.index('--cookies') + 1] = '[redacted]'
            entry = self._create_log_entry(f"Starting crawler: {' '.join(display_cmd)}", "info")
            await self._push_log(entry)

            try:
                if collection_run:
                    from collection_tasks import finish_run
                    finish_run(collection_run, 'running')
                # Start subprocess
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(self._project_root),
                    env={
                        **os.environ,
                        **login_process_environment(login_mode),
                        "PYTHONUNBUFFERED": "1",
                        "MEDIACRAWLER_WEB_QR_LOGIN": "1" if web_qr else "0",
                        "MEDIACRAWLER_SEMANTIC_FILTER": "1" if config.semantic_filter else "0",
                        "MEDIACRAWLER_SEMANTIC_MODEL": config.semantic_model,
                        "MEDIACRAWLER_SEMANTIC_RULE": config.semantic_rule,
                        "MEDIACRAWLER_KEYWORD_PAIRS": json.dumps(config.keyword_pairs, ensure_ascii=False),
                        "TYPESAFE_API_KEY": api_key if config.semantic_filter else os.environ.get("TYPESAFE_API_KEY", ""),
                        "MEDIACRAWLER_COLLECTION_RUN": str(collection_run) if collection_run else '',
                        "MEDIACRAWLER_PUBLICATION_WINDOW": json.dumps(publication_window.as_dict()),
                        "MEDIACRAWLER_WEIBO_SEARCH_TYPE": task_config['weibo_search_type'],
                        "MEDIACRAWLER_IMAGE_SUBJECT": "0",
                        "MEDIACRAWLER_IMAGE_PROVIDER": "",
                        "SILICONFLOW_API_KEY": "",
                        "MEDIACRAWLER_IMAGES_ONLY": "0",
                    }
                )

                self.status = "running"
                self.stage = "starting" if config.platform.value in {'wb', 'xhs'} else "running"
                self.started_at = None if self.stage == 'starting' else datetime.now()
                self.current_config = config.model_copy(update={"semantic_api_key": None})
                self.collection_run = collection_run
                if collection_run:
                    run = json.loads(collection_run.read_text(encoding='utf-8'))
                    self.task_credentials[run['task_id']] = {'semantic_api_key': api_key, 'cookies': config.cookies}

                entry = self._create_log_entry(
                    f"Preparing crawler on platform: {config.platform.value}, type: {config.crawler_type.value}",
                    "success"
                )
                await self._push_log(entry)

                # Start log reading task
                self._read_task = asyncio.create_task(self._read_output())

                return True
            except Exception as e:
                if collection_run:
                    from collection_tasks import finish_run
                    finish_run(collection_run, 'failed')
                self.status = "error"
                entry = self._create_log_entry(f"Failed to start crawler: {str(e)}", "error")
                await self._push_log(entry)
                return False

    async def stop(self) -> bool:
        """Stop crawler process"""
        async with self._lock:
            if not self.process or self.process.poll() is not None:
                return False

            self.status = "stopping"
            entry = self._create_log_entry("Sending SIGTERM to crawler process...", "warning")
            await self._push_log(entry)

            try:
                self.process.send_signal(signal.SIGTERM)

                # Container shutdown allows the crawler's cleanup to flush Excel.
                checks = 120 if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1' else 30
                for _ in range(checks):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.5)

                # If still not exited, force kill
                if self.process.poll() is None:
                    entry = self._create_log_entry("Process not responding, sending SIGKILL...", "warning")
                    await self._push_log(entry)
                    self.process.kill()

                entry = self._create_log_entry("Crawler process terminated", "info")
                await self._push_log(entry)

            except Exception as e:
                entry = self._create_log_entry(f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(entry)

            self.status = "idle"
            if self.collection_run:
                from collection_tasks import finish_run
                finish_run(self.collection_run, 'stopped')
            self.current_config = None

            # Cancel log reading task
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None

            return True

    def get_status(self) -> dict:
        """Get current status"""
        from api.services.weibo_login import weibo_web_login
        from api.services.xhs_login import xhs_web_login
        stage = self.stage if self.status == 'running' else (
            'waiting_login' if weibo_web_login.busy or xhs_web_login.busy else 'idle')
        return {
            "status": self.status,
            "stage": stage,
            "platform": self.current_config.platform.value if self.current_config else None,
            "crawler_type": self.current_config.crawler_type.value if self.current_config else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": None
        }

    def _build_command(self, config: CrawlerStartRequest) -> list:
        """Build main.py command line arguments"""
        cmd = ["uv", "run", "python", "main.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--lt", config.login_type.value])
        cmd.extend(["--type", config.crawler_type.value])
        cmd.extend(["--save_data_option", config.save_option.value])

        # Pass different arguments based on crawler type
        if config.crawler_type.value == "search" and config.keywords:
            cmd.extend(["--keywords", config.keywords])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            cmd.extend(["--specified_id", config.specified_ids])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            cmd.extend(["--creator_id", config.creator_ids])

        if config.start_page != 1:
            cmd.extend(["--start", str(config.start_page)])

        cmd.extend(["--get_comment", "true" if config.enable_comments else "false"])
        cmd.extend(["--get_sub_comment", "true" if config.enable_sub_comments else "false"])
        cmd.extend(["--get_media", "true" if config.enable_media else "false"])

        if config.max_notes_count is not None:
            cmd.extend(["--crawler_max_notes_count", str(config.max_notes_count)])

        if config.max_comments_count is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(config.max_comments_count)])

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        cmd.extend(["--headless", "true" if config.headless else "false"])

        return cmd

    def _update_collection_stage(self, line):
        if self.status == 'running' and self.stage == 'starting' and '[CrawlerStage] collecting' in line:
            self.stage = 'running'
            self.started_at = datetime.now()

    async def _read_output(self):
        """Asynchronously read process output"""
        loop = asyncio.get_event_loop()

        try:
            while self.process and self.process.poll() is None:
                # Read a line in thread pool
                line = await loop.run_in_executor(
                    None, self.process.stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        self._update_collection_stage(line)
                        level = self._parse_log_level(line)
                        entry = self._create_log_entry(line, level)
                        await self._push_log(entry)

            # Read remaining output
            if self.process and self.process.stdout:
                remaining = await loop.run_in_executor(
                    None, self.process.stdout.read
                )
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            self._update_collection_stage(line)
                            level = self._parse_log_level(line)
                            entry = self._create_log_entry(line.strip(), level)
                            await self._push_log(entry)

            # Process ended
            if self.status == "running":
                exit_code = self.process.returncode if self.process else -1
                if exit_code == 0:
                    entry = self._create_log_entry("Crawler completed successfully", "success")
                else:
                    entry = self._create_log_entry(f"Crawler exited with code: {exit_code}", "warning")
                await self._push_log(entry)
                self.status = "idle"
                if self.collection_run:
                    from collection_tasks import finish_run
                    finish_run(self.collection_run, 'completed' if exit_code == 0 else 'failed')

        except asyncio.CancelledError:
            pass
        except Exception as e:
            entry = self._create_log_entry(f"Error reading output: {str(e)}", "error")
            await self._push_log(entry)


# Global singleton
crawler_manager = CrawlerManager()
