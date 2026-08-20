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
