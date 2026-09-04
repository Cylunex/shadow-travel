import { useEffect, useState } from "react";
import { localEntries } from "../offline";
import type { PlanState } from "./lifecycle";
export function TripReadiness({ plan }: { plan: PlanState }) {
  const [pack, setPack] = useState<PlanState>();
  useEffect(() => {
    void localEntries<PlanState>("pack")
      .then((rows) => setPack(rows.find((p) => p.id === plan.trip.id)?.value))
      .catch(() => setPack(undefined));
  }, [plan]);
  return (
    <section className="readiness">
      <h3>出发准备清单</h3>
      <ul>
        <li>
          {plan.approved_revision
            ? `已确认 v${plan.approved_revision}`
            : "待确认计划"}
        </li>
        <li>
          {plan.checks.errors.length
            ? `${plan.checks.errors.length} 个时间或引用冲突待处理`
            : "当前草稿未发现确定冲突（不等于全部可行）"}
        </li>
        <li>交通、营业与无障碍：按站核验，手工估计不是实时证据</li>
        <li>
          {plan.document.tasks.filter((t) => !t.done).length} 项准备任务未完成
        </li>
        <li>
          {plan.document.reservations.filter((r) => !r.source_ref).length}{" "}
          项预订没有资料引用；引用不代表附件访问权
        </li>
        <li>
          {pack?.offline && new Date(pack.offline.expires_at) > new Date()
            ? `本机副本 v${pack.approved_revision}，有效至 ${new Date(pack.offline.expires_at).toLocaleString()}`
            : "本机没有有效旅行副本"}
        </li>
        <li>Google 底图、实时地址、路线与天气均未离线下载</li>
      </ul>
    </section>
  );
}
