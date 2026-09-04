# 类型化旅程提案

精确合同为 contracts/agent-v2.openapi.yaml；未声明字段全部拒绝。

```json
{
  "grant_id": "TOOL_RETURNED_GRANT_ID",
  "trip_id": null,
  "expected_trip_version": 0,
  "expected_plan_revision": 0,
  "summary": "京都五日：创建旅程，住宿与交通待确认",
  "operations": [{
    "op": "CREATE_TRIP",
    "trip": {
      "title": "京都五日",
      "start_date": "2026-10-03",
      "end_date": "2026-10-07",
      "timezone": "Asia/Tokyo",
      "status": "planned"
    }
  }],
  "inferred": ["标题、目的地时区"],
  "uncertainties": ["住宿未确认，往返交通未核验"]
}
```

新建必须 workspace grant、单个首位 CREATE_TRIP、两个版本为 0；日期和时区必须明确。
既有 Trip 必须有 trip_id 和刚读取的两个版本，允许 workspace 或该 Trip grant。

| 操作 | 约束 |
| --- | --- |
| CREATE_TRIP | 完整 trip 字段；可组合站次/预订；整批原子提交 |
| UPDATE_TRIP | 完整 trip 字段，先读再改，保留其余字段；不是任意 JSON Patch |
| ADD_STOP | Host 提供新 id、工具返回 place_id、日期时间停留；不创造 Place |
| MOVE_STOP | stop_id、day、start、timezone、可选 fold；不移动锚点或已执行站次 |
| REMOVE_STOP | stop_id；不删除 Place 或 Visit |
| UPSERT_RESERVATION | reservation：id/title/day/time/kind/note/timezone/fold；kind 为 stay/transport/ticket/other |
| REMOVE_RESERVATION | reservation_id 必须属于当前 Trip；禁止悬空引用 |

最多 50 操作。站次变化令交通估计失效，审核明确显示，不伪装实时路线。
预订只是计划摘要，不代表付款出票或已入住。跨服务 source_ref 当前拒绝。
保存返回 review_id/revision/changeset_hash/preview/state，不创建正式数据。
用户确认后原子保存 Trip + Plan Draft，返回版本和 resource_uri，不批准 PlanVersion。

## 旧地图草案

- route：当前地图已有地点 ID 的有序停靠点。
- place-list：已有 Place 引用，不创造未经地图服务核验的位置。
- map-notes：等待审核的共享备注。

不要把 Trip、Visit、Member Preference、照片或支付塞进旧地图 payload。
