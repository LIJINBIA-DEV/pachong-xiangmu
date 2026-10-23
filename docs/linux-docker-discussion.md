# Linux Docker 部署方案

日期：2026-10-12。用户先授权制作文件，随后明确授权部署到 Spark，保留原有服务。图片继续调用 API，不使用 Spark GPU。本次已实际部署，验收结果见 [部署记录](spark-deployment-20261012.md)。

## 已确认范围

- 整套采集、数据管理、日志和人工审核工作台通过 Docker 放在 NVIDIA DGX Spark，仅内网访问。
- 图片识别继续调用硅基流动 `Qwen/Qwen3.5-4B`，不新增本地模型容器、不下载权重、不占用 GPU。
- 文本语义筛选继续调用 Jev API，保留宠物判断、明确拒绝直接排除、不确定交人工的规则。
- 微博支持手动填写 Cookie 和网页扫码登录。失效或需要额外验证时停止采集、保存已完成结果并提示；用户重新扫码或更新 Cookie 后手动继续。
- 工作台服务自动启动，但中断的采集、识别任务由用户手动续跑，不自动抓取。
- Spark 从新任务开始。Windows 旧 Excel、图片、人工审核记录和识别缓存不迁移、不删除、不覆盖。
- Spark 已有 RAGFlow、Ollama、PaddleOCR-VL 保持不动；不抢占它们的端口或调整服务。
- 不更改筛选标准；云端重识别继续保留人工修改的账号、图片及本帖决定。

## 已有代码与本次适配

FastAPI 已能提供 `api/webui` 中构建好的网页及 API。采用一个工作台容器、一个 API worker；镜像包含 uv、Node、锁定的 Python 依赖和 Playwright Chromium。容器模式禁用桌面 CDP，使用无头浏览器和 Cookie，Windows 默认行为保留。

图片 API 密钥由 `SILICONFLOW_API_KEY` 注入，Jev 可用 `TYPESAFE_API_KEY` 或已有网页表单。Windows DPAPI 加密设置不能在 Linux 解密，不复制旧凭据，也不把真实密钥写入镜像。

持久化 Spark 新目录中的完整 `data/`、`browser_data/` 与 `logs/`。完整 data 包括 Excel、图片、人工标记、模型缓存、账号审计与补采记录。扫码登录状态私有保存于 browser_data。容器重启不启动任务；Cookie 模式补采在失去内存 Cookie 后要求重新填写，扫码模式复用有效的保存状态。正常停止容器时通知采集进程清理保存。

明确的 HTTP 登录／验证响应与真正的搜索空结果分开记录。网络或解析失败不应记作搜索耗尽，也不直接认定 Cookie 无效。

## 目标机此前只读快照

讨论阶段曾通过受信任别名 `spark-xiaozhuji` 只读检查，没有安装、停止或调整服务：Ubuntu 24.04.4 / ARM64，GB10；Docker 28.3.3、Compose 2.39.1。内网地址当时为 `192.168.30.168`。`18080` 已被 RAGFlow 占用，`18180` 当时空闲，部署前需重新确认。

准备文件阶段没有再次连接 Spark；授权部署后已重新检查端口及既有服务，确认 18180 空闲后启动独立工作台容器。GPU 配置与本地推理性能不属于当前 API 方案的验证范围。

## 本次交付与限制

新增 `compose.spark.yaml`、`docker/Dockerfile.app`、`.env.spark.example`、`.dockerignore` 与 `docker/README.md`，配套容器模式、Cookie 故障提示、补采凭据重新输入与正常关闭处理。

前期检查 Compose 配置、模拟行为回归和前端构建后，本次已在 Spark 实际构建 ARM64 镜像并启动。普通用户无头 Chromium、内网网页、硅基流动调用、Excel 导出和挂载目录重启保留均已验证；既有容器保持不变。完整操作说明见 [Docker 使用说明](../docker/README.md)。

2026-10-12 在用户修改项目后再次复核：新增九列审核结果 Excel 导出，以及缺失／损坏图片审核处理。依赖清单与挂载位置仍适用；Dockerfile 明确安装 tzdata，并新增构建时后台、导出接口、网页资源及无头 Chromium 启动检查。最新相关 Python 测试 119 项、前端 26 项及前端构建通过。镜像构建仍未执行，没有部署。导出的审核结果由浏览器下载，不新增服务器持久化目录；更新代码后需要重新构建镜像，不能只重启旧容器。

## 实际验收及待处理

1. 已通过：ARM64 镜像构建、Chromium、本地 API、内网网页、九列 Excel 导出和临时人工标记保存。
2. 已通过：硅基流动合成文字卡片识别；云端模型为 Qwen/Qwen3.5-4B，结果为二者都不是、文字／图文设计卡片、建议不合格。
3. 已通过：三个宿主目录在新容器重启后保留；任务仍为空闲；既有 13 个容器未改变。
4. 待处理：Jev 直连返回 HTTP 451 地区不可用。用户明确确认先部署、稍后处理网络。Jev 密钥也需后续在环境或网页配置。
5. 待处理：由用户填写 Cookie 后实测真实微博采集。此次未迁移 Windows 旧数据，未代替用户确认网页使用条款。

参考：[Playwright Docker](https://playwright.dev/python/docs/docker)、[浏览器 channel](https://playwright.dev/python/docs/browsers)、[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)。
