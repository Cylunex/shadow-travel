# Shadow Travel

Shadow Travel 是个人地点、到访和旅行记忆中心。它既管理去过哪里，也管理为什么收藏、如何组织
主题地图以及一次旅行如何被长期回顾。

## 理念

- Place 是稳定地点身份，Visit 是实际发生的到访事实；
- 主题地图负责组织和策划，不复制地点或到访数据；
- 地图展示、路线建议和模型结果都不能改写用户原始记录；
- 与 Ledger、Health、Asset 通过引用协作，各自保留领域边界。

## 主要功能

- 全局地点库、到访记录和个人地图；
- 主题地图、点位状态、路线与展示模式；
- 地点详情、照片、记录和自定义字段；
- 高德/Google 地图适配；
- OIDC、成员协作、只读分享和机器同步；
- Platform Asset、LLM 和 Agent 集成接口。
- 离线安全 Trip/Visit、可验证 Trip Bundle、隐私分层与隔离恢复证据。
- 地点收集箱：来源与原因、逐条核实、独立收藏，再归入主题；
- 多日旅程：候选池、固定锚点、预约摘要、准备事项、同行权限、版本化确认；
- 旅途中模式：下一站、外部导航、私密到访、7 天有效的本地旅行副本；
- 私密片段与旅行故事、已有照片引用、GPX 预览/导入/导出；
- 就近排序草案、时间冲突检查与 ICS 导出，不自动生成到访或正式计划。
- Agent 旅程授权、类型化变更提案和逐项差异审核；由真实登录用户确认后保存计划草稿。

地图界面始终使用高德日间底图。底图下载、原生后台轨迹、票据 OCR 和跨应用资料授权
不包含在当前本地副本能力内，界面按真实可用性展示。

## 本地开发

```bash
uv sync --extra dev
uv run alembic upgrade head

cd web
npm install
npm run dev
```

实际数据库、OIDC、地图和 Platform 凭据只通过被忽略的本地配置提供。

## 文档

- [产品需求](docs/product-requirements.md)
- [架构](docs/architecture.md)
- [后端 API](docs/backend-api.md)
- [开发说明](docs/development.md)
- [Shadow App 接入](docs/shadowapp-integration.md)
- [离线写入、隐私与 Trip Bundle 恢复](docs/offline-portability.md)
- [优化方案](docs/optimization-plan-2026-09.md)
- [本轮实现与验收边界](docs/lifecycle-implementation.md)
- [Agent v2 调研、改造与集成边界](docs/agent-v2-plan-2026-09-04.md)
- [Agent Plugin 接入](docs/agent-plugin.md)
