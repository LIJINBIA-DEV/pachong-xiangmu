# 在 Mac 上运行

项目目录：`/Users/Admin/Downloads/MediaCrawler`

1. 在 PyCharm 打开本目录。
2. 选择运行配置 **MediaCrawler WebUI (Mac)**，点击运行。
3. 打开 <http://127.0.0.1:18080/>。
4. 在配置页选择平台、填写关键词，再开始采集并扫码登录。

停止服务：点击 PyCharm 运行窗口的停止按钮。

Python 解释器使用项目的 `.venv/bin/python`（Python 3.11）。Mac 所需的 Node、Python 依赖及 Chromium 已安装；原 Windows 环境保留在 `.venv.windows` 和 `webui/node_modules.windows`。

也可以在终端运行：

```sh
cd /Users/Admin/Downloads/MediaCrawler
.venv/bin/python scripts/start_mac.py
```

如果 PyCharm 中的服务已启动，无需再次启动，以免端口冲突。

已验证：依赖兼容性、前端构建、应用导入、JavaScript 运行环境、Chromium 启动、后端环境自检与网页加载；登录环境相关测试 6 项通过。

尚未验证：账号扫码登录后的真实采集、第三方模型 API 调用。启用图片识别等云模型功能需要有效的对应 API Key。仪表盘原有数据来自下载的项目，不是本次测试新采集的数据。
