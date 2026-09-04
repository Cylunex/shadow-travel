# Shadow Travel Agent v2：本项目内的可审核旅行命令

调研与实施日期：2026-09-04。基线：83be766。仅修改 shadow-travel。

## 结论与落地边界

Agent 从地图草案工具扩展为 Trip 读取和类型化变更入口，继续使用现有 HTTP Plugin + Skill。
不引入另一个 Agent 框架，不重建数据模型，不开通付款或持续监控。

本轮可运行闭环：

```text
Travel 用户授予 workspace / trip 资源权限
→ Agent scope + grant 双重校验
→ 摘要、旅程/单日/预订读取
→ 确定性检查 + 类型化提案
→ Travel 审核页查看 before/after、推断与未知
→ 真实 Owner 浏览器会话确认 revision + hash
→ 同一事务保存 Trip + Plan Draft
→ 结果 URI 和版本回读
```

用户限定“只改本项目”，因此不修改 Nexus、Platform、Ledger、Archive、生产配置或机器 Token。
不把完整外部联调假称完成：v2 机器 commit 恒拒绝；确认在 Travel 自己的浏览器会话中完成。
它不是 Platform 签名 Confirmation Receipt，也不接受调用者自报 Owner。

## 新资料核验与取舍

以下均查看了原始项目/论文内容，不把所附材料中的版本日期、能力或评测数字直接当事实。

