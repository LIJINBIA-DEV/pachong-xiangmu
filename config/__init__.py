# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/__init__.py
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


from .base_config import *
from .db_config import *

# Opt-in container defaults. Keep the desktop's existing browser behavior.
import os as _os
if _os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1':
    ENABLE_CDP_MODE = False
    CDP_CONNECT_EXISTING = False
    HEADLESS = CDP_HEADLESS = True
    LOGIN_TYPE = 'cookie'

# Explicit desktop UI mode uses the upstream Playwright persistent browser path.
# It owns its browser/profile and never waits for a separately opened CDP port.
if _os.environ.get('MEDIACRAWLER_LOGIN_ENVIRONMENT') == 'local':
    ENABLE_CDP_MODE = CDP_CONNECT_EXISTING = False
    HEADLESS = CDP_HEADLESS = False
