# 本地 SemIf 语义筛选

网页“语义模型”现在可以在 **Jev 1.13 (TypeSafe API)** 和 **SemIf / Qwen3.5-4B Q4 (本地)** 之间选择。选择本地模型无需 TypeSafe API Key；采集进程会在首次需要判断时启动项目内的 `llama-server.exe`，只监听 `127.0.0.1`，结束后关闭。模型与运行程序均在 `models/`，不提交到 Git。

模型文件：`models/semif-qwen3.5-4b-q4/Qwen_Qwen3.5-4B-Q4_K_M.gguf`（3,013,027,808 字节；SHA-256 `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`）。它与 [SemIf 浏览器演示](https://github.com/tseanard/SemIf/blob/master/webgpu-demo/worker.js)所用的固定 Qwen3.5-4B Q4 权重相同，下载自 [ModelScope 镜像](https://modelscope.cn/models/bartowski/Qwen_Qwen3.5-4B-GGUF)。运行程序是 [llama.cpp b11233 的 Windows Vulkan 版](https://github.com/ggml-org/llama.cpp/releases/tag/b11233)。

本地判断读取 A/B/C 三个选项字母的下一 token 概率，不让模型生成长篇回答。`keep` 进入 Matched；`review` 或最高概率低于 0.65 进入 Review；`reject` 不进入筛选结果。概率只在三个选项之间归一化，不能直接当成校准后的正确率。新采集的 Excel 只保留符合和待复核的帖子；同目录的 `semantic_checkpoint_*.jsonl` 保存已判断帖子的原文、一级评论及结论，供中断后续跑。筛选结果另保存在 `_semantic.xlsx`，其 `Summary` 记录模型、判断次数和统计。实际质量需要人工抽样检查。

不启动爬虫即可做四条例句检查：在项目根目录运行 `uv run python -m scripts.check_semif_local`。模型加载或推理出错时查看 `models/runtime/semif-server.log`，采集会停止，不把未判断帖子当作命中。已知限制：搜索接口未返回的帖子仍无法补采；评论无法读取时也不会凭空推断。Jev 默认不再设置固定 100 次调用上限；可用 `MEDIACRAWLER_SEMANTIC_MAX_CALLS` 和 `MEDIACRAWLER_SEMANTIC_MAX_INPUT_TOKENS` 设置预算。Jev API 仍按其费用规则计费；本地 SemIf 没有 API 费用，但会占用本机显存。