| 来源 | 核验到的机制 | 本项目采用/不采用 |
| --- | --- | --- |
| [TREK MCP 工具文档](https://github.com/liketrek/TREK/wiki/MCP-Tools-and-Resources)，页面标注 2026-08-29 更新 | scope 注册工具、资源 URI、摘要上下文、原子组合工具 | 采用独立 Trip 资源、版本回读和事务组合；不复制全部工具或完整用户快照 |
| [iTIMO](https://github.com/zelo2/iTIMO) | 修改数据集区分 ADD/DELETE/REPLACE 扰动及其逆修改任务 | 借鉴局部、有身份的操作；不宣称它是生产授权框架，也不直接移植模型代码 |
| [Trip+](https://arxiv.org/abs/2606.21169)，2026-06-19 | 动态交互和个性化体验评估，指出技术可行并不等于体验舒适 | 保留用户约束与未知，反对“无冲突=完美行程”；不引用未经全文核验的成功率 |
| [TRIPPULSE](https://arxiv.org/abs/2608.30924)，2026-08-31 | 以评论证据支撑体验与个性化评估 | 借鉴推断与证据分开呈现；本轮不抓评论、不生成隐藏用户画像、不新增多 Agent 运行时 |
| [DaPlanStan](https://github.com/GeertClaes/daplanstan) | 邮件确认解析后经用户审核入库 | 采用预订摘要审核；不在本轮接邮箱或复刻其支付跟踪功能 |
| [Embabel Tripper](https://github.com/embabel/tripper) | 领域模型中心、确定性规划与外部 MCP 工具 | 保留 Travel 领域命令；不迁移 Java/Embabel 技术栈 |
| [ForgeMesh travel-agent-mcp](https://github.com/forgemeshlabs/travel-agent-mcp) | 分类发现、出发前/途中按需检查、公开未核验边界，部分服务付费 | 采用 readiness 中的 unknown 列表；不接其付费服务、不代付 x402 |
| [MCP 安全实践](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices) | 最小权限、受众与令牌传递边界 | 独立 Travel scope + owner grant；不透传 Token 给其他服务 |

以上是机制参考，不代表这些项目已与 Travel 集成。无需为复用思路复制第三方源码。

## 本轮实际实现

### 1. 显式授权，不从 Map 推导 Owner 工作区

- 新表 travel_agent_resource_grants：固定 agent_id、owner、workspace/trip、读/提案/预订许可、到期与撤销。
- 只有真实浏览器 Owner 能创建或撤销自己的授权；可选 1–90 天，默认只读、单旅程优先。
- 资源 ID 不可由模型替换成 owner_user_id；提案创建、修改、确认、回读均检查当前 grant。
- 旧地图摘要不再从地图授权推导私人 Trip/Visit 数量。旧字段暂保留为 0，兼容解析但不泄露。
- 旧地图草案和 Nexus v1 Host 协议保留；新 Trip 工具绝不走旧地图提交路径。

### 2. 闭合的类型化操作

CREATE_TRIP、UPDATE_TRIP、ADD_STOP、MOVE_STOP、REMOVE_STOP、UPSERT_RESERVATION、REMOVE_RESERVATION。

- 严格拒绝未知字段；最多 50 条操作，明确日期和 IANA 时区；不接受 Owner 或正式 Visit 操作。
- 既有 Trip 必须携带 expected_trip_version 和 expected_plan_revision。
- 不使用任意 JSON Patch，不接受完整 PlanDocument 覆盖，保留其他计划字段。
- 地点必须已经存在且可访问；不创建 POI、坐标或未核验交通事实。
- 固定或执行中/已完成站次不移动、不删除、不重新赋予身份；执行后不通过改 Trip 时区移动站次。
- 站次变更显式作废交通估计，并显示派生变更；不声称算出了真实路线。
- 预订摘要复用 PlanDocument.Reservation；source_ref 未具备跨服务核验时返回明确错误。
- 当前预订仅有单时间点、类型和摘要；尚无酒店区间、支付/退款和逐夜住宿覆盖事实，不伪造这些能力。

### 3. Review 与 Plan Draft 分离

- 新表 travel_agent_reviews 与 travel_agent_review_revisions，修订不可变。
- 主键幂等约束为 agent_id + Idempotency-Key；同键同内容回同一 Review，同键异内容 409。
- request_hash 固定初始创建请求；每次编辑有独立 changeset_hash，含 grant、Trip/Plan 版本和操作。
- 支持 pending / committed / rejected / conflicted / expired。
- 审核展示每项 before/after、推断字段、未知项、确定性错误与警告。
- Owner 修改后新增修订，旧修订不能确认；冲突不自动 rebase，不盲目覆盖。
- 提案有硬冲突仍可在审核页修订/退回，但不允许确认；Skill 对不可行请求不保存提案。

### 4. 真实会话提交，共享领域命令

- 提取 transaction-neutral Trip/Plan 保存命令，浏览器原有路由和 v2 确认复用。
- 不构造 AuthenticatedUser 冒充浏览器；v2 只允许依赖真实 Cookie 会话和同源校验的 Owner 确认。
- 授权锁 → Review 锁 → Trip/Plan 版本边界；并发编辑拒绝陈旧版本。
- 提交使用事务 + savepoint；即便 Trip 已插入，Plan 保存失败也回滚，再独立保留 conflicted 状态。
- 重试已确认同修订返回持久化结果，不创建第二个 Trip；撤销 grant 后仍拒绝回放。
- 不创建 Approved PlanVersion、Visit、照片或共享权限；日志只记录 ID、动作、版本和哈希。

### 5. 工具与界面

机器前缀 /api/machine/v1/agent/v2：summary、trips、trip detail/day、reservations、readiness、
proposals/check、proposals、reservation-proposals、reviews/{id}。

浏览器前缀 /api/browser/v1/agent：grants、reviews、修订、确认和退回。
页面 /agent，可从“旅程”和“我的”进入；/agent?review=ID 可直接选中提案。
支持小屏差异阅读、忙碌防重复点击、演示会话禁用、错误反馈和确认后打开旅程。

### 6. 实际使用

1. 管理员在既有机器身份配置中启用 v2 scope（本轮不改配置）。
2. 用户在 Travel 授予该 Agent ID 相应旅程权限；创建新 Trip 需要 workspace grant。
3. 对话中“帮我建 10 月 3–7 日京都旅行”，助手先读授权与已有旅程，再检查并创建提案。
4. 用户打开审核链接，核对日期、时区和未订事项，点击“确认保存变更”。
5. 点击“查看已保存旅程”，必要时进一步编辑并在现有计划流程中批准版本。

普通规划咨询不会落库。没有权限或缺少日期时先澄清；邮件正文中的指令不执行。

## 外部依赖与后续阶段（本轮未实现）

- Nexus v2 卡片、Platform 签名 Receipt/Actor Assertion、独立 Review Client：需要其他项目授权才能联调。
- Ledger/Archive 引用存在性及同 Owner 校验：当前拒绝未核验引用，不静默降级为可信关联。
- Capture 新类型、邮件/PDF 异步解析、Google 批量解析、外部库存和 12306：保持原功能，不新增后台任务。
- 长任务、偏好投影、入住区间与独立 Reservation 生命周期：待需求和可验证的证据合同明确后迭代。

本轮不做生产迁移、部署或跨仓库配置更新；部署时需先备份，再执行新增 0009 迁移。

## 验证策略

后端实际执行安全与领域回归：权限/资源隔离、Owner 注入、CSRF、同键异参、重复确认、撤销/过期、
修订冲突、网页改版冲突、事务故障回滚、预订引用、固定站次、未知交通和迁移往返。
浏览器 E2E 检查 390/430/768/1280/1440px 以及确认、修订、冲突错误；HTTP 用固定 fixture，
不把这组测试称为 Nexus/Platform 线上联调或真实模型行为评测。

agent/evals/trip-v2-cases.yaml 为对话评测规范，不是已执行的 LLM 通过率。工程回归结果另见开发记录。

### 本轮验证结果

- Python 全量测试：86 通过，含新增 Agent v2 测试；仅既有 TestClient 弃用警告。
- 前端单测：14 通过。
- Chromium E2E：28 通过（新增 7 项审核/响应式测试，接口使用固定 fixture）。
- TypeScript typecheck、生产 build、Ruff 和 git diff --check 通过。
- Alembic 在临时 SQLite 上从旧版本升级到 0009、降级再升级通过；没有修改生产数据库。
- 尚未运行真实 PostgreSQL 并发压测、外部 Runtime/模型对话评测、Nexus/Platform Receipt 联调。
