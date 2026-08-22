# Travel 草案类型

- `route`：`payload` 使用已有地点 ID 表达有序停靠点和路线说明。
- `place-list`：`payload` 只整理当前上下文已有地点，不创建未经地图服务核验的新地点。
- `map-notes`：`payload` 保存等待用户审核的地图级说明，不直接修改共享地图。

所有草案都保持 `pending`，由 Travel 浏览器会话中的用户批准、拒绝和应用。
