# Shadow Travel vNext：Google 国际地图与可信旅途执行

研究日期：2026-09-04。代码基线：`main@ecb5829`。

状态：**改造建议，尚未实施**。本次只核对代码、阅读两份用户材料和检索外部资料，未修改业务代码、调用付费地图服务或核验生产部署。本文承接而不覆盖 [上一轮方案](optimization-plan-2026-09.md) 和 [已实现清单](lifecycle-implementation.md)。

## 1. 结论与本轮决策

下一版不再重建“收集—地点—旅程—回忆”页面，而是把已有闭环做得能放心使用：

> 国内使用高德，国外使用 Google Maps；计划围绕具体站次组织，旅途中围绕每位成员的实际执行组织，外部地点与路线信息始终带来源、时效和使用权限。

建议确定以下决策：

1. **国外地图主线明确选 Google**：地图、地点搜索、地点详情、道路/公交路线与外部导航配套落地。MapLibre/OSM 不再作为本轮海外替代方案。
2. **先修正确性，再加智能**：同一酒店多次出现、同行各自完成、跨时区、交通方向、旧版迁移是首批验收，而不是末尾补测试。
3. **PlanStop / PlanSegment / MemberStopOutcome 分开**：在哪里、如何到下一站、谁实际完成了，不能共用 Place 状态。
4. **外部资料不是永久自有数据**：来源引用、短期展示内容与用户自己的笔记分开；“用户点过确认”不自动解除 Google 数据限制。
5. **先提供逐段路线核验，后做矩阵优化**：一次检查当天相邻站次，避免每次拖动都请求全量 N×N 矩阵。
6. **Today 是旅途中入口**：下一站、何时出发、相关票据、未核验事项、离线状态放在同一个操作面，不增加全能 Dashboard。
7. **AI 是可关闭的建议工具**：提取、解释、比较、局部修改建议；不代写正式计划、个人完成情况或真实到访。

保留 Travel 蓝 `#159DE5`、轻量 React/PWA、现有领域边界和日间地图。应用面板可以暗色，地图不跟随暗夜模式。

## 2. 对两份材料的修订：哪些已完成，哪些仍然存在

以下是代码检查，不是根据旧文档推断。上一轮测试成绩仅见实现清单，本次未重跑，也不把它当生产验收。

| 议题 | 当前事实 | 本轮处理 |
| --- | --- | --- |
| 离线队列丢尾、账号隔离、SW 清其他应用缓存 | 上一轮已改，见 `offline.ts`、`sw.js` 及单测 | 保留回归；扩展到新的运行时命令，不重复立项修同一批问题 |
| Capture、Trip、版本、Pack、Memory、GPX | 已有第一轮实现 | 继续完善真实流程，不重新搭 Demo |
| Google 接入 | 前端 Google 外跳返回 `undefined`；后端搜索/编码/路线主动 unavailable；后端单点外跳已经实现 | 不是仅配置 Key，也不是所有代码都从零开始 |
| 区域选择 | 前端 `mapProviderForCountry`、后端 `selector.py` 将缺失国家归 CN；Place 表也有 CN/GCJ02 默认值 | 同时修 DTO、表默认、导入、选择器，不能只改一个函数 |
| 下一站 | `TripPage.tsx` 把本 Trip 的 Visit 按 `placeId` 聚合，然后排除所有相同 Place 的 Stop | 首要正确性缺陷；重复站次、跨天酒店都可能受影响 |
| 重排锁定 | `planning.py` 也是按当天已到访 Place 锁定 Stop | 必须和运行时一起改，不能只修界面 |
| 交通时间 | v1 `travel_minutes` 挂在 Stop；检查器把它加在该 Stop 停留时间之后 | 迁移时按“离开这一站到后续站”理解，歧义处不能静默改成入站时间 |
| 页面维护 | `TripPage.tsx` 当前 1150 行 | 先提取纯逻辑、数据 hooks 和子面板，再引入新能力 |
| 长期地点存储 | `TravelPlace` 的名称、国家和坐标必填，provider 单来源 | Google 的内容过期后仍要保留收藏身份，现有结构需要渐进兼容 |

代码入口：[前端 Provider](../web/src/map/provider.ts)、[Google 后端](../server/src/shadow_travel/integrations/maps/google.py)、[区域选择](../server/src/shadow_travel/integrations/maps/selector.py)、[TripPage](../web/src/features/TripPage.tsx)、[规划服务](../server/src/shadow_travel/api/planning.py)、[模型](../server/src/shadow_travel/infrastructure/models.py)。

## 3. 本轮值得借鉴的项目：更看机制和近期修复

“新增”指相对用户本轮两份材料新增或明显更新的参考。不使用 Star 数证明质量，不把 README 声明当作经过实测的产品保证。

