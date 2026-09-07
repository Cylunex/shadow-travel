# Travel Agent Plugin

> 2026-09-07 设计衔接：统一鉴权、Agent 与 Nexus 目标规范以 [本项目接入设计](nexus-integration-design.md) 为准。不再新增领域自管 OIDC/Session、Agent registry/Grant/审批中心或模型/工具通用循环；普通明确写入采用中央 current_intent。以下相关条目仅描述旧实现/历史阶段，不能作为新增实现继续复制；未迁移接口仍保留当前安全限制。

Travel 拥有地图、地点、Trip、计划、授权和提案数据。Shadow Plugin 声明远程 HTTP 能力，
不包含新的 Harness 或 Agent 框架依赖。只有明确授权的数据才可被机器读取。

## 两条兼容路径

- 旧地图：travel.maps.read / travel.drafts.create，保留 Nexus v1 Host 审核兼容；
- v2 旅程：travel.trips.read / travel.trips.propose，预订另需 travel.reservations.read/propose。
  机器只读与创建类型化提案；真实 Owner 在 Travel 浏览器审核页确认，保存 Trip + Plan Draft。

v2 不接受模型传 Owner，不从地图 grant 自动授权所有 Trip，不自动创建 Visit、Approved
PlanVersion 或付款。机器 commit 返回 owner_browser_confirmation_required。
旧 Host 的写 scope 不能成为新 Trip 的提交途径。

## 本地接入顺序

1. 迁移数据库至 head（新增 0009 grants/reviews/revisions；不升级旧 grant 权限）。
2. 按需在现有机器身份注册表开启 v2 scopes；凭据和真实配置不进入仓库。
3. 导入 shadow-plugin.yaml / agent/manifest.yaml。v1 与 v2 分别使用
   contracts/agent.openapi.yaml 和 contracts/agent-v2.openapi.yaml。
4. Owner 打开 /agent，填写管理员提供的 Agent ID 并授权。
   单 Trip 为默认选择；需要创建新 Trip 时明确授予 workspace。
5. Runtime 按 Skill 摘要先行、检查、创建提案；Idempotency-Key 由 Host 提供。
6. 返回 /agent?review=ID；由用户在 Travel 登录会话中查看差异、修订、确认。
7. travel.reviews.get 回读结果，再按授权读取 Trip/Plan 版本。

尚未修改 Nexus v2 卡片、Platform Receipt 或 Runtime Profile，不能声称旧 Nexus 页面已能
提交新 Trip。跨服务 Ledger/Archive 引用未核验时拒绝，不把 Agent Token 透传给下游。

## 合同与验证

v2 OpenAPI 的请求 schema 从 FastAPI/Pydantic 生成。生成器 scripts/agent_v2_contract.py 只向
stdout 输出，不读取生产配置。协议变化后同步合同、Manifest、Skill 和 Evals；插件合同测试
核对工具 operation_id 与真实路由。

详细调研、领域边界、操作词汇和后续依赖见
[Agent v2 改造方案](agent-v2-plan-2026-09-04.md)。
