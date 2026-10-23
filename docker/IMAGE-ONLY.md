# 单镜像部署：内置采集浏览器和 Jev 代理

镜像标签：`mediacrawler-portable:20261020-proxy-fix2`。交付物只有一个
`mediacrawler-20261020-proxy-fix2-amd64.tar` 镜像文件；无需源码、Compose 或启动脚本。
包含工作台、采集程序、Chromium/noVNC、Mihomo v1.19.32。
预构建包是 Linux amd64，适用于 Intel/AMD 的 Linux Docker 引擎，以及
Windows Docker Desktop 的 Linux 容器。Docker 必须已经能够正常启动。

本版修复微博 `pics` 字典格式的图片解析，并补全微博详情图片（含 18 图帖子）；
同时保留 fix1 的 Linux 容器网页保存硅基流动密钥功能。

## 导入和启动

Windows CMD 或 PowerShell 中执行（先进入 tar 文件所在目录）：

```text
docker load -i mediacrawler-20261020-proxy-fix2-amd64.tar
```

将下面的 8 位占位符 `XXXXXXXX` 改成自己的 8 位英文字母或数字密码，再整行复制运行：

```text
docker run -d --name mediacrawler --init --restart unless-stopped --stop-timeout=90 --shm-size=1g -p 127.0.0.1:18180:8080 -p 127.0.0.1:16080:6080 -e BROWSER_PASSWORD=XXXXXXXX -v mediacrawler-data:/app/data -v mediacrawler-browser:/app/browser_data -v mediacrawler-logs:/app/logs mediacrawler-portable:20261020-proxy-fix2
```

以上一行命令也可在 Linux/macOS 终端使用。
也可在 Docker 图形管理界面创建容器，按上述端口、环境变量和卷填写。
导入镜像不会自动创建容器；创建后可在 Docker 界面启停。

- 工作台：http://127.0.0.1:18180
- 登录浏览器：http://127.0.0.1:16080/vnc.html
- 改浏览器对外端口时，同时设置 `DESKTOP_PUBLIC_PORT` 为对应端口。
- 默认绑定本机。工作台没有用户鉴权；远程使用应通过受控内网或 SSH 隧道。
- 已有同名容器时不要盲目删除；先停止采集并备份，再复用其原有数据卷升级。

## 配置 Jev 专用代理

1. 打开工作台“配置”，在“Jev 专用代理”中填写自己的 Clash/Mihomo 订阅链接。
2. 启用代理并保存。选择要使用的节点，选择后立即生效；点击“更新订阅”可刷新节点。
3. 勾选“语义筛选”，在上方 Jev 密钥输入框中填写自己的 API Key，点击“测试 Jev”验证实际 API。
4. 在图片设置中填写自己的硅基流动 API Key，并按原流程扫码登录和采集。

修正版支持在 Linux 容器页面直接保存硅基流动密钥。密文及解密文件都保存在
`/app/data/.image-subject` 私人目录，随数据卷保留；备份时应完整保留该目录并妥善保管。
持有整个数据卷的管理员仍可以解密密钥。若配置了 `SILICONFLOW_API_KEY` 环境变量，
运行时优先使用环境变量；新部署无需设置该变量即可在页面保存。

支持 `proxies:` 节点列表的 Clash/Mihomo YAML 订阅（可带其他完整配置字段，
但只导入节点）。不支持仅有 `proxy-providers:` 引用的配置、Base64 URI 列表
或订阅商网页；请向订阅商获取对应的 Clash/Mihomo 格式链接。
只接受受支持的网络代理节点，订阅内的规则、控制端口、TUN、脚本等不会被应用。

首次保存及“更新订阅”会下载订阅，当前版本由用户手动刷新。订阅下载需要容器本身
能够访问该地址；首次下载直连，已启用时通过当前节点下载。如果当前节点失效，
可先关闭代理并保存，再刷新订阅。重启使用缓存，不依赖启动时联网。

只有 Jev API 使用这条代理。微博、小红书采集和硅基流动保持原来的网络方式，
宿主机浏览器不会自动代理。新镜像的页面开关决定 Jev 是否代理；旧版
`TYPESAFE_PROXY_URL`、SSH 中转设置不再覆盖这个开关。停用代理表示 Jev 直连；
启用后，节点失败会报错，不会悄悄改为直连。

代理内核及控制接口仅在容器内部监听，不需要额外映射代理端口，不需要特权容器。
订阅链接、节点密码及控制密钥不写入镜像、不通过状态接口回显，保存在
`/app/data/.jev-proxy` 私人目录。请勿把包含个人配置的数据卷备份公开分发。

订阅可用、网站能打开、节点延迟低，都不等于 Jev API 可用。
HTTP 451 等服务端限制仍要以实际 Jev 测试结果为准。

## 数据和升级

`mediacrawler-data` 保存采集数据、人工审核记录、图片模型设置和代理配置；
`mediacrawler-browser` 保存登录状态；`mediacrawler-logs` 保存日志。
重建容器应复用这些卷。**不要删除卷**；只导出镜像不包含这些私人数据。
更换机器需另行安全备份、迁移数据卷，并可能需要重新扫码。

## 内核来源

Mihomo 使用未修改的官方 v1.19.32 二进制，下载时校验 SHA-256。
许可证、对应版本源码压缩包和来源记录位于镜像内
`/usr/share/doc/mihomo/`。可以用下面命令取出：

```text
docker cp mediacrawler:/usr/share/doc/mihomo ./mihomo-source-and-license
```

项目原有许可证继续适用。验收范围以随交付的验收记录为准；未配置真实订阅和
Jev Key 时，不能宣称某个节点已通过真实模型调用。