| 项目 / 本次依据 | 借鉴到 Shadow 的机制 | 不照搬的部分 |
| --- | --- | --- |
| **TREK v4.2.0，2026-09-03**〔近期更新〕 | 发布记录修复了酒店锚点、按天路线/天气及预订关联问题；直接转成跨城、首尾酒店、一天多张票据的回归用例 | 不扩展聊天、请假、印刷工作室；其地图下载实现不代表 Google 允许同样下载。[发布记录](https://github.com/liketrek/TREK/releases/tag/v4.2.0) |
| **Pappus Travel Planner**〔复核〕 | 地点与交通 Leg 独立、备选安排、计划/实际时间对照、单文件可移植 | 只学模型和迁移体验，不把现有 PostgreSQL 换成 Flutter/SQLite，不将照片原件塞进 Travel。[官方仓库](https://github.com/Calyptra-Software/PappusTravelPlanner) |
| **vis.gl/react-google-maps v1.9.0**〔新增〕 | 2026-07 发布页包含 Advanced Marker 键盘事件、loader 竞态与损坏地图实例重挂载修复；可作 React 生命周期验收参考 | 不为了 3D 示例采用 alpha API。本轮优先沿用现有适配器风格，用官方 loader 薄封装；确有维护收益才加 wrapper。[版本页](https://github.com/visgl/react-google-maps/releases/tag/v1.9.0) |
| **TravStats**〔新增〕 | 用户带入登机牌、邮件或文件再辅助解析；手工输入始终可用 | 不照搬其小家庭账号模型、统计成就或自动合并策略；票据解析不等于航班实时状态。[官方仓库](https://github.com/Abrechen2/TravStats) |
| **GeoPulse**〔复核〕 | 位置时间线、轨迹检测、照片服务接入可作为 TrackAdapter 的参照 | 自动检测只能给 Shadow 提供推断候选，不能替用户创建 Visit。[官方仓库](https://github.com/tess1o/geopulse) |
| **Colota**〔复核〕 | Android 离线采集、标准格式导出、向自托管后端上报 | 作为后续外部输入；不把原生后台能力承诺给 PWA。[官方仓库](https://github.com/dietrichmax/colota) |

这些是参考对象，不是待安装服务列表。复制实现前必须对具体版本核对许可证；例如 Pappus 标为 GPL-3.0-or-later，Colota 标为 AGPL-3.0，不能当作无条件可粘贴代码。

## 4. 近期文章、研究与官方方案

| 来源与时间 | 可信边界 | 本项目的行动 |
| --- | --- | --- |
| **AlterAtlas，2026-07-18** | 研究原型通过 persona 模拟帮助比较修订；不是现实可行性的保证 | 增加节奏/休息/同行限制编辑和改动解释，不引入不可验证的“疲劳精确分数”。[论文](https://arxiv.org/abs/2607.16565) |
| **Trip+，2026-06-19** | 同时考虑交互、个性化和环境变化，体验评估含 LLM 模拟器 | 采用“中途变化”的测试任务；主观模拟不能替代硬约束测试。[论文](https://arxiv.org/abs/2606.21169) |
| **TREK benchmark，2026-08-10 v2**〔新增〕 | 与自托管 TREK 应用不是同一个项目；合成知识库、确定性规则评测，含不可行样例 | 为 Shadow 建立可行/无解/缺数据三类固定案例，不以模型自评通过率作为验收。[论文](https://arxiv.org/abs/2607.26977v2) |
| **MobilityBench，2026-02-26 首发** | 用确定性 API 回放减少实时服务变化带来的评测偏差 | 同一套 Google/高德契约夹具跑排序、核验、失败降级；真实服务只做有限 smoke。[论文](https://arxiv.org/abs/2602.22638) |
| **Keyhive，2024–2026，笔记更新到 2026-07**〔新增〕 | 研究本地优先的并发授权与加密同步，不是现有系统可即插即用的替代品 | 学习“有本地副本≠仍有同步权限”；保持现有 CAS/Outbox，不在本轮改成 CRDT 或承诺 E2EE。[项目](https://www.inkandswitch.com/project/keyhive/)、[笔记](https://www.inkandswitch.com/keyhive/notebook/) |
| **Google Maps Grounding 路由更新，2026-08-20**〔新增〕 | 官方文章宣布其 Agent Platform 集成的新路由能力 GA；不代表全部 Maps Tools 都已 GA | 语义沿途发现可后续试验；基础路径仍使用结构化 Places/Routes API，不绑定某个模型或 Agent 平台。[官方文章](https://mapsplatform.google.com/resources/blog/introducing-new-routing-features-in-grounding-with-google-maps/) |

研究启发与工程结论须分开：本文后续的数据结构、阈值、排期和 UX 是针对 Shadow 的设计建议，不是上述作者的原方案，也不是论文已经证明的生产可靠性。

## 5. 国外 Google：完整接入，而非备用占位

### 5.1 区域与能力路由

采用 `RegionContext { country_code?, subdivision?, service_region, source, confidence }`。地图服务区域是技术路由配置，不靠语言、账号所在地、IP 或模糊地址缩写推断。

| 当前操作位置 | 底图 / POI / 路线 | 失败时 |
| --- | --- | --- |
| 中国大陆服务区域 | 现有高德组合 | 显示具体不可用项，保留本地资料和手工安排 |
| 国外目的地 | Google Maps JS / Places API (New) / Routes API | 联网重试、仅列表、手工输入和可用的 Google 外跳；不悄悄换 OSM |
| 港澳台等需单独配置的服务区域 | 按覆盖表明确配置并实测，不能用简单的 CN/非 CN 二分替代 | 说明区域能力，不错误宣称交通方式一定支持 |
| 未知位置 | 询问目的地或让用户选择搜索区域 | 不自动写 CN，不初始化假坐标 |
| 混合行程 | 跟随当前 Day/Stop/Segment；同一天跨境时按局部段落切换 | 总览分区域显示，不把跨境航班画成驾车路线 |

不强制一趟 Trip 只有一个 Provider。全球地点页对不同来源分组，受限制的 Google 内容不能无条件叠到高德底图。

### 5.2 接口拆分到够用为止

保留 `MapSurface` 门面和旧接口兼容，内部逐步区分：

```text
MapSurface → AMapSurface / GoogleMapSurface
PlaceService → 搜索、详情、选点解析
RouteService → 相邻段核验、候选矩阵
Navigator → 高德 URI / Google Maps URLs
ProviderPolicy → 展示、缓存、导出、AI 输入边界
WeatherService → 后续的有界天气提示
```

这是模块化单体内的协议，不拆成六个微服务。能力状态至少为 `ready / not_configured / unsupported_region / quota_limited / temporarily_unavailable`，失败不能返回空成功。

### 5.3 Google 地图与搜索

- 仅在进入海外 Surface 时动态加载 `maps`、`marker`；组件卸载清理监听和 Marker，过滤变化不重建地图。官方支持按需 `importLibrary`。[加载指南](https://developers.google.com/maps/documentation/javascript/load-maps-js-api)
- 使用 Advanced Markers、聚合、选中描边和路线序号；**生产配置 Map ID**，不用示例 Map ID 顶替生产配置。[Advanced Markers](https://developers.google.com/maps/documentation/javascript/advanced-markers/start)
- 固定日间 roadmap；地图实例、SDK 加载失败、无 Key、区域不支持分别有清楚提示。Bottom Sheet 与导航不能遮住归因、控制按钮。
- 搜索接 Places API (New)：Autocomplete 或用户明确提交的 Text Search；选择候选后按需请求 Details。按交互生成 session token，Details 完结后重置，不跨用户/搜索复用。[Session tokens](https://developers.google.com/maps/documentation/places/web-service/using-session-tokens)
- 字段掩码只取当前 UI 所需字段，不使用 `*`；首轮不引入评论、照片和 AI summary。字段选择必须与 SKU 用量记录对齐。
- 国家/城市与搜索区域明确展示。原文名称、用户别名和界面语言分别处理，不能用译名覆盖身份。
- 确认候选只建立 PlaceSource 和用户收藏关系；服务端使用候选 token/重新核验，不能相信客户端自报的“Google 已验证”。

### 5.4 外跳、链接收集与新 API

Google Maps URLs 无需 API Key，可先补齐单点和下一段导航。用 Place ID 提高定位准确性；完整当天路线仅在 URL 长度、waypoint 和交通方式允许时提供，否则明确为“打开下一段”，不截断后伪称全路线。[Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)

新增 `POST /captures/resolve`：逐项返回 `resolved / ambiguous / unsupported / failed`。优先解析受支持的地点链接；不把列表、路线和短链接一律识别为单个 Place。

Maps Tools Resolution API 当前明确标为 **experimental**，可把受支持的 Google Maps 地点链接解析为 Place ID，单批上限 20。放在 feature flag 后，失败保留原始 Capture 并回到搜索确认，不成为主路径依赖。[官方文档](https://developers.google.com/maps/ai/grounding-lite/resolution-api)

不抓取 Google Maps 页面来绕过 API。其他 URL 抓取/OCR 后续进入隔离任务：只允许指定协议/域名、逐跳检查重定向及解析地址、禁止内网目标、限制大小/时间；网页文字只作为材料，不能成为工具执行指令。

## 6. 最重要的架构修订：来源、内容许可与时效不是一个字段

### 6.1 三层数据

1. **Place / UserPlaceContent**：内部稳定 ID、收藏关系、用户自己写的别名/备注、授权来源的自有观测。
2. **PlaceSource**：provider、provider_place_id、来源链接、解析状态、首次/最近核验时间；同一 Place 可以有多个来源，但不同来源不自动合并。
3. **ProviderContent**：外部名称、地址、坐标、营业时间等展示内容；由明确策略决定是否可保存、保存多久、如何归因。

Place 的长期身份不能依赖“Google 名称和坐标永久非空”。新 DTO 允许 `location_unavailable` 和来源待刷新；列表仍显示用户别名或明确的未解析收藏。现有手工/高德数据不删除，不将未知位置填成 `(0,0)`。

政策核验基于当前 Google 标准文档；实际适用条款还取决于账单地区和具体合同，发布前需确认，不把本文视为法律意见。

### 6.2 默认拒绝不明确的持久化

Google Places 内容受存储限制，Place ID 有明确例外；普通 POI 选择确认不能套用“用户自行提供街道地址”的狭窄例外。展示 Google Places 内容时须遵守地图搭配及归因要求。[Places 政策](https://developers.google.com/maps/documentation/places/web-service/policies)

不能对所有产品统一设“缓存 30 天”或“Pack 7 天所以合法”。当前服务条款对 Places 经纬度、Routes 经纬度和不同 Weather 字段有不同许可；这些例外不等于整个响应可缓存。当前条款还给 Places UI Kit 单列规则，不能反向当成任意 Places REST 内容可叠加高德的授权。[Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)

建议策略模型：

```text
ContentPolicy(provider, product, field_group, contract_region, policy_version)
  → persist_allowed, storage_expires_at, allowed_surfaces,
    offline_allowed, export_allowed, ai_use_allowed, attribution

EvidenceRef(subject, request_context, observed_at, fresh_until, policy_ref)
  → status: available / stale / unavailable / expired_redacted
```

设计规则：

- `fresh_until` 是业务上多久值得相信；`storage_expires_at` 是内容最迟何时必须清理。两者独立，前者不能延长后者。
- 没有核实权限的字段默认只在当前会话展示，不写通用 JSON 快照、日志、PlanVersion 或离线包。
- 业务版本只永久存用户安排、来源引用和经允许保留的信息，不嵌入整套 Google 响应；过期后允许出现“当时核验内容已清理”。
- 清理覆盖服务端缓存、前端持久存储、导出投影和备份策略；新旧客户端都不能重新写回已禁止内容。
- Place ID 失效不删除 Visit。先将来源标为待修复，用户确认是否同一地点；旧 ID 作为身份解析历史，不做自动跨账号合并。Google 建议对超过 12 个月的 ID 刷新，这不等于所有详情也可一年刷新一次。[Place IDs](https://developers.google.com/maps/documentation/places/web-service/place-id)
- 坐标观测记录 CRS、来源和采集/转换方式。GCJ02 原始值不伪称 WGS84；派生值不覆盖原始值，未经许可不能借转换把外部内容变成“自有”。

因此，将材料中的 `ExternalFactSnapshot { payload: 任意JSON }` 改为 **受策略约束的内容缓存＋可长期存在的证据引用**，这是 Google 上线前置项。

## 7. PlanDocument v2：先有站次和交通段，再做求解器

### 7.1 最小模型

| 对象 | 关键字段 / 规则 |
| --- | --- |
| Candidate | `id, place_id, source_capture_id?, priority, note`；长期主题意愿不被 Trip 候选偏好覆盖 |
| PlanStop | `id, place_id, local_date, timezone, time_window?, planned_start?, duration, anchor, reservation_refs[]`；同一 Place 可重复出现 |
| PlanSegment | `id, from_stop_id, to_stop_id, mode, departure_context, estimate, evidence_ref?`；使用站次 ID，不使用 Place 对当唯一键 |
| TransportBooking | `origin, destination, departure_local+zone, arrival_local+zone, status, source_ref`；飞机/跨境火车是独立交通，不伪装道路路线 |
| PlanScenario | 后续只对待执行片段建替代草稿；首版不做任意嵌套分支图 |
| PlanVersion | 不可变用户决策；schema version 与 plan revision 分开；核验资料可能独立过期 |

Stop 的地点事实与 MapPoint 的主题攻略仍分开。一个 Reservation 可关联多个端点，一站可关联多个 Reservation，不做 first-match 查找。

### 7.2 跨时区与日期

- Trip 保留默认时区用于页面初始视图；每个跨区 Stop、交通出发和到达端点保留 IANA 时区。
- 预约输入保存当地时间、时区和明确解析出的 UTC instant；比较重叠使用 instant，不对不同城市的 `HH:mm` 字符串排序。
- 夏令时不存在的时间必须提示，重复时间要求选定 offset/fold；不能只保存固定 `UTC+X`。
- Visit 的日期仍是用户确认的当地日期，不能在旅行结束后因切换界面时区改变。
- “周一 22:00 到周二 02:00”的营业窗口跨日展开；未知、临时关闭、特殊假日都显式表达，不拿本周营业时间保证几个月后的行程。

### 7.3 v1 迁移策略

1. 保留所有既有 v1 确认版本；用只读适配器呈现，不原地重写历史 JSON。
2. 用户首次编辑为 v2 时生成新草稿，保留已有 Stop ID；复制站次必须产生新 ID。
3. 按 v1 检查器现有语义，将 Stop 的交通估计迁往它的出站 Segment，标为 `manual_unverified`；跨日、末站、同刻排序等歧义生成迁移提示，不自动丢字段或猜方向。
4. 旧交通估计不能升级成 Google 核验结果；旧 CN 默认值也不能视为经过核验的国家事实。
5. v2 文档进入后拒绝旧客户端覆盖写入；返回 `client_upgrade_required`，而不是静默丢失新字段。
6. 迁移前做数量/引用校验和可恢复备份；数据库扩展、读适配、写切换、最终约束分开发布，不能靠回滚历史版本删除新数据。

## 8. 真实路线：先核验相邻段，再有界优化

### 8.1 第一层：当天相邻段核验

N 个站次先请求 N−1 个必要交通段；每段带模式、出发时间、地点来源、返回状态。对公交逐段计算，不能用含多个中间站的单次公交请求代替——Google Routes 的 transit 不支持 intermediate waypoints。[Transit Routes](https://developers.google.com/maps/documentation/routes/transit-route)

返回必须区分：

```text
已核验的路线估计 / 用户手工估计 / 资料过期 / 无结果 / 服务失败 / 不支持
```

“本次查询无路线”不等于现实中绝对不可达；只能说明该 Provider/模式/时间条件下的结果。未知值为 null，不为 0；直线仅是明确标注的空间示意。

### 8.2 第二层：选择候选后核验矩阵

Google Matrix 按 origin×destination 元素计算规模；一般非 transit 上限 625，transit 和 `TRAFFIC_AWARE_OPTIMAL` 上限 100，单元素失败要单独处理。[矩阵文档](https://developers.google.com/maps/documentation/routes/compute_route_matrix)

项目首轮建议候选上限 10 个：完整 10×10 为 100 元素，不等于 100 次请求，也不等于一份免费结果。更大候选先地域粗筛，再按能力拆批。使用 `originIndex/destinationIndex` 对齐响应，不能按返回顺序猜配对。

矩阵是候选排序工具，不提供最终路线几何，也不是所有时刻都有效。草案改变出发时间后，要重新核验选中段；不使用早高峰的一份公交矩阵证明整天可行。只对用户明确触发的核验收费，批量重试有总预算和次数上限。

### 8.3 校验结果不是一个绿色勾

- **确定冲突**：预约相撞、日期范围错误、引用丢失、已锁站次被移动；阻止“无冲突确认”。
- **待核验**：无营业资料、路线失败、未来公交未覆盖；允许用户明确确认未核验计划，不能显示“已验证可行”。
- **软建议**：步行偏多、缺少休息、路线折返、同行偏好不均；解释代价，用户决定。

先实现可测试的规则与有界启发式。只有案例证明启发式无法满足明确时间窗和锚点约束时，再引入 OR-Tools 等求解器；LLM 不参与距离计算或硬约束判定。

## 9. Stop 级运行时：还必须带成员维度

用户材料的 `StopOutcome(run_id, stop_id)` 不足以表达“我去了、同行没去”。建议：

```text
TripRun(run_id, trip_id, approved_revision, runtime_revision, state)
RunPlanBinding(run_id, plan_revision, effective_at, adoption_reason)
MemberStopOutcome(run_id, stop_id, member_id, state, revision,
                  actual_started_at?, actual_ended_at?, visibility)
OutcomeVisitLink(outcome_id, visit_id)
RuntimeCommand(owner_id, operation_id, base_outcome_revision,
               plan_revision, payload_hash, result_ref)
```

首版个人状态只需 `pending / in_progress / completed / skipped / deferred`。不通过 GPS 自动写 arrived，也不通过打开 Google 导航判定到达。

完成规则：

1. 下一站只根据当前成员、当前 Run、当前站次计算。酒店 A 的早晨 Stop 完成不影响晚上的 Stop。
2. 完成 Stop 不自动生成 Visit；“标记去过并完成本站”是明确的组合操作，服务端事务创建/复用 Visit 并关联 Outcome。
3. 同一天同地点的旧 Visit 可供用户复用并关联多个 Stop，但必须显示“关联同一条到访”，不能伪称有多个独立到访时刻。
4. 没有时间数据时不从 `created_at` 猜实际到达时间；Visit 可不属于计划，计划外地点可独立记录。
5. 每人只能修改自己的 Outcome/VisitRecord；Trip 编辑权不能代替他人完成。可选择共享完成投影，照片、文字和详细时间仍按单独权限控制。
6. 中途批准新版计划不会自动重置 Run；采用新版需显示站次映射和冲突，保留已执行站次。计划 ID 不可跨版本复用为另一个地点的站次。
7. 纠错用新命令/审计修正个人状态，不删除已存在的 Visit 或改写旧计划；历史事实与当前状态投影分开。

数据库为成员＋站次建立唯一约束，命令幂等与 Outcome 更新使用事务/CAS。不能只在前端用 Set 模拟运行时。

## 10. Today、准备度与途中局部修改

### 10.1 默认旅途中页面

地图保持主体；移动端底部半屏面板集中展示：

- 当前日期与当地时间、自己/同行完成视图切换。
- 下一站、本地名称、用户备注、可用地址、相关预约资料入口。
- 预计出发时刻及依据；过期/未知时改为“请核验交通”，不显示虚假倒计时。
- **开始导航 / 标记去过 / 跳过或延后**；手势不是唯一操作方式。
- 本地未同步条数、最近保存时间、正在查看的确认版本。

“Trip Readiness”用待办清单而不是无法解释的分数：是否确认计划、哪些段未知、哪些资料缺少授权、是否下载本地副本、日期是否超出天气/交通查询范围。

### 10.2 Weather 与 RepairProposal

Weather API 已在 2025-06-30 GA，天气预警在 2025-11-18 GA，不应把网页 2026 更新日期当作它刚发布。[发布记录](https://developers.google.com/maps/documentation/weather/release-notes)

天气绑定当前 Stop 的位置与时间，不取全 Trip 第一座城市。显示 Provider、观测/预报时间、适用窗口及可用范围；提示不是安全保证，不承诺专业户外预警。

RepairProposal 包含 `base_plan_revision + base_runtime_revision + impacted_stop_ids + evidence_refs + assumptions + expires_at + diff`。只调整未执行且未锁定的站次；默认锁住预约和固定交通。批准前重新检查成员权限、版本、锁定项和必要证据。

支持三种清晰选择：换到另一时段、替换为已确认候选、保持原计划并知道风险。采用先生成新草稿，再由用户确认和显式应用到 Run；不因天气刷新静默改计划。

沿途找餐厅/补给点可先用 Places 的 Search Along Route 能力做小范围候选发现，仍要核验额外交通与时间窗，不自动插站。[官方方案](https://developers.google.com/maps/documentation/places/web-service/search-along-route)

Isochrones 可达圈暂列探索项：本次确认有官方功能文档，但所读概览未明确标出发布阶段；不沿用材料中的 Preview 标签当作已核实状态。采用前再查账号可用性、发布阶段、模式限制和成本，不纳入首版验收。[概览](https://developers.google.com/maps/documentation/isochrones/overview)

## 11. 离线：加入执行记录，但不做 Google 离线地图

继续复用当前 IndexedDB、账户隔离、SW 和 Outbox。Google 底图/SDK/API 内容不进入普通 Service Worker 的应用壳缓存；不下载瓦片，不将 7 天本地副本包装成完整离线导航。[Map Tiles 政策](https://developers.google.com/maps/documentation/tile/policies)、[Routes 政策](https://developers.google.com/maps/documentation/routes/policies)

### 11.1 Pack v2

保存已确认的用户计划、个人授权范围内的 Outcome/Visit、用户备注、允许保存的来源引用；每类外部字段独立经过 ProviderPolicy，不能直接序列化完整 `_place_payload`。

Pack manifest 增加 schema version、owner、实例、确认版号、内容范围、创建/过期时间和校验摘要。内容 hash 只说明完整性，不能单独证明包来自可信服务；如需签名，应复用已存在的 Bundle 信任设计，不另造不兼容格式。

离线时显示当天列表和自有资料；缺少许可或已过期的地址/坐标明确提示，不能悄悄带出。Google Maps 外跳也可能需要网络或用户在 Google 自有 App 中另行准备，Travel 不保证它离线可用。

### 11.2 命令队列

扩展 Outbox 为类型化命令，保留当前隔离机制：

- IDB 原子保存“个人操作＋待重放命令”；拿到服务端确认再逐条出队。
- “Visit＋完成本站”在线和重放都走同一幂等事务，避免网络中断只完成一半。
- 命令携带 Run/Plan/Outcome revision。旧版本、成员被撤销、重复 payload 不同分别进入可恢复冲突，禁止最后写入者自动覆盖。
- 权限被撤销后停止共享同步；保留个人待处理数据并允许导出/显式另存，不能通过离线命令恢复共享权限。
- 原始未同步 Visit 不因 Pack 过期清除。退出/清理前展示未同步项；内容过期清理和用户操作保留分开。
- 首版继续只读离线计划＋可写个人执行/到访，不宣称任意多人离线规划自动合并。

`.shadowtrip` 应基于现有 Bundle 扩展“可迁移的用户数据投影”，不要新建第三套真相源。Google 原始响应、评论、照片、未经许可的路线及其他用户私密记录默认排除。

## 12. 票据、照片、轨迹：有用的扩展，但排在主线之后

### 12.1 预约资料

保留手工摘要，增加出发/到达端点、时区、多个附件引用。授权票据先经过 Archive 或隔离解析任务形成 `ReservationDraft`，用户看到原文对应字段后确认。二维码/条码规则解析优先于 OCR，OCR 优先于无法解释的整篇 LLM 猜测；未知类型保持 unknown，不默认酒店。

确认号、证件号和附件权限不跟随 Trip 成员默认共享。来源链接不授予访问权；解析结果只补草稿，不代表已出票或真实航班动态。

### 12.2 照片与 Journey

沿用现有 Asset 引用，跨应用选图以明确授权的日期/位置范围查询；令牌和临时 URL 不进 Pack。Journey 展示计划站次、个人完成、计划外发现、照片与片段；没有实际时间就不绘制精确实际时间轴。

AI 整理文字保留 Visit/Memory/Asset 引用，不从计划补写“我去了”；公开分享应使用可撤销的独立投影，默认隐藏私密坐标、同行身份和票据。

### 12.3 轨迹

现有 GPX → TrackAdapter → TrackSession → DetectedStay 候选 → 用户确认 Visit。保留分段和数据缺口，不将隧道失联画成实际直达路径。GeoPulse/Colota 接口后续按用户主动启用的 Trip 和时间范围接入；原生采集另做授权、后台行为与续航验收。

## 13. 工程组织、成本和隐私

### 13.1 渐进拆分

先将 `TripPage.tsx` 收敛为路由容器，把 `planning / runtime / preparation / members / offline` 作为 features/trips 子模块；提取 `useTripPlan`、`useTripRun`、`useTripEvidence` 和纯 selector。不能只是把 1150 行复制到一个自定义 hook。

后端 `api/planning.py` 只留输入输出和权限入口，核验、计划迁移、运行时命令放 domain/services；Google HTTP 客户端放 integrations/maps。复用既有 `TravelClientMutation` 幂等基础，先核验语义再扩展，不维护两套近似去重逻辑。

生成/校验 API DTO，避免 TS/Pydantic 的 v2 字段手工漂移。Provider 错误、内容许可、空值与 schema 版本进入契约测试。

长期地点分页、视口加载、列表虚拟化和长任务 Worker 仍在待办：本次 Capture 查询有上限，不能把分页缺失当成“用户没有更多数据”。优先把链接解析、票据解析等慢任务做成有进度、可重试、可取消的后台任务；首轮可使用 PostgreSQL 任务表，不无理由引入新消息集群。

### 13.2 Google 配置与费用

- Browser Key 与 Server Key 分开；前者按 referrer 和实际浏览器 API 限制，后者按服务器应用限制和 API allowlist。若 Places 走服务端，不给浏览器 Key 额外开放整套 Web Services。[安全指南](https://developers.google.com/maps/api-security-best-practices)
- 发布前检查 Map ID、API 启用、域名限制、地图可达性、CSP 和公开隐私/使用条款。真实配置只进受保护运维目录，不进仓库。
- 建 `ProviderUsage`：operation/SKU、请求数、矩阵元素数、错误、延迟、重试次数；不保存完整搜索词、精确出行日志、Key 或原始响应。
- 去抖、取消过时请求、地图实例复用、最小字段、批次上限、应用级限流与熔断一起使用。用户每次拖动地图不触发 Places/Routes 查询。
- 不继续沿用“Google 每种 API 都有 1 万次免费”的笼统说法；费用按实际 SKU、字段、地区和当期账单规则核验。本方案先约束调用规模，不承诺固定免费额度。
- 普通预算通知不当硬上限。2026 年已有 **Spend Caps Preview**，但当前官方适用服务列表未列 Maps，不能拿它保证地图账单封顶；仍需 API 配额与应用内门槛。[Spend Caps 文档](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

原始 Google 内容进入外部 LLM 前也必须过 `ai_use_allowed`；不能认为“不拿来训练，只用于推理”就自动不受合同约束。正式启用 Google Grounding 另核验对应产品条款与成本。

## 14. 实施批次与依赖

下表是顺序与退出条件，不是已经完成的任务列表，也不承诺把所有内容塞进一次大提交。

| 批次 | 任务 | 可以独立验收的交付 |
| --- | --- | --- |
| R0 基线防回归 | `REG-01` 固定场景；`MOD-01` Trip 拆分；`OCC-01` 清除 Place 级自动完成推断 | 原流程保持可用；无精确关联时显示待确认，不错误完成重复站次 |
| R1 Google 海外闭环 | `SRC-01` 来源/内容策略与 DTO；`GEO-02` 区域/CRS；`GGL-01` renderer；`GGL-02` Places；`NAV-01` 外跳 | 关闭 LLM 建东京/巴黎 Trip，真实搜索、地图选点、收藏、安排和导航；缺配置可解释 |
| R2 计划与真实交通 | `PLAN-02` v2 读写/迁移；`SEG-01` 独立段；`ROUTE-02` 相邻段；`TIME-02` 时区；`VALID-01` 规则 | 重复酒店、跨时区交通、未知路线、营业待核验能准确表达；旧版本仍可读 |
| R3 个人旅途执行 | `RUN-01` Run/Outcome；`SYNC-02` 原子组合命令；`PACK-02` 策略化离线包 | 两位同行同地点不同状态；离线完成本站后只重放一次；旧计划不污染新站次 |
| R4 变化与可解释优化 | `MATRIX-01` 有界矩阵；`READY-01` 准备度；`WEATHER-01`；`REPAIR-01`；可选链接解析 | 变化只生成局部草案，保留锚点和个人事实，费用/时效/假设可见 |
| R5 经历与跨项目 | `BOOK-02` Archive 草案；`ASSET-02`；`TRACK-02`；`JOURNEY-02`；Bundle 扩展 | 资料、照片、轨迹授权可追溯，实际经历不由计划推导 |

R1 的最低来源/策略设计必须先于 Google 结果长期入库。R2 与 R3 的站次 ID 契约在 R0 先定，避免先做一套临时完成表再推翻。R4 不阻塞基本旅行，实验 API 不阻塞 R1–R3。

建议把 **R0–R3 定为下一次正式版本范围**；R4 作为随后增强，R5 按跨项目授权逐项推进。需要估工时应在 Google 凭据、地区覆盖、政策清单和实际迁移样本确认后再做，不用纸面日期代替这些前置条件。

## 15. 验收与发布门槛

### 必须加入的固定案例

1. 东京三日：关掉 LLM，完整收藏、规划、确认、导航、记录、回忆。
2. 酒店→景点→同一酒店；连续三天同一酒店；一站两份预订。
3. 两个同行，一个完成一个跳过；Trip owner 无法改他人 Outcome/VisitRecord。
4. 北京→东京→巴黎：按区域切地图，飞行不请求驾车路线，同一天跨时区排序正确。
5. 未知国家、同名地点、同楼不同商户、失效 Place ID；禁止坐标相近自动合并。
6. Google 加载失败、Key 受限、429、超时、公交不支持；均不显示假路线或“0 分钟”。
7. 矩阵部分元素失败/乱序、公交时间变化、营业跨午夜、夏令时缺失/重复小时。
8. 旧 v1 计划和离线副本升级；旧客户端拒写 v2；交通方向迁移无静默丢数据。
9. 离线冷启动、组合命令响应丢失、双标签重放、换账号、成员撤权、计划更新冲突。
10. Google 内容到期、只读历史版、Pack、打印/ICS/Bundle 导出都不能绕过数据策略。
11. 暴雨、休馆、约束无解：已完成站次和固定预约不动，允许“没有可行建议”。
12. 390/430/768/1280/1440px，三档 Sheet、键盘、系统字体放大、浅/深面板下地图始终日间；归因不被遮挡。

### 测试分层

- 领域：固定时钟、版本迁移、状态机、校验器、策略判定。
- Provider：合成或明确获准保存的 HTTP fixtures；不能为“回放”永久镜像受限实时响应。
- 后端：真实事务/权限/幂等集成；并发场景要补 PostgreSQL 测试，不只 SQLite。
- 浏览器：现有 Playwright 扩展真实 SW/IDB、版本冲突和移动布局。
- 真人/真实 Provider smoke：使用受限测试 Key，少量已知地点；验证归因、坐标、国际网络、外跳和实际费用，不依赖每天实时结果做 CI 精确断言。

每个批次保留 typecheck/build、前后端测试、迁移检查。UI 显示的“已核验”都必须能回溯到来源、时间、上下文和政策状态。

### 量化目标（项目目标，非已有成绩）

- 固定场景中错误自动完成、越权写入、静默丢队列、静默丢站均为 0。
- 交通段 100% 有质量状态；未知不计入“路线核验覆盖率”。
- 数据导出 100% 经过策略投影；受限字段过期清理有测试。
- 每个海外 Trip 能查看调用规模与失败原因；费用与真实账单对账，不只估算金额。
- 移动地图有效区域、长列表滚动和按钮可达性通过上述尺寸验收；性能阈值在目标手机测基线后确定。

上线顺序：测试环境迁移与恢复演练 → 内部账号启用 Google → 一个真实小行程试用 → 再开放运行时和离线写入。地图、内容缓存、v2 写入、运行时、智能建议各有独立开关；回退关闭新写入但保留已存在数据可读，不能将 v2 静默压回 v1。

## 16. 最终取舍

本轮最值得做的是：**Google 海外闭环＋正确的站次/成员状态＋可追溯交通核验＋可靠离线执行**。

不优先做：再换一套视觉风格、全量地图供应商市场、3D 地球、全平台持续定位、多 Agent 自动旅行、无限分支求解器、完整 OTA/财务系统。用户确有需要时可扩展，但不能让它们先于“同一酒店晚上仍然是下一站”这种基本正确性。

新版本的完成定义不是 API 都有名字，而是：**一次实际海外旅行能用；途中变化不篡改事实；网络失败不丢个人记录；Google 数据的展示、保存和导出都有清楚边界。**
