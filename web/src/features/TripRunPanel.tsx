import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Modal } from "../components/Shared";
import { localDate } from "../domain";
import { isLocalReadMode, stableClientId } from "../offline";
import type { Place } from "../types";
import {
  api,
  type PlanState,
  type RunState,
  type Stop,
  type OutcomeState,
} from "./lifecycle";
import {
  pendingCommands,
  submitCommand,
  type PendingCommand,
} from "./runtimeOffline";
import { TripEvidencePanel } from "./TripEvidencePanel";

const labels: Record<OutcomeState, string> = {
  pending: "未开始",
  in_progress: "进行中",
  completed: "完成",
  skipped: "跳过",
  deferred: "稍后",
};
export function TripRunPanel({
  plan,
  day,
  catalog,
  onSelect,
  onRun,
}: {
  plan: PlanState;
  day: string;
  catalog: Place[];
  onSelect: (id: string) => void;
  onRun: (run: RunState) => void;
}) {
  const [run, setRun] = useState<RunState | null>(plan.run || null);
  const [pending, setPending] = useState<PendingCommand[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [stop, setStop] = useState<Stop>();
  const [date, setDate] = useState("");
  const [share, setShare] = useState(false);
  const [visit, setVisit] = useState(true);
  const [reuse, setReuse] = useState<string>();
  const online = navigator.onLine && !isLocalReadMode();
  const accept = (value: RunState) => {
    setRun(value);
    onRun(value);
  };
  const loadPending = async () =>
    setPending(
      (await pendingCommands())
        .filter((e) => e.value.tripId === plan.trip.id)
        .map((e) => e.value),
    );
  useEffect(() => {
    let active = true;
    const load = async () => {
      if (navigator.onLine && !isLocalReadMode()) {
        const result = await api<{ run: RunState | null }>(
          `trips/${plan.trip.id}/run`,
        );
        if (active && result.run) accept(result.run);
      } else if (plan.run) accept(plan.run);
      if (active) await loadPending();
    };
    void load().catch((e) => active && setError(e.message));
    const update = () => void load().catch((e) => setError(e.message));
    window.addEventListener("runtime-queue-changed", update);
    return () => {
      active = false;
      window.removeEventListener("runtime-queue-changed", update);
    };
  }, [plan.trip.id]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
      const id = (e as { detail?: { visit_id?: string } }).detail?.visit_id;
      if (id) setReuse(id);
    } finally {
      setBusy(false);
    }
  };
  const own = (id: string) =>
    run?.outcomes.find(
      (o) => o.stop_id === id && o.member_id === run.member_id,
    );
  const stops = (run?.document.stops || [])
    .filter((s) => s.day === day)
    .sort((a, b) => a.start.localeCompare(b.start));
  const next =
    stops.find((s) => own(s.id)?.state === "in_progress") ||
    stops.find((s) => !own(s.id) || own(s.id)?.state === "pending");
  async function command(target: Stop, state: OutcomeState, visitId?: string) {
    if (!run) return;
    const result = await submitCommand(plan.trip.id, {
      operation_id: stableClientId("outcome"),
      run_id: run.id,
      plan_revision: run.plan_revision,
      stop_id: target.id,
      base_revision: own(target.id)?.revision || 0,
      state,
      shared: state === "completed" ? share : own(target.id)?.shared || false,
      ...(state === "completed" && visit
        ? visitId
          ? { reuse_visit_id: visitId }
          : { visit_date: date }
        : {}),
    });
    if (result) accept(result.run);
    await loadPending();
    setStop(undefined);
    setNotice(
      result
        ? "本次站次状态已保存。个人照片和记录仍然私密。"
        : "已保存在此设备，尚未同步；不会提前显示为已完成。",
    );
  }
  return (
    <section className="trip-runtime">
      <div className="next-stop">
        <small>
          旅途中 · {run ? `绑定确认版 v${run.plan_revision}` : "尚未开始"}
        </small>
        <h2>
          {next
            ? catalog.find((p) => p.id === next.place_id)?.name
            : run
              ? "没有待开始的站次"
              : "按自己的节奏出发"}
        </h2>
        <p>站次状态与真实到访独立；同一地点再次安排不会自动完成。</p>
      </div>
      {!run && (
        <button
          className="primary-button"
          disabled={!online || !plan.approved_revision || busy}
          onClick={() =>
            void action(async () => {
              const r = await api<{ run: RunState }>(
                `trips/${plan.trip.id}/run/start`,
                "POST",
              );
              accept(r.run);
            })
          }
        >
          开始旅途中模式
        </button>
      )}
      {run && plan.approved_revision !== run.plan_revision && (
        <div className="lifecycle-alert">
          <p>
            有新的确认计划。当前执行仍保持 v{run.plan_revision}，不会自动换版。
          </p>
          <button
            disabled={
              busy || !online || plan.role === "viewer" || pending.length > 0
            }
            onClick={() =>
              void action(async () => {
                const r = await api<{ run: RunState }>(
                  `trips/${plan.trip.id}/run/adopt`,
                  "POST",
                  {
                    base_revision: run.revision,
                    plan_revision: plan.approved_revision,
                  },
                );
                accept(r.run);
              })
            }
          >
            明确采用确认版 v{plan.approved_revision}
          </button>
          <small>已完成或进行中的站次不得被删除或改写。</small>
        </div>
      )}
      {error && (
        <p role="alert" className="lifecycle-alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {stops.map((s) => {
        const outcome = own(s.id),
          queued = pending.find((p) => p.command.stop_id === s.id);
        const others =
          run?.outcomes.filter(
            (o) => o.stop_id === s.id && o.member_id !== run.member_id,
          ) || [];
        return (
          <article className="plan-stop" key={s.id}>
            <button className="stop-title" onClick={() => onSelect(s.place_id)}>
              <span>
                {s.start}
                <small>{s.timezone || run?.document.timezone}</small>
              </span>
              <strong>
                {catalog.find((p) => p.id === s.place_id)?.name || "地点不可用"}
              </strong>
              <span>
                {queued
                  ? queued.state === "conflict"
                    ? "同步冲突"
                    : "待同步"
                  : labels[outcome?.state || "pending"]}
              </span>
            </button>
            <p>{s.note}</p>
            {outcome?.visit_id && (
              <Link to={`/places/${s.place_id}`}>
                已关联到访 · 补照片和个人记录
              </Link>
            )}
            {others.length > 0 && (
              <small>
                同行主动共享：
                {others
                  .map(
                    (o) =>
                      `${plan.members.find((m) => m.id === o.member_id)?.name || "同行"} ${labels[o.state]}`,
                  )
                  .join("、")}
              </small>
            )}
            {queued && (
              <p>
                {queued.error || "等待原账号联网同步"} ·{" "}
                <Link to="/settings">处理待同步操作</Link>
              </p>
            )}
            <div className="compact-actions">
              <button
                disabled={busy || !!queued}
                onClick={() => void action(() => command(s, "in_progress"))}
              >
                开始
              </button>
              <button
                className="primary-button"
                disabled={busy || !!queued}
                onClick={() => {
                  setStop(s);
                  setDate(
                    localDate(
                      s.timezone ||
                        run?.document.timezone ||
                        plan.trip.timezone,
                    ),
                  );
                  setVisit(!outcome?.visit_id);
                  setShare(outcome?.shared || false);
                  setReuse(undefined);
                }}
              >
                完成 / 记录到访
              </button>
              <button
                disabled={busy || !!queued}
                onClick={() => void action(() => command(s, "skipped"))}
              >
                跳过
              </button>
              <button
                disabled={busy || !!queued}
                onClick={() => void action(() => command(s, "deferred"))}
              >
                稍后
              </button>
              {outcome && (
                <button
                  disabled={busy || !!queued}
                  onClick={() => void action(() => command(s, "pending"))}
                >
                  恢复未开始
                </button>
              )}
            </div>
          </article>
        );
      })}
      {run && !stops.length && <p>这一天没有站次，可切换日期查看。</p>}
      {run && (
        <TripEvidencePanel
          stops={run.document.stops}
          places={catalog}
          day={day}
        />
      )}
      {stop && (
        <Modal title="确认本次站次" onClose={() => setStop(undefined)}>
          <div className="form-stack">
            <label>
              <input
                type="checkbox"
                checked={visit}
                onChange={(e) => setVisit(e.target.checked)}
              />
              我确实去过，同时创建到访事实
            </label>
            {visit && (
              <label>
                到访日期
                <input
                  type="date"
                  required
                  value={date}
                  onChange={(e) => {
                    setDate(e.target.value);
                    setReuse(undefined);
                  }}
                />
              </label>
            )}
            <label>
              <input
                type="checkbox"
                checked={share}
                onChange={(e) => setShare(e.target.checked)}
              />
              将本次完成状态与旅程同行共享
            </label>
            <p>
              照片、评分和个人记录默认私密。只完成站次不会自动证明到访；日期也不会被当作精确到达时间。
            </p>
            {error && <p role="alert">{error}</p>}
            {reuse ? (
              <button
                disabled={busy}
                onClick={() =>
                  void action(() => command(stop, "completed", reuse))
                }
              >
                同一天已有到访 · 确认复用
              </button>
            ) : (
              <button
                className="primary-button"
                disabled={busy || (visit && !date)}
                onClick={() => void action(() => command(stop, "completed"))}
              >
                {busy
                  ? "保存中…"
                  : visit
                    ? "确认去过并完成此站"
                    : "仅完成此站，不创建到访"}
              </button>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
