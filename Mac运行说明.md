# 在 Mac 上运行

项目目录：`/Users/Admin/Downloads/MediaCrawler`

1. 在 PyCharm 打开本目录。
2. 选择运行配置 **MediaCrawler WebUI (Mac)**，点击运行。
3. 打开 <http://127.0.0.1:18080/>。
4. 在配置页选择平台、填写采集主题；先点击“检查登录／显示二维码”，登录成功后再开始采集。

小红书本机登录会打开可见浏览器，二维码同步显示在网页。登录与采集共用 `browser_data/xhs_user_data_dir`，下次会先检查已有登录；遇到平台安全验证，请在这台 Mac 打开的浏览器窗口中完成。验证窗口最多保留 10 分钟，可在网页取消。刷新二维码不会清空原有资料目录。服务器版仍使用后台浏览器；本机的浏览器资料正在被其他窗口使用时，请先关闭占用窗口再重试。

网页服务同时支持本机和局域网访问，端口为 `18080`。其他设备连接同一局域网后，使用 `http://这台Mac的局域网IP:18080/` 访问；本机仍可使用上面的 `127.0.0.1` 地址。Mac 须保持开机、服务运行，切换网络后 IP 地址可能变化。当前网页没有登录权限控制，获得访问权限的设备可以查看数据并操作采集任务。

停止服务：点击 PyCharm 运行窗口的停止按钮。

Python 解释器使用项目的 `.venv/bin/python`（Python 3.11）。Mac 所需的 Node、Python 依赖及 Chromium 已安装；原 Windows 环境保留在 `.venv.windows` 和 `webui/node_modules.windows`。

也可以在终端运行：

```sh
cd /Users/Admin/Downloads/MediaCrawler
.venv/bin/python scripts/start_mac.py
```

如果 PyCharm 中的服务已启动，无需再次启动，以免端口冲突。

使用 Jev 语义筛选前，在配置页保存自己的 API Key；AI 内容总结的接口与 Key 在“数据管理 → AI 设置”中单独配置。已有采集数据会保留。

在其他电脑上使用时，需要重新安装 Python、Node.js、项目依赖和 Playwright 浏览器；本机虚拟环境不能直接跨电脑复制。交付安装步骤见《交付说明.md》。
