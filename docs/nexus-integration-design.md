# Travel 接入 Nexus 的详细设计

设计版本：2026-09-07 / UA-1。状态：分阶段实现。普通 Trip 创建/更新与预约摘要增删已接入统一命令；中央 Principal/Grant 迁移、完整 Plan/Visit 命令仍按本设计推进。公共身份、鉴权、Agent、模型、命令与回执以 [Platform 统一规范](https://github.com/Cylunex/shadow-platform/blob/main/docs/nexus-unified-access-design.md) 为准；本文仅定义本领域差异。旧接口安全限制在对应能力通过迁移验收前继续生效。

## 1. 实现基线与所有权

基线 `b010886`。旧 `api/machine.py` 可应用旧地图草案；`api/agent_v2.py` 有 Trip/workspace ResourceGrant、类型化提案和浏览器审核，机器 v2 commit 返回 403。新路径以 `application/agent_reviews.py`、`trip_commands.py`、`plan_commands.py` 为底座，不回退旧接口绕过 v2 约束。

Travel 拥有 Place、Map、Visit、Trip、Plan、成员角色、预约资料和旅行实际状态。Platform 管理 user/Agent/workload/Session、Agent 资源委托和确认。地图成员/同行权限、私密到访、固定/执行中站点是业务约束，继续在 Travel 校验，不迁入通用策略数据库。

## 2. 鉴权收敛

`auth/oidc.py`、`auth/store.py` 的 OIDC/Session 管理替换为 Platform SDK；保留旧 user_id 与中央 user_id 的稳定映射。`integrations/agent.py` 不再读本地 registry。机器 API 只接受对应 `travel` instance 的中央 Principal，不能把任意 owner 字段或浏览器代理头当身份。

TravelAgentResourceGrant 的有效 Agent 委托迁入中央：exact trip、地图或明确 workspace + capability + reservation 披露权限 + expiry。原 `allow_propose` 不能直接映射为 execute，workspace grant 不由某个 Trip/map 的 grant 推导。旧 grant 的引用和撤销历史保留，停止中央模式下的本地发放/编辑。

`/agent` 不再要求用户手输 Agent ID 并逐项目授权；领域页面可带 Trip 引用打开统一授权组件。已有个人范围允许的普通命令无需再配置 grant；协作/共享权限变更在原交互点内联确认。

## 3. 命令与读模型

| 操作 | 输入与前置 | 结果 |
| --- | --- | --- |
| `trip.create` | title、日期/时区、owner workspace scope | Trip + Plan draft refs/versions，direct |
| `trip.update` | trip_ref、expected_trip_version、明确字段 | direct；实际旅行状态变化另列语义 |
| `plan.add/move/remove_stop` | trip_ref、expected_plan_revision、stop/place ID、day/order | 新 plan revision；不能移动/删除固定或已执行站点 |
| `plan.candidates.update` | place refs、plan revision | 候选池修改，不生成 Visit |
| `reservation.note.upsert/remove` | 资料 ID、版本、用户给出的摘要/引用 | 仅保存私人计划资料，不调用真实预订服务 |
| `visit.record/correct` | place_ref、发生时间、记录版本 | 仅用户明确到访意图，保留隐私与来源 |
| `trip/context/readiness.read` | trip/day/字段范围 | 有界上下文，预约原文需单独披露许可 |
| `operation.status` | command_id 或领域 receipt ref | 权威状态/实际 Trip/Plan 版本 |

`trip.create/update` 与 `reservation.note.upsert/remove` 已由 `execute_nexus_travel_command` 实现，沿用 `travel.drafts.review` 能力以兼容现有 Host；其余为后续能力拆分。参数保持 Pydantic 类型；复用 `Proposal` 的操作词汇与纯投影检查，移除“必须浏览器确认”作为普通计划保存的前置条件，但不移除领域约束。

## 4. 事务、版本与执行语义

SDK 授权后，领域按原锁顺序读取 Trip/Plan 和相关执行状态，核对中央资源范围、成员权限及 expected versions，再调用 transaction-neutral 保存服务。command ID 唯一结果与 Trip/Plan 版本同事务提交，返回 result_kind=record 或 draft，指明是“计划草稿已更新”。用户只要求改计划时此即完成，不能暗示已发布/已预订。

改站次使 segments/travel_minutes 等交通估计失效；不重复使用旧估计。固定、执行中/已完成站点不能被模型重新编号为另一地点。日期/时区修改影响已执行记录时返回明确冲突，不偷偷重算 Visit 历史。

版本冲突可以读回最新计划并提供最小问题，但不能把旧整份计划直接覆盖新版本。同 command 重试返回同 Receipt；不同操作的版本冲突不靠修改幂等键强行通过。

## 5. 外部引用与隐私

统一命令会把无法跨服务核验的 `source_ref` 保存为 `reference_verification=unverified` 和用户给出的最小摘要；旧提案接口仍拒绝未核验引用。未授权不读取 Ledger/Archive/Asset 内容，未核验信息不变成真实预订事实。阅读资料需中央 Access 分别批准目标域和披露用途；禁止 Token 透传。

Trip 导出/分享只包含用户授权的字段，成员私密 Visit、照片定位和预约个人信息仍由 Travel 按范围投影。普通私人导出与对外分享能力分开，长期共享关系改变使用中央确认，不因存在 export 词一律审核。

## 6. 迁移步骤

1. 中央 Session、用户/资源映射与 read-only context，保留旧 v1/v2 路由但按 capability 固定 auth_mode。
2. 新建普通 command handler、操作结果查询和 Receipt，复用 v2 校验/事务。
3. 切 trip.create/update、plan change；迁入 grant 后停用对应本地 Agent 授权 UI。旧机器 403 对旧接口仍成立。
4. v1 旧草案仅兼容查询/既定执行，不能成为 v2 新命令 fallback；历史 pending 不自动提交。
5. 内联确认只用于真实高影响能力；当前未实现下单/付款/真实取消不开放入口。

## 7. 验收

无授权 Trip/跨 owner/成员降权/到期委托；两个京都旅程只追问目标；修改计划不产生 Visit/预订；固定站点、执行状态、timezone 冲突；双击/丢响应/旧 v1 回退拒绝；预约引用未核验可保存但不可读原文。扩展 `server/tests/test_agent_v2.py`、合同测试及浏览器场景，确保无需跳 Travel 审核页也可安全完成普通计划修改。
