# vNext 实现与发布边界

本次在原有模块化单体、React/TravelContext 和地图门面上实现；未新建 Demo、未更换业务数据库，也未自动推送或部署。设计依据见 [改造方案](vnext-google-runtime-plan-2026-09-04.md)。

## 已落地

| 能力 | 实现与验收边界 |
| --- | --- |
| Plan v2 | 兼容旧计划；显式升级预览；稳定站次 ID；独立 Segment；候选优先级、理由、停留估计与备选分组；逐站/预约时区和 DST 消歧；日历按各自时区导出 |
| 成员执行 | TripRun 绑定不可变确认版本；MemberStopOutcome 按成员＋站次唯一；开始、完成、跳过、稍后、纠错；同行只见主动共享的状态 |
| Visit 原子组合 | 明确勾选才创建 Visit；同地同日提示复用；可关联同一 Visit 至多站；组合操作与幂等回执在同一事务；不推断精确到达时间 |
| 版本与局部修订 | 新确认版不自动替换正在执行的版本；采用时保护已完成/进行中站次；就近排序和时间平移只生成有时效的草稿，显示差异与冲突 |
| 离线执行 | 写前队列保留丢失响应的命令；原账号验证、服务端 owner 防护、版本检查；有冲突不覆盖；导出和显式移除本机操作；旧 Visit 队列保持兼容 |
| Pack v2 | 包含确认计划、用户地点、来源引用、自己的执行/到访；manifest 标明实例、所有者、版本与范围；校验实际 HTTP 内容摘要；不是签名/完整离线导航 |
| Google 海外地图 | Maps JavaScript API + Advanced Markers，固定日间底图，地图选点；Places New 搜索/详情，Google Geocoding，Routes 路线、Matrix、Maps URLs；高德继续承担大陆地图 |
| 来源边界 | Google 收藏仅存 Place ID 与独立填写的别名/城市；不永久保存返回的地址、坐标、照片、评论；坐标缺失用 null，不使用 0,0 或装饰地图 |
| 当前证据 | 用户按需查相邻段路线、当天交通矩阵、本站日期预报；不保存至计划/Pack/AI；失败、未知、过期范围与无路线不能当作零分钟或成功 |
| 准备清单 | 确认版本、冲突、准备事项、资料引用和本机副本逐项展示，不使用不透明的“准备度分数” |

重要实现选择：

- 旧的 `candidates: string[]` 保留，附加 `candidate_metadata`，避免一次迁移破坏所有旧客户端。
- 同日再安排同一地点仍有独立 Stop ID；“已去过”不重新并入个人意愿。
- 地图解析出的临时 Google 坐标只存在页面内存；地图选择回调区分 AMap/Google，避免 WGS-84 误送给高德。
- 一次最多显示/解析 20 个海外地点，更多地点明确提示筛选；选中超出首批的地点会纳入当前批次。
- 相邻路线核验目前是**当前时刻参考**，不是计划未来出发时刻的可行性证明。公交多站须分段。
- Source-only 地点在既有导出中不构造伪坐标，GeoJSON 使用 null geometry。
- 当前 Google 每进程限制 4 个并发、60 次请求/分钟；矩阵单批 2–10 点、最多 100 元素，累计 200 元素/分钟。这不是账户级硬账单上限，生产仍须配置 Google API 配额。

## 本次没有冒充完成的外部能力

以下是设计中的后续/条件性扩展，**本次未实现或未完成生产验收**：

- Google 真实账户联调（本地未提供 Browser Key、Map ID 与 Server Key），域名/API 白名单、账单账户及实际目的地交通覆盖验收。
- 中国大陆以外各特殊服务区域的细粒度覆盖表；当前明确区分大陆/海外，并按服务实际失败降级，不能声称全球所有交通方式可用。
- 自动票据 OCR/Archive 解析、跨应用 Assets 选图、GeoPulse/Colota 持续轨迹连接。现有手工资料引用、照片、GPX 和记忆仍可用；新连接需要明确 API 契约和授权。
- 自动营业时间核验、未来时刻公交可行性证明、天气驱动的智能改线。当前局部修订是透明规则，不是 LLM 或求解器自动决策。
- 服务端地图用量账本、跨进程全局额度、全国/全球超大地点库的视口分页与虚拟列表。
- Google 瓦片离线下载、公开原始 Google 内容、自动替同行完成或修改其私人记录：不提供。

## Google 配置

服务器沿用现有 `TRAVEL_GOOGLE_MAPS_SERVER_KEY_FILE`，指向仓库外受保护的纯文本 Server Key 文件。需要启用并限定实际使用的 Places API (New)、Routes API、Geocoding API；天气入口另需 Weather API。

前端构建时注入：

```text
VITE_GOOGLE_MAPS_BROWSER_KEY=<受网站来源与 Maps JavaScript API 限制的 Browser Key>
VITE_GOOGLE_MAP_ID=<该项目的 JavaScript Map ID>
```

Browser Key 属于可见的前端配置，不能复用 Server Key。真实配置不进仓库。Google 地图与 UI 暗夜主题脱钩，始终使用 LIGHT 底图。缺配置、加载失败或授权失败显示可重试错误，列表仍可用。

发布前按 [Google 安全指南](https://developers.google.com/maps/api-security-best-practices) 和 [JS API CSP 指南](https://developers.google.com/maps/documentation/javascript/content-security-policy) 检查 API 限制、来源、CSP、公开隐私与使用条款；地图真实加载及计费验收不能用模拟接口测试代替。

天气使用 [每日预报接口](https://developers.google.com/maps/documentation/weather/daily-forecast)，仅在服务返回的日期窗口内展示；矩阵按照 [Routes Matrix 契约](https://developers.google.com/maps/documentation/routes/compute_route_matrix) 用索引对齐，缺失单元格保留 unknown。

## 数据库与回滚

- `20260904_0007`：新增 Run 与成员站次结果表；不改写旧 PlanVersion/Visit。
- `20260904_0008`：Place 坐标允许为空，以支持来源引用。
- 正式发布先备份数据库、确认连接目标，再通过既有发布流程运行 `alembic upgrade head`。本轮测试只操作临时数据库，没有改生产库。
- 若已有 source-only 地点，0008 的 downgrade 会拒绝把 null 坐标强制改为非空；必须先做经确认的数据迁移。不能以伪造坐标或删地点完成回滚。

## 验证

本轮最终结果：69 项 Python 测试、10 项前端单测、14 项 Chrome E2E 全部通过；typecheck、build、变更范围 Ruff 检查与 git diff --check 通过。既有 Starlette/httpx 测试弃用警告仍存在，不影响本轮结果。

- Python 全量测试包含站次隐私、幂等、复用、版本锁定、时间平移、DST、Provider 契约、坐标/存储边界与迁移升降级。
- TypeScript typecheck、生产 build、原有离线单测。
- Chrome E2E：390/430/768/1280/1440 宽度、手机 Sheet、旧版离线冷启动、新执行队列、丢响应后相同 operation_id 重放、Google 引用确认、未配置时诚实降级、Plan v2 手机编辑。
- SDK 渲染、真实路线/天气/搜索计费调用仍需在获得配置后做受控生产联调；当前自动化使用可重复回放的 Provider/API 夹具。
