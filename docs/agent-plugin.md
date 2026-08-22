# Travel Agent Plugin

Travel 是独立领域应用，拥有地图、地点、路线、授权和草案数据。仓库中的 Shadow Plugin 只
声明它对 Agent Runtime 暴露的远程能力，不包含 DSH、Cordis 或其他 Harness 依赖。

首期能力只有：

- 读取当前 Agent 通过 scope 和地图级 grant 双重授权的最小地图上下文；
- 创建 `pending` 状态的可撤销草案，正式应用仍由 Travel 用户会话完成。

Platform 校验 `shadow-plugin.yaml`、`agent/manifest.yaml` 和 OpenAPI 后，把本项目配置编译进
目标 Profile 的通用 DSH Bundle。运行时使用 Travel 专属 Bearer 直接访问机器 API，Platform
不转发地图数据。真实地址、Token、用户数据和生产 Profile 配置均不进入本仓库。

当前接口不返回统一摘要或长期资源引用，因此三个 Tool 都使用有严格响应与模型预算的
`full` 模式。以后若 API 增加 `summary` 或 `shadow://` 引用，应先更新领域 OpenAPI，再收紧
Manifest 的结果模式。
