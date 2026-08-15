# Shadow Travel 后端接口契约

本文记录 Web UI、Shadow Media、LLM 与 Agent 后续对接所需的业务接口。所有浏览器接口均使用服务端 OIDC 会话，生产路径由 `/travel/` 前缀统一承载；本文省略此前缀。

## 浏览器接口

### 工作区与地图

- `GET /api/browser/v1/workspace`：返回当前用户可访问的地图、地点、个人到访、路线与成员摘要。
- `POST /api/browser/v1/travel-maps`：新建主题地图。`route_enabled` 默认 `false`，公园清单等场景不会自动产生路线。
- `PATCH /api/browser/v1/travel-maps/{map_id}`：修改名称、城市、主题样式、周期、路线开关或归档状态。
- `DELETE /api/browser/v1/travel-maps/{map_id}`：仅所有者可永久删除；仍有照片时拒绝删除，避免媒体对象失联。
- `PUT /api/browser/v1/travel-maps/{map_id}/place-order`：整体重排地点顺序。

### 地点、意愿和到访

- `POST /api/browser/v1/travel-maps/{map_id}/places`：创建或复用高德地点并加入地图。
- `POST /api/browser/v1/travel-maps/{map_id}/places/{place_id}`：把已有可访问地点加入另一张地图。
- `PATCH /api/browser/v1/places/{place_id}`：修改地点资料和共享备注。
- `DELETE /api/browser/v1/travel-maps/{map_id}/places/{place_id}`：从地图移除；仍有关联照片时拒绝。
- `PUT /api/browser/v1/places/{place_id}/preference`：保存当前用户自己的 `none / want / planned / skip` 意愿。
- `POST /api/browser/v1/places/{place_id}/visits`：记录一次到访。
- `PATCH /api/browser/v1/visits/{visit_id}`、`DELETE /api/browser/v1/visits/{visit_id}`：修改或删除自己的到访。

### 路线

- `POST /api/browser/v1/travel-maps/{map_id}/routes`：从地图内地点创建路线。
- `PATCH /api/browser/v1/routes/{route_id}`：修改路线、出行方式、备注、顺序与高德计算结果。
- `DELETE /api/browser/v1/routes/{route_id}`：删除路线。
- `POST /api/browser/v1/maps/routes`：通过 `MapProvider` 计算路线摘要；国内选高德，国际阶段选 Google。

### 同行协作

- `GET /api/browser/v1/travel-maps/{map_id}/collaboration`：成员和当前用户角色；待处理邀请仅所有者可见。
- `POST /api/browser/v1/travel-maps/{map_id}/invitations`：创建一次性邀请令牌，原令牌只在响应中出现一次。
- `POST /api/browser/v1/invitations/accept`：当前登录用户使用令牌加入地图。
- `DELETE /api/browser/v1/travel-maps/{map_id}/invitations/{invitation_id}`：撤销邀请。
- `PATCH /api/browser/v1/travel-maps/{map_id}/members/{member_id}`：所有者调整 `editor / viewer`。
- `DELETE /api/browser/v1/travel-maps/{map_id}/members/{member_id}`：所有者移除同行人，或同行人主动退出。

地图角色只负责共享资源权限；地点意愿和到访仍按 `shadow_user_id` 独立保存，不形成论坛、动态或关注关系。

### 照片

上传流程为三段式：

1. `POST /api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos/uploads` 由 Travel 后端向 Shadow Media 申请一次性 PUT 目标；
2. 浏览器直接向该临时目标上传图片，不接触 Media 服务凭据；
3. `POST /api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos/complete` 由 Travel 后端确认，并只保存返回的 `media_id`。

其他接口：

- `GET /api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos`：列出照片元数据，不返回永久对象地址。
- `POST /api/browser/v1/photos/{photo_id}/access`：权限通过后申请短时访问地址。
- `PATCH /api/browser/v1/photos/{photo_id}`、`DELETE /api/browser/v1/photos/{photo_id}`：照片所有者修改说明或删除。

照片始终以 `private` 创建。媒体中心重编码并清理原 EXIF；拍摄时间和坐标只能作为 Travel 的独立字段显式保存，坐标默认仅照片所有者可读。

### LLM 路线草案

- `POST /api/browser/v1/travel-maps/{map_id}/assistant/route-drafts`：用地图内已有地点和用户目标生成结构化路线草案。
- `GET /api/browser/v1/travel-maps/{map_id}/agent-drafts`：列出 LLM/Agent 草案。
- `PATCH /api/browser/v1/agent-drafts/{draft_id}`：批准或拒绝草案。
- `POST /api/browser/v1/agent-drafts/{draft_id}/apply`：把已确认的路线草案转换为正式路线。

模型请求由 Travel 进程内 SDK 直接发往供应商。提示词、输入、回答、地图内容和图片地址不会进入统一统计；统计只包含模型别名、实际模型、Token、延迟和状态。

## Agent 机器接口

机器接口只能使用独立 Bearer，缺少或错误凭据均返回 JSON，不读取浏览器 Cookie。

- `GET /api/machine/v1/agent/capabilities`：返回当前 Agent 能力。
- `GET /api/machine/v1/agent/maps`：只返回地图所有者显式授权的地图。
- `GET /api/machine/v1/agent/maps/{map_id}`：返回最小化地图、地点与路线上下文，不含个人意愿、到访和照片地址。
- `POST /api/machine/v1/agent/maps/{map_id}/drafts`：提交待用户确认的草案，必须提供 `Idempotency-Key`。

地图所有者通过以下浏览器接口控制 Agent 授权：

- `GET /api/browser/v1/travel-maps/{map_id}/agent-access`
- `PUT /api/browser/v1/travel-maps/{map_id}/agent-access/{agent_id}`
- `DELETE /api/browser/v1/travel-maps/{map_id}/agent-access/{agent_id}`

Agent registry 的 scope 和 Travel 数据库中的地图级授权必须同时满足。Agent 自报的用户名、用户 ID 或资源所有者字段一律不用于授权。
