# 本机 Jev 中转

2026-10-12 已接通且在本机后台运行。Spark 经本机访问 Jev 已返回正常的缺少密钥提示（HTTP 403），不再返回直连时的地区限制（HTTP 451）。用户尚未填写 Jev 密钥，因此正式模型推理需在填写后检查，不将网络接通称为密钥或推理已验证。

## 使用

- 本机需保持开机、联网、避免休眠，并维持当前能访问 Jev 的网络／代理。
- 本机中转与 MediaCrawler 项目 CMD 独立。关闭本机采集项目不影响已启动的中转。
- 本机重新开机后，双击 `E:\zdemo\guanjiancicaiji\启动Jev中转.cmd`，或 `MediaCrawler` 目录里的同名脚本。上一级入口自动调用项目内脚本，不需要先切换目录或手输命令。
- CMD 窗口在正常退出、启动失败或发现已有中转时都保持打开，便于查看提示。本窗口启动的中转会随窗口关闭而停止，SSH 子进程也随之停止；重复启动不会抢占端口或创建第二个实例，也不会停止已有中转。
- 启动器先检查 Python 运行环境和 SSH 程序；不保存 Jev API Key，不修改 Spark 现有服务，也不需要管理员权限。
- 停止中转：双击 `停止Jev中转.cmd`；只通知本项目的专用中转会话，不关闭其他 CMD 或服务。
- 现在不用重新启动，本次已经以后台方式启动。
- 在 Spark 工作台配置页填写 Jev API Key，点击密钥连接检查。不要把密钥写进脚本或发到聊天中；本机中转不额外保存 Jev 密钥。

本机日志和状态位于 `.local/jev-relay/`。中转鉴权 token 使用当前 Windows 用户的 DPAPI 加密保存，既不是 Jev API Key，也不进入镜像或源码包。

## 连接方式

Spark Jev 客户端 → 容器只读挂载的 Unix socket → SSH 加密反向通道 → 本机 127.0.0.1:28181 中转 → Jev HTTPS。

Spark socket 位于 `/home/jc/mediacrawler-spark/docker/runtime/jev-relay/jev.sock`。目录权限 0700，socket 0600，用户为 jc；容器 app 同为 UID 1000。中转只允许 Jev `/v1/systemone` 及 jev-1.13.0 模型，校验专用 token，限制请求体大小。不开放本机 LAN 监听或 Spark 公网监听，不更改 SSH GatewayPorts、Windows 防火墙或全局代理。

Qwen 仍使用硅基流动原有 HTTPS 接口。微博采集、Qwen、Jev 中转各自使用自己的连接配置，没有设置全局 HTTP_PROXY／HTTPS_PROXY。

本机 SSH 进程通过已有严格主机校验的 `spark-xiaozhuji` 连接，带有保活与重连。配置中转但 socket 不可用时，请求失败并沿用现有保存／暂停逻辑，不自动退回 Spark 直连或生成假判断。

## Spark 维护

已部署的配置使用基础 Compose 与 `compose.spark-jev-relay.yaml` 覆盖文件，保留原有采集、浏览器和日志目录，额外挂载私有 socket 目录。不要只用基础 Compose 更新，否则会移除中转配置。

建议使用已提供的脚本，它根据服务器配置自动加入中转覆盖文件：

```sh
cd /home/jc/mediacrawler-spark
sh docker/spark-compose.sh ps
sh docker/spark-compose.sh logs --tail 100 app
# 任务结束后更新工作台代码：
sh docker/spark-compose.sh up -d --build app
```

`.env.spark` 中保存运行时中转 token，权限 0600。配置前的备份位于服务器 `deployment/env-before-jev-relay`，同样为 0600；不要下载、输出或提交这些凭据文件。

## 验证结果

- 78 项相关测试通过，覆盖真实 JevReviewer 调用链的模拟响应、鉴权、指定目标、错误状态透传及 Qwen 独立连接。
- 接入中转后，容器再次实际调用硅基流动合成文字卡片成功；Qwen 路径没有使用 Jev 中转。
- Spark 宿主及实际工作台容器，经 SSH 到本机再到 Jev，均返回 HTTP 403 缺少 API Key；说明请求已到达 Jev 鉴权环节。
- 在隔离的容器子进程中，把 socket 改为不存在的路径，实际 Jev SDK 返回 network_error，未退回直连；正常进程的 socket 配置没有改动，中转仍可连通。
- 已重新构建并更新工作台这一容器；其他 15 个容器的镜像、启动时间和运行状态保持不变。
- 更新前已有 42 个数据文件逐个校验，内容没有改变。没有替用户发起采集或设置开机计划任务。
- 实际开关中转／重连及有效 Jev 密钥推理由用户后续使用验证；本次没有通过中断运行中的中转来测试断线。
