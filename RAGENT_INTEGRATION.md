# 考研择校项目采集端

本仓库保存当前本机 MediaCrawler 源码及 Ragent 学校评价适配。Java 主项目单独在 [kaoyan-school-agent](https://github.com/LIJINBIA-DEV/kaoyan-school-agent) 管理；此处保留原项目 LICENSE。

适配代码位于 `api/routers/school_reviews.py` 和 `api/services/school_review*.py`；测试位于 `tests/test_school_review*.py`。支持学校相关文字采集、Jev 筛选、五维画像、阶段进度、持久缓存和预热。Ragent 调用时不下载完整视频。

本机私有配置位于 `.runtime/`；复制 `config/ragent-secrets.example.json` 后在本机填写 Jev 密钥和桥接令牌。`scripts/start_mac.py` 会读取该私有文件并监听本机 18080。前端源码位于 `webui/`，新机器需安装依赖并构建工作台；账号扫码登录由本人完成。

Git 不保存虚拟环境、依赖目录、采集结果、浏览器登录状态、日志和真实密钥。仓库代码不等于数据库和平台登录备份。
