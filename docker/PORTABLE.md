# Docker 部署版

包含工作台、Python/Node 环境、Chromium、中文字体、网页远程登录窗口和 Mihomo 代理内核。模型使用硅基流动 / Jev API，不需要 GPU。现有 Windows 一键启动版仍可单独使用。

只需镜像文件的用户请直接按 [单镜像部署说明](IMAGE-ONLY.md) 导入并创建容器，无需本目录源码或启动脚本。

## 启动

- Windows：安装并启动 Docker Desktop，切换为 Linux 容器，双击 `启动Docker.cmd`。
- Linux / macOS：安装 Docker 与 Compose v2，执行 `sh 启动Docker.sh`。
- 首次启动会生成私人配置 `.env.portable`。没有本地镜像时 Compose 会从源码构建，首次需要联网下载环境；后续复用镜像。
- 若有预构建的 `mediacrawler-20261020-proxy-fix2-amd64.tar`，可先按单镜像部署说明导入；如需启动脚本自动导入，将文件命名为 `mediacrawler-image.tar`，放在项目目录或项目目录的上一级。启动脚本会在镜像不存在时自动导入；镜像必须匹配目标机器架构。
- 打开 `http://127.0.0.1:18180`。在 `.env.portable` 填入自己的 `SILICONFLOW_API_KEY`、`TYPESAFE_API_KEY`，然后再次运行启动脚本应用配置。
- 本包不包含任何人的密钥、登录状态或旧采集结果。不要向别人发送填写后的 `.env.portable`。
- 当前镜像名 `mediacrawler-portable:20261020-proxy-fix2` 是本地构建名，不是已发布的公共仓库地址。

局域网访问：把 `APP_BIND_IP` 改为服务器的内网 IP，并放行该内网的 `APP_PORT`、`BROWSER_PORT`。工作台目前没有用户登录鉴权，默认只绑定本机；请通过受控内网或 SSH 隧道访问，不要直接映射公网。浏览器密码只保护远程桌面，不保护工作台 API。HTTPS 反向代理需同时代理 noVNC 的 WebSocket，前端当前使用相同主机和单独浏览器端口。

## 扫码和验证码

配置选择「服务器版」「扫码登录」，点击获取二维码。可直接扫码，也可点击「打开登录浏览器」。输入 `.env.portable` 中的 `BROWSER_PASSWORD`（VNC 协议使用 8 位字母数字密码），在浏览器窗口里手动完成验证。

同一登录会话最多保留 10 分钟，认证成功后自动保存并关闭浏览器；取消、到期也会关闭。微博和小红书登录互斥，登录进行时不能启动采集。普通本机版和无桌面的旧服务器版不受影响。

此入口用于登录验证。采集中遇到登录失效或验证时仍按原规则暂停，你回配置页重新登录后手动续跑；不承诺自动通过平台风控，也不自动解验证码。

## 数据保存与迁移

默认使用三个 Docker 命名卷（前缀由 `COMPOSE_PROJECT_NAME` 决定）：

| 卷 | 容器位置 | 内容 |
|---|---|---|
| collected-data | /app/data | Excel、图片、审核标记、识别缓存等 |
| browser-state | /app/browser_data | 登录状态 |
| app-logs | /app/logs | 日志 |

`docker compose --env-file .env.portable -f compose.portable.yaml down` 停止/移除容器但保留卷。**不要加 `-v`**，也不要删除对应卷。改项目名会使用另一组卷，旧数据不会自动出现。服务自动启动，未完成任务需你手动续跑。

升级：保留 `.env.portable` 和项目名，替换源码后 Windows 运行 `启动Docker.cmd -Rebuild`，Linux/macOS 运行 `sh 启动Docker.sh --rebuild`。不要直接拿 Windows 浏览器 profile 替换容器目录，迁移机器后可能需要重新扫码。

备份：先停止采集并执行 compose stop，再用 `docker cp <容器名>:/app/data ./backup/data`，同样复制 browser_data、logs，并单独安全保存 `.env.portable`。容器名可用 compose ps 查看。迁移需复制这三个目录到新容器挂载卷，并核对文件数量、审核记录与 UID/GID 权限；仅复制镜像不包括数据。正式迁移前保留原卷。

## Jev 代理

新镜像在配置页提供“Jev 专用代理”：填写 Clash/Mihomo 订阅，保存并选择节点，
然后用实际 Jev Key 测试。代理配置保存在 data 卷的 jev_proxy 私人目录，
容器重启使用缓存，订阅更新由“刷新节点”按钮触发。此版本不自动定时更新订阅。
实际私人目录为 `/app/data/.jev-proxy`，普通数据文件接口不会列出或下载其中内容。

页面停用表示 Jev 直连；启用后请求固定走容器内部代理，节点故障不回退直连。
新镜像的内置模式优先于旧 `TYPESAFE_PROXY_URL` 和 SSH 中转环境变量。
原来没有内置代理的镜像仍可用这些旧配置。订阅格式及数据保护详见单镜像部署说明。

Qwen 继续直连硅基流动。网页控制台能打开不代表 API 请求成功；请在工作台测试密钥。Docker 不会消除 HTTP 451 地区限制。

## 分发与架构

Dockerfile 面向 `linux/amd64` 与 `linux/arm64`。本机默认构建当前 CPU 对应镜像。多架构发布需要你自己的镜像仓库：

```sh
docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile.portable -t YOUR_REGISTRY/mediacrawler:VERSION --push .
```

没有执行这个命令就不算发布了双架构镜像。Windows 云电脑必须支持 Docker 所需虚拟化；旧 Windows ZIP 能运行不代表 Docker 可用。

离线镜像导出：`docker save -o mediacrawler-20261020-proxy-fix2-amd64.tar mediacrawler-portable:20261020-proxy-fix2`；目标同架构机器执行 `docker load -i mediacrawler-20261020-proxy-fix2-amd64.tar` 后创建容器。采集和 API 仍需联网。

排错：`docker compose --env-file .env.portable -f compose.portable.yaml logs --tail 100`。健康检查覆盖 API、VNC、WebSocket 监听；并不等价于已经扫码或完成实际采集。实际构建及验收范围参见随包验收记录。
