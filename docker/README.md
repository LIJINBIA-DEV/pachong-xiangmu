# Spark Docker 使用说明

2026-10-12 已在 Spark 实际构建 ARM64 镜像并部署，入口为 `http://192.168.30.168:18180/`，服务器目录为 `/home/jc/mediacrawler-spark`。图片识别使用硅基流动 `Qwen/Qwen3.5-4B` API，不使用 Spark GPU。Jev 已通过本机 SSH 中转到达鉴权接口，等待用户在网页填写有效 Jev 密钥。详见 [中转说明](../docs/jev-ssh-relay.md)。

## 文件及服务

- `compose.spark.yaml`：一个工作台容器，包含 FastAPI、构建后的网页及采集进程；只运行一个 API worker。
- `docker/Dockerfile.app`：构建网页，安装锁定的 Python 依赖、uv、Node 和与 Playwright 版本匹配的 Chromium。目标架构为 Linux ARM64。
- `docker/check_runtime.py`：镜像构建时以普通用户检查后台、最新审核导出接口、上海时区及网页资源，再启动 Chromium 渲染本地测试页面；不访问微博或模型 API。
- `.env.spark.example`：运行时配置模板，真实密钥填写在服务器的 `.env.spark`，不加入镜像或版本库。
- `.dockerignore`：排除电脑旧数据、图片、审核状态、缓存、模型、凭据与测试产物。

部署使用独立 Compose 项目 `mediacrawler-spark`，新容器 `mediacrawler-spark-app-1` 设置 2 核 CPU、8GB 内存上限。部署前的 13 个容器 ID、镜像、启动时间及运行状态已逐一核对，全部未改变。详细验收见 [部署记录](../docs/spark-deployment-20261012.md)。

容器使用无头 Chromium，支持网页扫码登录和手填 Cookie，不连接 Windows Chrome。扫码成功后将私有登录状态保存在持久化的 browser_data 目录，网页不返回 Cookie。默认入口绑定 `127.0.0.1:18180`；内网使用时填写 Spark 的内网 IP。容器需要访问微博、TypeSafe 和硅基流动的外网接口。

## 将来部署时的准备

下面是首次安装的可复用步骤。本次已完成安装，不要对现有部署重复执行 `cp .env.spark.example .env.spark`，以免覆盖真实配置。安装时把代码及以上文件放入 Spark 的一个新项目目录，不复制 Windows 的 `data`、`browser_data`、`.env`、`logs`、`artifacts` 和模型目录。保留 Spark 已有服务。

在项目根目录创建配置及空目录：

```sh
cp .env.spark.example .env.spark
chmod 600 .env.spark
mkdir -p docker/runtime/data docker/runtime/browser_data docker/runtime/logs
id -u
id -g
```

用编辑器填写 `.env.spark`：

- `SPARK_BIND_IP`：Spark 内网 IP，例如此前检查时的 `192.168.30.168`，部署时重新确认。不填 `0.0.0.0`。
- `APP_PORT`：默认 `18180`，部署前检查没有被其他服务占用。不要使用已被 RAGFlow 占用的 `18080`。
- `APP_UID`、`APP_GID`：填写拥有上述三个目录的普通用户 UID/GID；默认 `1000`。目录须由该用户创建并可写，避免由 root 自动创建后无法保存文件。
- `APP_CPUS`、`APP_MEMORY_LIMIT`：默认 `2.0` 和 `8g`，仅限制新工作台容器，不调整其他服务。
- `NODE_IMAGE`、`PYTHON_IMAGE`：默认官方基础镜像。本次 Spark 直连 Docker Hub 超时，使用已有的 Daocloud 镜像源，并在服务器配置中固定到拉取的 ARM64 镜像摘要；未修改 Docker 全局镜像源。
- `SILICONFLOW_API_KEY`：填写硅基流动密钥。Linux 无法使用电脑上 DPAPI 加密的密钥，需通过此环境变量提供；不要在网页重复保存密钥。
- `TYPESAFE_API_KEY`：填写 Jev 密钥，或留空后在已有网页配置表单中输入。
- 数据、浏览器和日志目录保持默认即可；它们是 Spark 独立的新目录，不指向电脑旧数据。

校验配置、构建与启动：

```sh
docker compose --env-file .env.spark -f compose.spark.yaml config --quiet
docker compose --env-file .env.spark -f compose.spark.yaml build
docker compose --env-file .env.spark -f compose.spark.yaml up -d
docker compose --env-file .env.spark -f compose.spark.yaml ps
docker compose --env-file .env.spark -f compose.spark.yaml logs --tail 100 app
```

内网浏览器打开 `http://<Spark内网IP>:18180/`。当前工作台没有登录鉴权，仅供受信任内网使用，不配置公网映射。

首次打开会显示使用须知，需要用户自行阅读并确认。硅基流动密钥已在服务器配置中设置；微博登录按当前工作台提供的方式操作。Jev 网络已接通本机中转，仍需你在配置页填写有效 Jev 密钥并检查正式调用。

## 采集、审核及重启

