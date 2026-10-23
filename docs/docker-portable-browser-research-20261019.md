# 含浏览器 Docker 分发可行性研究

日期：2026-10-19。范围：当前工作区源码及官方资料核查；本次只写研究文档，没有构建镜像、发起采集、修改业务代码或连接任何服务器。仓库已有部署记录仅作历史背景，不作为当前版本已验收的证据。

## 结论

可行，而且当前仓库已经具备“工作台＋采集程序＋Chromium”的容器基础。建议制作通用 Linux 镜像，提供 `linux/amd64` 与 `linux/arm64` 两种构建，通过同一镜像标签分发；使用者安装可运行 Linux 容器的 Docker 后启动。Docker 多架构清单可让客户端选择对应架构，但不能保证任意系统、任意云电脑都能运行。[Docker 多平台构建](https://docs.docker.com/build/building/multi-platform/)

推荐正常情况下沿用现有网页二维码和 Cookie 登录；如希望在验证码等异常情况下也能像本机一样操作，需要增加可选的远程浏览器桌面及“暂停等待人工处理—同会话继续”的流程。仅把浏览器装入镜像不会自动提供人工交互能力。

## 当前仓库已具备什么

以下为本次读取文件得到的事实，未在本次执行其构建或部署：

| 文件 | 当前实现 | 对通用分发的意义 |
|---|---|---|
| [`docker/Dockerfile.app`](../docker/Dockerfile.app) | Node 构建前端；Python 3.11 Debian Bookworm；`uv sync --frozen`；`python -m playwright install --with-deps chromium`；普通用户启动；一个 Uvicorn worker | 已包含浏览器和系统依赖，运行机器无需安装自己的 Chrome、Python、Node |
| [`uv.lock`](../uv.lock) | Playwright 锁定为 1.61.0 | 应由此版本安装配套浏览器，不直接照抄官方文档当前最新版标签 |
| [`compose.server.yaml`](../compose.server.yaml) | 一个 app 服务；`init: true`、`shm_size: 1gb`、2 CPU/4g 内存限制；默认仅绑定 127.0.0.1:18180；三个宿主目录挂载 | 有进程回收、资源限制、数据持久化基础；当前项目名仍为 `mediacrawler-temp-us`，需整理成通用交付模板 |
| [`api/services/weibo_login.py`](../api/services/weibo_login.py)、[`api/services/xhs_login.py`](../api/services/xhs_login.py) | 无头 Chromium 获取官方二维码；网页显示；保存登录状态；检测额外验证并报告 | 普通扫码可以复用，不能视为已有完整远程桌面 |
| [`login_environment.py`](../login_environment.py)、[`config/__init__.py`](../config/__init__.py) | 容器选择服务器模式，拒绝本机桌面模式，默认 headless | 容器不会在访问工作台的电脑上弹出本地窗口 |
| [`docker/check_runtime.py`](../docker/check_runtime.py) | 检查应用/静态资源；启动 Chromium 渲染合成本地页面 | 是构建冒烟检查，不证明实际扫码、Cookie 恢复、验证码和采集成功 |
| [`.dockerignore`](../.dockerignore) | 排除 data、browser_data、模型、环境文件、运行产物等 | 保留不把个人凭据和采集成果打进分发镜像的方向 |
| [`docker/README.md`](../docker/README.md) | 包含旧机器名称、IP、既往验收及部分旧功能描述 | 应另整通用使用说明；不能原样当作这次可移植版验收报告 |

## 哪些机器可以运行

- **Linux x86-64 / ARM64**：作为首要目标，分别原生构建及验收。Playwright 当前官方支持 Debian 12/13、Ubuntu 22.04/24.04/26.04 的 x86-64 与 arm64；这支持所选基础系统的方向，但锁定旧版依赖仍应实测，不把最新文档当作旧版本完整兼容承诺。[Playwright 系统要求](https://playwright.dev/python/docs/intro#system-requirements)
- **Windows 电脑**：使用 Linux 容器，需符合 Docker Desktop 的系统及 WSL2/Hyper-V、硬件虚拟化要求。Windows 云电脑可能没有开放嵌套虚拟化；能运行目前的 Windows ZIP 不等于能运行 Docker。Docker Desktop 不支持 Windows Server 作为安装系统。[Docker Windows 安装要求](https://docs.docker.com/desktop/setup/install/windows-install/)
- **macOS**：使用 Docker Desktop 的 Linux 虚拟化环境，Intel/Apple Silicon 分别匹配镜像架构，并核对支持的 macOS 版本。用户仍在普通浏览器中访问工作台。[Docker Mac 安装要求](https://docs.docker.com/desktop/setup/install/mac-install/)、[Docker Desktop 网络架构](https://docs.docker.com/desktop/features/networking/)
- **其他 CPU、老旧 NAS、没有虚拟化权限的云桌面**：不列入首版承诺。多架构不是单个二进制跨所有系统；模拟运行也可能显著拖慢构建或执行。[Docker 多平台构建](https://docs.docker.com/build/building/multi-platform/)

## 浏览器、扫码与人工验证码

普通模式可以只保留一个 app 容器。二维码由容器浏览器生成，经工作台传给用户手机扫描，用户电脑无需安装采集浏览器。当前代码已经提供这条路径。

增强模式建议在同一 app 镜像中提供可选 Xvfb、VNC 服务端、noVNC/WebSocket 通道，或者后续单独提供桌面版本镜像。Xvfb 为 Linux 有界面浏览器提供虚拟显示；noVNC 是浏览器中的 VNC 客户端，还需要实际 VNC 服务端及 WebSocket 接入，不能只安装 noVNC 文件。[Playwright headed Linux](https://playwright.dev/python/docs/ci#running-headed)、[noVNC 官方仓库](https://github.com/novnc/noVNC)

**当前缺口**：微博服务遇到验证后会退出并在 finally 关闭浏览器；容器模式强制 headless 且不允许本机模式。因此必须新增人工处理状态，让需要操作的同一个浏览器会话保持存活，显示远程桌面，处理完成后再检查登录状态并继续。重新打开另一个浏览器不保证接续原来的挑战。远程桌面入口只对受控网络/经鉴权入口开放，避免任何访客接管已登录账号。这里是拟议设计，尚未实现。

## 镜像运行要点

固定 Playwright 版本和对应浏览器，使用锁文件后执行配套安装即可；若改用官方 Playwright 基础镜像，镜像版本须与项目依赖匹配。保留 init、足够共享内存和普通用户。官方对爬取建议普通用户加适当 seccomp；非 root 不自动等于 Chromium 沙箱已启用，需结合启动参数验收。现有 1GB shm 是项目配置，不是已证明适合所有负载的结论。[Playwright Docker](https://playwright.dev/python/docs/docker)

不建议为方便而默认开启 privileged，也不必把 CDP 调试端口公开。优先维持一个工作台实例、一个采集任务的当前使用模型。若将来拆浏览器容器，要另外处理远程连接版本匹配、会话归属和恢复，当前阶段收益不足。

## 数据和登录状态

保留 `/app/data`、`/app/browser_data`、`/app/logs` 外置挂载。采集图片、Excel、人工标记及缓存留在数据挂载目录，容器升级替换不应删除宿主内容；浏览器登录状态单独保存。挂载权限必须适合容器 UID/GID。绑定目录依赖具体宿主路径，因此分发模板要允许用户设置位置，不能写死原电脑盘符。[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

不要把某个人的 profile 或 Cookie 固化进镜像。相同 `user_data_dir` 不能由两个浏览器实例同时打开；采集与人工桌面应复用同一进程/会话或通过互斥顺序使用，而不是并发争用目录。[Playwright persistent context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)

## 网络与 Jev 代理

Docker 解决软件环境一致性，不保证平台登录和模型 API 的网络地区条件。须从**容器内部**分别测试微博、Jev、硅基流动，而不是用宿主浏览器打开网站替代。仓库 Compose 尚未显式配置 Jev 专用代理。

容器的 `127.0.0.1:7897` 默认指向容器自身，不是宿主 SoCloud。Docker Desktop 可通过 `host.docker.internal` 访问宿主；Linux Engine 可显式加入 `host.docker.internal:host-gateway` 映射。代理还必须监听容器可访问的宿主地址并通过防火墙；仅添加名字映射不会把宿主 loopback 监听变为可访问。[Docker add-host/host-gateway](https://docs.docker.com/reference/cli/docker/container/run/#add-host)、[Docker bridge network](https://docs.docker.com/engine/network/drivers/bridge/)

Docker 拉镜像代理、应用 HTTP 客户端代理和浏览器代理是不同层。运行容器需显式设置可达的代理配置，不能假定宿主“系统代理/TUN 已开启”就一定覆盖容器；应记录容器实际请求是否走预期路径。建议 Jev 专用可选代理，Qwen 继续直连硅基流动，避免把微博也无意切换出口。此为设计建议，仍需核对各客户端实现并实测。[Docker CLI 容器代理](https://docs.docker.com/engine/cli/proxy/)、[Docker Desktop 网络](https://docs.docker.com/desktop/features/networking/)

## 分发方式与资源预算

建议先发布两个原生架构的镜像和通用 Compose，用户只拉取镜像，不在每台机器重新安装 Python/Node 或构建。网络受限环境可再提供对应架构的离线镜像包；这只解决软件分发，采集和模型 API 仍需联网。上述属于交付方案，当前没有生成新镜像。

资源仅作为初次验收预算、**不是实测最低要求**：单采集任务从容器 2 vCPU、4GB 内存开始，人工桌面或重图片页面预留到 8GB；镜像/构建缓存暂预留 10–20GB 磁盘，采集图片空间另算。当前 Compose 的 2 CPU/4g 只表示上限配置，没有性能基准；具体镜像大小需构建后量测。模型走 API 时不配置 GPU。

## 实施前与发布验收清单

1. 通用化项目名、环境变量示例、挂载目录和用户说明；不沿用旧机器 IP/代理地址。
2. 在 Linux amd64、Linux arm64 分别原生构建；确认锁文件、编译依赖、Chromium 实际可运行，并记录镜像尺寸。
3. 从全新挂载目录完成实际网页扫码，手机确认后真正采集少量帖子/图片；保留 Cookie 登录备选。
4. 验证二维码过期、用户取消、网络失败、额外验证码、浏览器异常退出都显示正确原因；若承诺远程操作，必须实测同会话人工处理后继续。
5. 容器重启/替换后核对 Excel、图片、人工标记、配置和登录状态；不自动重开旧采集任务。
6. 分别测试 Jev 直连/代理与硅基流动直连；日志不输出密钥或完整 Cookie。
7. 检查普通用户目录权限、shm 使用、内存峰值、优雅退出和残留进程；检查并发扫码与采集互斥。
8. 在实际 Windows Docker Desktop 电脑验证启动；在云桌面先确认虚拟化权限，不能根据 Windows ZIP 测试替代 Docker 验收。
9. 出包前扫描凭据与个人数据；默认只监听本机或受控内网，公共入口另外设计鉴权。

本次没有完成以上运行验收，只确认已有基础与官方支持路径。主要待做项是通用镜像分发、当前版本双架构验收、代理配置，以及需要时的同会话远程人工登录能力。
