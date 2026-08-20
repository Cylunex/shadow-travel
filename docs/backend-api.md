# Shadow Travel 后端接口契约

本文记录 Web UI、Shadow Media、LLM 与 Agent 后续对接所需的业务接口。所有浏览器接口均使用服务端 OIDC 会话，生产路径由 `/travel/` 前缀统一承载；本文省略此前缀。

## 浏览器接口

### 工作区与地图

- `GET /api/browser/v1/workspace`：返回当前用户可访问的地图、地点、个人到访、路线与成员摘要。
- `POST /api/browser/v1/travel-maps`：新建主题地图。`route_enabled` 默认 `false`，公园清单等场景不会自动产生路线。
- `PATCH /api/browser/v1/travel-maps/{map_id}`：修改名称、城市、主题样式、进度规则、路线开关或归档状态。进度支持关闭、完成全部、任意 N 个和可选日期范围。
- `DELETE /api/browser/v1/travel-maps/{map_id}`：仅所有者可永久删除。个人到访、记录和照片不以地图为所有者，不会随地图删除。
- `PUT /api/browser/v1/travel-maps/{map_id}/place-order`：整体重排地点顺序。
- `GET /api/browser/v1/travel-maps/{map_id}/progress`：按成员返回本期进度；本人读取全部个人 Visit，其他成员只统计显式共享给该主题的完成状态。
- `POST /api/browser/v1/travel-maps/{map_id}/copies`：复制共享点位、自定义字段和可选路线，不复制成员意愿、到访和照片。
- `GET /api/browser/v1/travel-maps/{map_id}/audit-events`：读取共享资源变更审计。

### 地点、意愿和到访

- `POST /api/browser/v1/travel-maps/{map_id}/places`：创建或复用高德地点并加入地图。
- `POST /api/browser/v1/travel-maps/{map_id}/places/{place_id}`：把已有可访问地点加入另一张地图。
- `PATCH /api/browser/v1/places/{place_id}`：修改地点事实，或通过 `map_id` 修改某个 MapPoint 的分类、标签、共享备注、自定义属性和进度开关。MapPoint 写入支持 `expected_version` 乐观锁。
- `PATCH /api/browser/v1/travel-maps/{map_id}/points/batch`：原子批量修改 MapPoint；任一版本冲突时整批回滚。
- `DELETE /api/browser/v1/travel-maps/{map_id}/places/{place_id}`：从地图移除，不删除 Place、个人 Visit、VisitRecord 或照片。
- `PUT /api/browser/v1/travel-maps/{map_id}/places/{place_id}/preference`：保存当前成员在该 MapPoint 中的 `none / want / planned / skip` 意愿。旧的无地图路径仅作为前端兼容入口。
- `GET /api/browser/v1/travel-maps/{map_id}/points`：按关键词、分类、标签、成员意愿、共识、到访和照片状态筛选主题点位。
- `POST /api/browser/v1/places/{place_id}/visits`：记录一次 Visit；从主题创建时可独立选择是否共享完成状态。
- `PATCH /api/browser/v1/visits/{visit_id}`、`DELETE /api/browser/v1/visits/{visit_id}`：修改或删除自己的到访。
- `PUT /api/browser/v1/visits/{visit_id}/completion-share`：新增或撤回 VisitMapShare。
- `PUT /api/browser/v1/visits/{visit_id}/record`：创建或更新一条可选 VisitRecord，并在私密与来源主题共享之间切换。
- `GET /api/browser/v1/travel-maps/{map_id}/shared-records`：返回成员主动共享给该主题的记录时间线。

Place 只保存名称、地址、坐标和 Provider 来源等现实事实；分类、标签、共享备注、自定义属性和排序保存在 MapPoint；Preference 始终带主题作用域；VisitMapShare 与 VisitRecord 分享互相独立。

### 自定义字段、导入与导出

- `GET/POST /api/browser/v1/travel-maps/{map_id}/fields`：列出或创建文本、数字、布尔和单选字段。
- `PATCH/DELETE /api/browser/v1/travel-maps/{map_id}/fields/{field_id}`：修改或删除字段定义；删除时同步移除点位值并递增版本。
- `POST /api/browser/v1/travel-maps/{map_id}/imports/preview`：解析 CSV 或 GeoJSON，返回标准化点位及逐行错误，不写数据库。
- `POST /api/browser/v1/travel-maps/{map_id}/imports`：应用确认后的点位；按 Provider 地点 ID 复用 Place。
- `GET /api/browser/v1/travel-maps/{map_id}/export?format=csv|geojson`：只导出共享地点事实和 MapPoint 内容，不包含个人意愿、到访或照片。

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

- `GET /api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos`：本人可读取自己的照片；主题成员只能读取已通过 VisitRecord 主动共享给该主题的照片元数据。
- `POST /api/browser/v1/photos/{photo_id}/access`：权限通过后申请短时访问地址。
- `PATCH /api/browser/v1/photos/{photo_id}`、`DELETE /api/browser/v1/photos/{photo_id}`：照片所有者修改说明或删除。

照片始终以 `private` 创建并挂在 VisitRecord 下。短时访问地址与元数据使用同一权限判定；上传完成接口可安全重试。媒体中心重编码并清理原 EXIF；拍摄时间和坐标只能作为 Travel 的独立字段显式保存，坐标默认仅照片所有者可读。

### 只读分享

- `GET/POST /api/browser/v1/travel-maps/{map_id}/share-links`：所有者列出或创建带有效期的只读令牌；原令牌只返回一次。
- `DELETE /api/browser/v1/travel-maps/{map_id}/share-links/{share_link_id}`：立即撤销令牌。
- `GET /api/public/v1/shares/{token}`：无需登录的只读展示接口，只返回共享 MapPoint；只有创建链接时明确启用，才附带已共享 VisitRecord 摘要，永不返回照片地址和私人记录。

### LLM 路线草案

- `POST /api/browser/v1/travel-maps/{map_id}/assistant/route-drafts`：用地图内已有地点和用户目标生成结构化路线草案。
- `GET /api/browser/v1/travel-maps/{map_id}/agent-drafts`：列出 LLM/Agent 草案。
- `PATCH /api/browser/v1/agent-drafts/{draft_id}`：批准或拒绝草案。
- `POST /api/browser/v1/agent-drafts/{draft_id}/apply`：应用已确认的 `route`、`map-notes` 或 `place-list` 草案。MapPoint 修改按 `expected_version` 原子检查冲突；外部 Agent 只能复用当前用户已有权访问的 Place，不能提交伪造地点事实。内部地点提取器的新候选必须携带经 MapProvider 验证的 Provider 数据。

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
