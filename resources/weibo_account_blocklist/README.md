# 微博账号排除名单

按用户要求，仅导入 pybotfinder 的 `bot.txt`、`media.txt`、`government.txt`。三个文件分别包含 4,994、781、597 个唯一 UID，合并去重为 6,338 个账号（34 次跨名单重复）。没有导入 human 或 influencer 名单。

来源：https://github.com/mengxiao2000/pybotfinder/tree/main/account_list

原始文件保存在 `pybotfinder/`；`manifest.json` 记录固定来源提交、下载时间、各文件 SHA-256、原始 URL 和数量；保留作者 MIT LICENSE。名单是来源项目的历史分类，作为本项目用户指定的排除规则，不代表完整的微博营销号库。

默认启用、仅本地精确查表，不请求在线检测服务、不额外采集账号资料。微博原始作者 UID（idstr/id）在匿名化前匹配；已匿名化的内容/评论按同一 UID 的 creator_hash 匹配，不用昵称匹配，不用帖子 ID 或评论 ID 匹配。

搜索结果命中时立即跳过，不补全正文、不抓评论、不下载图片、不进入语义/图片识别，不占采集目标。指定帖子获取详情后也会跳过；按指定作者采集时，命中的作者 UID 在请求主页资料前跳过。评论作者命中时不保存、不作为语义证据。日志中的原因区分 account_blocklist_bot、account_blocklist_media、account_blocklist_government。

排除名单内容加入语义断点版本，防止使用新增排除规则之前的旧判断缓存。已有 Excel 和人工审核记录不会被主动重写或删除。名单仅在进程内加载一次；以后更新名单需重启相应进程。后续采集进程会自动加载本地名单。

用户追加的精确 UID 排除项保存在 `organizations.json`，使用对应的 `account_blocklist_*` 原因。它们也在搜索、指定作者采集、评论和已匿名化记录中生效，不修改 pybotfinder 的原始快照和校验值。

2026-10-13 新增 `2272985297`（北京科教_健康北京，BTV科教《健康北京》官方微博），按媒体账号黑名单排除。已与存量帖子的作者哈希核对，不使用昵称模糊匹配。