1. 在配置页选择“扫码登录”，点击“开始扫码登录”，用手机微博扫描并确认；也可以选择 Cookie 登录并填写 Cookie。选择 Excel 输出、Jev 文本筛选和图片识别。扫码仅创建登录会话，不自动开始采集。
2. 图片识别固定从环境配置选择硅基流动，沿用当前人物、食物、图片类型及文字卡片判断规则；不确定项交人工审核。模型重识别保留既有人工标记。
3. 明确的 Cookie 失效、登录或验证响应会停止采集并提示，不记作搜索耗尽。已完成数据按现有保存逻辑写入 Excel。普通网络故障仍显示请求失败；不自动认作 Cookie 错误。
4. 登录失效后重新扫码或更新 Cookie，由你手动继续。已有任务可按现有流程完成审核后补采；扫码任务使用服务器保存的登录状态，Cookie 任务在进程重启丢失内存 Cookie 后要求重新填写。识别中断则在人工审核页手动点击识别／重试。
5. Docker 重启后工作台自动启动（需宿主 Docker 已设置开机启动），采集和识别不会擅自开始。显式停止的容器遵循 `unless-stopped`，不会自行启动。

持久化整个 `/app/data`，包括 Excel、图片、人工标记、识别缓存及补采记录；浏览器配置保存在 `/app/browser_data`，日志保存在 `/app/logs`。重建容器不会删除这些宿主目录。不要删除 `docker/runtime`，也不要只保留其中的 Excel。

新增的“审核结果导出”会生成九列 Excel 并通过浏览器下载，保存到打开工作台的电脑所选下载位置；它不额外写入服务器目录，也不覆盖原始采集 Excel。缺失或损坏图片的判断及人工修改仍使用持久化的 data 目录，不需要增加挂载点。

## 代码修改后的更新

Docker 从当前项目源码重新构建，不复用电脑上旧的 `api/webui`；网页会在镜像构建阶段执行 `npm ci` 和 `npm run build`。因此新增后端模块、审核界面和导出功能都会随当前源码进入镜像。

以后部署完成后，更新 Spark 项目目录中的源码及依赖锁文件，等任务结束再执行：

```sh
sh docker/spark-compose.sh up -d --build app
```

该操作重新构建并替换工作台容器，保留已挂载的数据、浏览器状态和日志目录。只执行 `restart` 不会加载尚未构建进镜像的新代码。

需要暂停服务时，等任务结束后执行：

```sh
sh docker/spark-compose.sh stop app
```

容器正常停止会给采集进程清理和保存数据的时间；断电或强制终止仍可能损失尚未写入的数据。修改环境密钥后，要在任务结束时重新创建容器，使新环境变量生效：

```sh
sh docker/spark-compose.sh up -d --force-recreate app
```

## 当前验证边界

已验证 Compose 配置解析、容器默认参数、Cookie 故障分类及补采重新输入 Cookie 的逻辑，前端已构建。Docker 相关行为测试使用模拟响应与临时数据，没有采集真实帖子。

2026-10-12 按最新项目复核：相关 Python 回归 119 项通过，包含新增审核结果导出、下载损坏判断及人工标记保护；前端 26 项通过，前端构建通过。新增构建检查脚本中的后台、时区、网页资源检查已在本机通过，Linux Chromium 实际启动检查须在构建镜像时执行。

上一次全量 Python 回归为 796 项通过、1 项跳过、4 项失败：既有测试依赖 Windows 缺少的 `grep`、不能直接执行的 `.sh`，以及被已有 CMD 会话挡住的启动测试。本轮不重复这些启动测试，不关闭现有 CMD；上述全量数量属于上次验证记录，不代表本次最新全量结果。

本次已在 Spark 完成 ARM64 构建、普通用户启动 Chromium、内网访问、硅基流动合成图片实测、Excel 导出、人工标记写入及三个挂载目录重启保留验证。系统依赖和 uv 下载使用镜像内部的国内源；锁定的 asyncmy 在 ARM64 上需要源码编译，因此镜像包含 build-essential。

中转接入后，Jev 经本机访问已进入鉴权环节，不再返回地区限制；正式 Jev 模型推理等待用户填写密钥。本次中转更新没有代用户发起采集，更新前已有的 42 个 Spark 数据文件内容保持不变，其他 15 个容器未改变。电脑旧数据仍留在电脑。

参考：[Playwright Docker](https://playwright.dev/python/docs/docker)、[浏览器安装与 channel](https://playwright.dev/python/docs/browsers)、[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)。

## 2026-10-12 网页扫码更新

已部署 `mediacrawler-spark-app:qrcode-20261012`。相关 Python 回归 101 项、前端 26 项及构建通过；Spark 无头 Chromium 已打开官方微博登录页，Chrome 工作台能显示二维码。此次更新前的其他 15 个容器均未改变。用户暂缓手机扫码，当前等待已取消，手机确认后的真实登录验证尚未完成。用户可稍后在配置页重新开始扫码。上文“未采集”等表述属于首次部署验收记录，不代表更新后的实时数据状态。
