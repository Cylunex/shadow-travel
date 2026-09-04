import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Plus,
  Save,
  Check,
  Download,
  Navigation,
  MapPin,
  GripVertical,
  Trash2,
  LockKeyhole,
  Printer,
} from "lucide-react";
import { MapSurface } from "../components/MapSurface";
import { Modal } from "../components/Shared";
import { VisitDialog } from "../components/VisitDialog";
import { mapProviderForCountry } from "../map/provider";
import { useTravel } from "../state/TravelContext";
import { localDate } from "../domain";
import { isLocalReadMode, stableClientId } from "../offline";
import {
  api,
  downloadPack,
  readPlan,
  tripCalendarUrl,
  type PlanDocument,
  type PlanState,
  type Stop,
  type Reservation,
} from "./lifecycle";
import type { Place } from "../types";
import { TripRunPanel } from "./TripRunPanel";
import { PlanV2Panel } from "./PlanV2Panel";
import type { RunState } from "./lifecycle";
import { TripReadiness } from "./TripReadiness";
import { orderedStops, pruneSegments } from "./planTime";

export function TripPage() {
  const { tripId = "" } = useParams();
  const { places, visits, recordVisit } = useTravel();
  const [state, setState] = useState<PlanState>();
  const [activeRun, setActiveRun] = useState<RunState>();
  const [draft, setDraft] = useState<PlanDocument>();
  const [tab, setTab] = useState("plan");
  const [day, setDay] = useState("");
  const [selected, setSelected] = useState<string>();
  const [dialog, setDialog] = useState<
    "candidate" | "stop" | "reservation" | "member" | null
  >(null);
  const [visitPlace, setVisitPlace] = useState<Place>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [delayMinutes, setDelayMinutes] = useState(30);
  const [search, setSearch] = useState("");
  const [dragged, setDragged] = useState<string>();
  const [dirty, setDirty] = useState(false);
  const [sheetSnap, setSheetSnap] = useState("half");
  const [editingStop, setEditingStop] = useState<Stop>();
  const [proposal, setProposal] = useState<{
    base_revision: number;
    document: PlanDocument;
    changes: { id: string; from: string; to: string }[];
    assumptions: string[];
    expires_at: string;
    checks: PlanState["checks"];
  }>();
  const load = async () => {
    const data = await readPlan(tripId);
    setState(data);
    setDraft(structuredClone(data.document));
    setDirty(false);
    setDay(
      (current) =>
        current || data.trip.startDate || localDate(data.trip.timezone),
    );
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, [tripId]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    const protectLink = (event: MouseEvent) => {
      if (
        dirty &&
        (event.target as Element)?.closest?.("a[href]") &&
        !window.confirm("当前计划草稿尚未保存，确定离开？")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", protectLink, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", protectLink, true);
    };
  }, [dirty]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!state || !draft)
    return (
      <div className="content-page">
        <Link to="/trips">返回旅程</Link>
        <p role="status">{error || "正在读取旅程…"}</p>
      </div>
    );
  const editing =
    state.role !== "viewer" && navigator.onLine && !isLocalReadMode();
  const catalog = [
    ...new Map([...places, ...state.places].map((p) => [p.id, p])).values(),
  ];
  const findPlace = (id: string) => catalog.find((p) => p.id === id);
  const change = (next: PlanDocument) => {
    if (next.schema_version === 2) {
      next = {
        ...pruneSegments({
          ...next,
          timezone: next.timezone || state.trip.timezone,
        }),
        candidate_metadata: Object.fromEntries(
          Object.entries(next.candidate_metadata || {}).filter(([id]) =>
            next.candidates.includes(id),
          ),
        ),
      };
    }
    setDraft(next);
    setDirty(true);
  };
  const confirmed = state.versions.find(
    (v) => v.revision === state.approved_revision,
  )?.document;
  const display =
    tab === "field"
      ? activeRun?.document || state.run?.document || confirmed
      : draft;
  const todaysStops = orderedStops(
    display?.stops || [],
    display?.timezone || state.trip.timezone,
  ).filter((s) => s.day === day);
  const selectedPlace = findPlace(selected || todaysStops[0]?.place_id || "");
  async function save() {
    if (!draft || !state) return;
    const result = await api<PlanState>(`trips/${tripId}/plan`, "PUT", {
      base_revision: state.revision,
      document: draft,
    });
    setState(result);
    setDraft(structuredClone(result.document));
    setDirty(false);
    setNotice("草稿已保存；点击确认计划后才用于旅途中模式与离线包。");
  }
  function submitStop(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    const f = new FormData(event.currentTarget);
    const stop: Stop = {
      ...editingStop,
      id: editingStop?.id || stableClientId("stop"),
      place_id: editingStop?.place_id || String(f.get("place")),
      day: String(f.get("day")),
      start: String(f.get("start")),
      duration_minutes: Number(f.get("duration")),
      travel_minutes:
        draft.schema_version === 1 && f.get("travel")
          ? Number(f.get("travel"))
          : null,
      mode: f.get("mode") as Stop["mode"],
      anchor: f.has("anchor"),
      note: String(f.get("note") || ""),
    };
    change({
      ...draft,
      stops: editingStop
        ? draft.stops.map((s) => (s.id === stop.id ? stop : s))
        : [...draft.stops, stop],
    });
    setEditingStop(undefined);
    setDialog(null);
  }
  function reorder(target: Stop, sourceId?: string) {
    const source = draft!.stops.find((s) => s.id === sourceId);
    if (
      !source ||
      source.anchor ||
      target.anchor ||
      source.day !== target.day ||
      source.id === target.id
    )
      return;
    change({
      ...draft!,
      stops: draft!.stops.map((s) =>
        s.id === source.id
          ? { ...s, start: target.start }
          : s.id === target.id
            ? { ...s, start: source.start }
            : s,
      ),
    });
  }
  return (
    <div className="trip-page">
      <header className="trip-header">
        <Link to="/trips" className="icon-button" aria-label="返回旅程">
          <ArrowLeft size={20} />
        </Link>
        <div>
          <span className="eyebrow">
            {state.trip.startDate || "日期待定"} —{" "}
            {state.trip.endDate || "待定"} · {state.trip.timezone}
          </span>
          <h1>{state.trip.title}</h1>
        </div>
        <span className="status-pill">
          {state.role === "owner"
            ? "所有者"
            : state.role === "editor"
              ? "可协作"
              : "只读"}{" "}
          · v{state.approved_revision || 0}
        </span>
        <Link className="secondary-button" to="/capture">
          <Plus size={16} />
          收集地点
        </Link>
      </header>
      <div className="trip-toolbar">
        <div className="lifecycle-tabs">
          {[
            ["plan", "规划"],
            ["field", "旅途中"],
            ["prep", "资料与准备"],
            ["members", "同行"],
            ["versions", "版本"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={tab === key ? "active" : ""}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="trip-toolbar-actions">
          <button
            className="secondary-button"
            disabled={!editing || busy || !dirty}
            onClick={() => void run(save)}
          >
            <Save size={15} />
            保存草稿{dirty && " *"}
          </button>
          <button
            className="primary-button"
            disabled={!editing || busy || dirty || !state.revision}
            onClick={() =>
              void run(async () => {
                const result = await api<PlanState>(
                  `trips/${tripId}/plan/approve`,
                  "POST",
                  { base_revision: state.revision },
                );
                setState(result);
                setNotice("计划已确认，历史版本保持不变。");
              })
            }
          >
            <Check size={15} />
            确认计划
          </button>
        </div>
      </div>
      {tab === "plan" && (
        <div className="compact-actions plan-assist">
          <button
            disabled={!editing || busy || dirty || !state.revision}
            onClick={() =>
              void run(async () => {
                setProposal(
                  await api(`trips/${tripId}/plan/reorder-proposal`, "POST", {
                    base_revision: state.revision,
                    day,
                  }),
                );
              })
            }
          >
            就近排序建议
          </button>
          <small>保留锚点 · 仅生成待确认草案</small>
          <label>
            调整未执行站次（分钟）
            <input
              aria-label="调整分钟"
              type="number"
              min="-180"
              max="360"
              value={delayMinutes}
              onChange={(e) => setDelayMinutes(Number(e.target.value))}
            />
          </label>
          <button
            disabled={
              !editing || busy || dirty || !state.revision || !delayMinutes
            }
            onClick={() =>
              void run(async () =>
                setProposal(
                  await api(`trips/${tripId}/plan/repair-proposal`, "POST", {
                    base_revision: state.revision,
                    day,
                    delay_minutes: delayMinutes,
                  }),
                ),
              )
            }
          >
            预览局部调整
          </button>
        </div>
      )}
      {error && (
        <div role="alert" className="lifecycle-alert">
          {error}{" "}
          {error.includes("conflict") && (
            <>
              <span>
                你的草稿仍保留。先导出再加载服务器版本，避免覆盖同行的修改。
              </span>
              <button
                onClick={() => {
                  const a = document.createElement("a");
                  const url = URL.createObjectURL(
                    new Blob([JSON.stringify(draft, null, 2)], {
                      type: "application/json",
                    }),
                  );
                  a.href = url;
                  a.download = "plan-draft.json";
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                导出我的草稿
              </button>
              <button onClick={() => void run(load)}>加载服务器版本</button>
            </>
          )}
        </div>
      )}
      {notice && (
        <div role="status" className="lifecycle-alert success">
          {notice}
        </div>
      )}
      {state.offline && (
        <div className="lifecycle-alert">
          本地副本 · {state.offline.notice} 下载于 {state.offline.downloaded_at}
        </div>
      )}
      {(tab === "plan" || tab === "field") && (
        <div className="trip-map-layout" data-snap={sheetSnap}>
          <section className="trip-plan-panel">
            <div className="sheet-snap-controls" aria-label="地点面板高度">
              {[
                ["collapsed", "收起"],
                ["half", "半屏"],
                ["full", "展开"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={sheetSnap === key ? "active" : ""}
                  onClick={() => setSheetSnap(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="day-picker">
              <label>
                查看日期
                <input
                  type="date"
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                />
              </label>
              {tab === "plan" && (
                <button
                  className="primary-button"
                  onClick={() => {
                    setEditingStop(undefined);
                    setDialog("stop");
                  }}
                  disabled={!editing || !draft.candidates.length}
                >
                  <Plus size={15} />
                  安排
                </button>
              )}
            </div>
            {tab === "field" && (
              <TripRunPanel
                key={tripId}
                plan={{ ...state, run: activeRun || state.run }}
                day={day}
                catalog={catalog}
                onSelect={setSelected}
                onRun={setActiveRun}
              />
            )}
            {tab === "plan" && (
              <PlanV2Panel
                plan={state}
                draft={draft}
                editing={editing}
                dirty={dirty}
                onChange={change}
              />
            )}
            {(tab === "plan" ? todaysStops : []).map((stop, index) => {
              const p = findPlace(stop.place_id);
              return (
                <article
                  className={`plan-stop${selectedPlace?.id === p?.id ? " selected" : ""}`}
                  key={stop.id}
                  draggable={editing && !stop.anchor && tab === "plan"}
                  onDragStart={() => setDragged(stop.id)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => reorder(stop, dragged)}
                >
                  <button
                    className="stop-title"
                    onClick={() => setSelected(stop.place_id)}
                  >
                    <span>
                      {stop.start}
                      <small>{stop.duration_minutes} 分钟</small>
                    </span>
                    <div>
                      <strong>{p?.name || "地点不可用"}</strong>
                      <small>
                        {p?.district} {stop.anchor ? "· 固定锚点" : ""}
                      </small>
                    </div>
                    {stop.anchor ? (
                      <LockKeyhole size={14} />
                    ) : (
                      <GripVertical size={14} />
                    )}
                  </button>
                  <p>{stop.note}</p>
                  <small>
                    {draft.schema_version === 2
                      ? "交通估计见独立路段"
                      : "到下一站："}
                    {draft.schema_version === 2
                      ? ""
                      : stop.travel_minutes === null
                        ? "时间未核验"
                        : `${stop.travel_minutes} 分钟（手工估计）`}
                  </small>
                  <div className="compact-actions">
                    {tab === "plan" ? (
                      <>
                        <button
                          disabled={!editing}
                          onClick={() => {
                            setEditingStop(stop);
                            setDialog("stop");
                          }}
                        >
                          编辑
                        </button>
                        <button
                          disabled={!editing || stop.anchor || index === 0}
                          onClick={() =>
                            reorder(stop, todaysStops[index - 1]?.id)
                          }
                        >
                          上移
                        </button>
                        <button
                          disabled={
                            !editing ||
                            stop.anchor ||
                            index === todaysStops.length - 1
                          }
                          onClick={() =>
                            reorder(stop, todaysStops[index + 1]?.id)
                          }
                        >
                          下移
                        </button>
                        <button
                          disabled={!editing}
                          onClick={() =>
                            change({
                              ...draft,
                              stops: draft.stops.filter(
                                (s) => s.id !== stop.id,
                              ),
                            })
                          }
                        >
                          <Trash2 size={13} />
                          移除
                        </button>
                      </>
                    ) : (
                      p && (
                        <button onClick={() => setVisitPlace(p)}>
                          标记去过
                        </button>
                      )
                    )}
                  </div>
                </article>
              );
            })}
            {!todaysStops.length && (
              <p className="lifecycle-hint">
                这天还没有安排。可以留白，或从候选地点开始。
              </p>
            )}
            {tab === "plan" && (
              <section className="candidate-pool">
                <header>
                  <h3>候选地点 · {draft.candidates.length}</h3>
                  <button
                    disabled={!editing}
                    onClick={() => setDialog("candidate")}
                  >
                    <Plus size={15} />
                    选择
                  </button>
                </header>
                {draft.candidates.map((id) => (
                  <button key={id} onClick={() => setSelected(id)}>
                    <MapPin size={14} />
                    {findPlace(id)?.name || id}
                    <span>
                      {draft.stops.some((s) => s.place_id === id)
                        ? "已安排"
                        : "未安排"}
                    </span>
                  </button>
                ))}
              </section>
            )}
            {state.checks.errors.map((c, i) => (
              <p className="map-search-error" key={i}>
                {c.message}
              </p>
            ))}
            {state.checks.warnings.length > 0 && (
              <p className="lifecycle-hint">
                {[...new Set(state.checks.warnings.map((c) => c.message))].join(
                  "；",
                )}
              </p>
            )}
          </section>
          <section className="trip-map">
            <MapSurface
              provider={mapProviderForCountry(
                selectedPlace?.countryCode ||
                  (selectedPlace?.provider === "google" ? "ZZ" : "CN"),
              )}
              places={(display?.candidates || [])
                .map(findPlace)
                .filter((p): p is Place => Boolean(p))}
              selectedId={selectedPlace?.id}
              onSelect={(p) => setSelected(p.id)}
              city={selectedPlace?.city || "旅行地图"}
            />
            {selectedPlace && (
              <div className="trip-map-card">
                <span className="eyebrow">{selectedPlace.city} · 地点事实</span>
                <h2>{selectedPlace.name}</h2>
                <p>{selectedPlace.address}</p>
                <div className="compact-actions">
                  <button
                    className="primary-button"
                    onClick={() => setVisitPlace(selectedPlace)}
                  >
                    <Check size={15} />
                    记录到访
                  </button>
                  <a
                    className="secondary-button"
                    href={mapProviderForCountry(
                      selectedPlace.countryCode ||
                        (selectedPlace.provider === "google" ? "ZZ" : "CN"),
                    ).externalPlaceUrl(selectedPlace)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Navigation size={15} />
                    地图导航
                  </a>
                  <Link to={`/places/${selectedPlace.id}`}>详情</Link>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
      {tab === "prep" && (
        <div className="trip-details-grid">
          <section className="lifecycle-card">
            <header>
              <h2>预约与资料</h2>
              <button
                className="secondary-button"
                disabled={!editing}
                onClick={() => setDialog("reservation")}
              >
                <Plus size={15} />
                添加
              </button>
            </header>
            <p className="lifecycle-hint">
              此处是共享摘要，不要填写确认码、证件号。资料引用不等于访问授权。
            </p>
            {draft.reservations.map((r) => (
              <article className="prep-row" key={r.id}>
                <div>
                  <strong>{r.title}</strong>
                  <small>
                    {r.day} {r.time} · {r.kind}
                  </small>
                  <p>{r.note}</p>
                  {r.source_ref && <code>{r.source_ref}</code>}
                </div>
                <button
                  className="icon-button"
                  aria-label={`移除 ${r.title}`}
                  disabled={!editing}
                  onClick={() =>
                    change({
                      ...draft,
                      reservations: draft.reservations.filter(
                        (x) => x.id !== r.id,
                      ),
                    })
                  }
                >
                  <Trash2 size={15} />
                </button>
              </article>
            ))}
          </section>
          <section className="lifecycle-card">
            <h2>准备事项</h2>
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const title = String(
                  new FormData(form).get("task") || "",
                ).trim();
                if (title)
                  change({
                    ...draft,
                    tasks: [
                      ...draft.tasks,
                      { id: stableClientId("task"), title, done: false },
                    ],
                  });
                form.reset();
              }}
            >
              <input
                name="task"
                placeholder="预约、行李、网络…"
                required
                maxLength={200}
              />
              <button disabled={!editing}>添加</button>
            </form>
            {draft.tasks.map((task) => (
              <label className="task-row" key={task.id}>
                <input
                  type="checkbox"
                  checked={task.done}
                  disabled={!editing}
                  onChange={(e) =>
                    change({
                      ...draft,
                      tasks: draft.tasks.map((t) =>
                        t.id === task.id ? { ...t, done: e.target.checked } : t,
                      ),
                    })
                  }
                />
                <span>{task.title}</span>
                <select
                  aria-label="责任人"
                  disabled={!editing}
                  value={task.assignee || ""}
                  onChange={(e) =>
                    change({
                      ...draft,
                      tasks: draft.tasks.map((t) =>
                        t.id === task.id
                          ? { ...t, assignee: e.target.value || null }
                          : t,
                      ),
                    })
                  }
                >
                  <option value="">未分配</option>
                  {state.members.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label>
              规划预算（非实际账单）
              <input
                type="number"
                min="0"
                value={draft.budget ?? ""}
                disabled={!editing}
                onChange={(e) =>
                  change({
                    ...draft,
                    budget: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </label>
            <label>
              共享约束摘要
              <textarea
                disabled={!editing}
                value={draft.constraints}
                placeholder="不要填写未经本人同意的健康详情"
                onChange={(e) =>
                  change({ ...draft, constraints: e.target.value })
                }
              />
            </label>
          </section>
          <section className="lifecycle-card">
            <h2>离线与出发检查</h2>
            <TripReadiness plan={state} />
            <p>
              仅下载已确认计划、地点和自己的到访；不含底图、票据原件或照片。此设备的解锁者可读取副本，请勿在公用设备启用。
            </p>
            <button
              className="primary-button"
              disabled={!navigator.onLine || !confirmed || busy}
              onClick={() => {
                if (
                  window.confirm(
                    "允许在此设备保留 7 天的旅行副本，并在断网时本地读取？不要在公用设备下载。",
                  )
                )
                  void run(async () => {
                    await downloadPack(tripId);
                    localStorage.setItem(
                      "shadow-travel-offline-enabled",
                      "yes",
                    );
                    setNotice(
                      "离线包已写入设备。底图与原始资料未下载；可到我的页面查看存储与同步状态。",
                    );
                  });
              }}
            >
              <Download size={16} />
              下载旅行副本
            </button>
            <div className="compact-actions">
              <a href={tripCalendarUrl(tripId)}>导出确认日历 ICS</a>
              <button
                onClick={() => {
                  setTab("field");
                  setTimeout(() => window.print(), 100);
                }}
              >
                <Printer size={15} />
                打印摘要
              </button>
            </div>
            <p className="lifecycle-hint">
              后台推送、票据自动解析、持续定位和合法离线底图未配置；不会显示为已启用。
            </p>
          </section>
        </div>
      )}
      {tab === "members" && (
        <section className="lifecycle-card trip-section">
          <header>
            <h2>本次同行</h2>
            <button
              className="secondary-button"
              disabled={state.role !== "owner" || !navigator.onLine}
              onClick={() => setDialog("member")}
            >
              添加同行
            </button>
          </header>
          <p>
            同行可以查看本次候选和计划；不会因此得到你的私密到访文字、照片和其他主题。
          </p>
          {state.members.map((member) => (
            <div className="prep-row" key={member.id}>
              <span>
                {member.name} · {member.role}
              </span>
              {state.role === "owner" && member.role !== "owner" && (
                <button
                  disabled={busy}
                  onClick={() => {
                    if (
                      window.confirm(
                        `撤销 ${member.name} 的旅程访问权限？已下载的离线副本不能即时撤回。`,
                      )
                    )
                      void run(async () => {
                        await api(
                          `trips/${tripId}/members/${member.id}`,
                          "DELETE",
                        );
                        await load();
                      });
                  }}
                >
                  移除
                </button>
              )}
            </div>
          ))}
          <label>
            旅程状态
            <select
              disabled={state.role !== "owner" || busy || !navigator.onLine}
              value={state.trip.status}
              onChange={(e) =>
                void run(async () => {
                  await api(`trips/${tripId}`, "PATCH", {
                    expected_version: state.trip.version,
                    status: e.target.value,
                  });
                  await load();
                })
              }
            >
              <option value="planned">准备中</option>
              <option value="active">旅途中</option>
              <option value="completed">已结束</option>
              <option value="cancelled">已取消</option>
            </select>
          </label>
        </section>
      )}
      {tab === "versions" && (
        <section className="lifecycle-card trip-section">
          <h2>确认历史</h2>
          <p>恢复只生成可编辑草稿；不修改历史版本，也不修改到访。</p>
          {state.versions.map((v) => (
            <div className="prep-row" key={v.revision}>
              <span>
                v{v.revision} · {v.created_at} · {v.document.stops.length} 站
              </span>
              <button
                disabled={!editing}
                onClick={() => {
                  change(structuredClone(v.document));
                  setNotice("已恢复到草稿，保存并确认后生效。");
                }}
              >
                作为新草稿
              </button>
            </div>
          ))}
        </section>
      )}
      {dialog === "candidate" && (
        <Modal title="从地点库选择候选" onClose={() => setDialog(null)}>
          <input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索地点、城市"
          />
          <div className="picker-list">
            {catalog
              .filter((p) => `${p.name}${p.city}`.includes(search))
              .map((p) => (
                <label key={p.id}>
                  <input
                    type="checkbox"
                    checked={draft.candidates.includes(p.id)}
                    onChange={(e) =>
                      change({
                        ...draft,
                        candidates: e.target.checked
                          ? [...draft.candidates, p.id]
                          : draft.candidates.filter((id) => id !== p.id),
                        stops: e.target.checked
                          ? draft.stops
                          : draft.stops.filter((s) => s.place_id !== p.id),
                      })
                    }
                  />
                  <span>
                    {p.name}
                    <small>{p.address}</small>
                  </span>
                </label>
              ))}
          </div>
          <Link to="/capture">没有想要的？去收集地点</Link>
          <button className="primary-button" onClick={() => setDialog(null)}>
            完成选择
          </button>
        </Modal>
      )}
      {dialog === "stop" && (
        <Modal
          title={editingStop ? "编辑安排" : "安排一站"}
          onClose={() => setDialog(null)}
        >
          <form className="form-stack" onSubmit={submitStop}>
            <label>
              地点
              <select
                name="place"
                required
                defaultValue={editingStop?.place_id}
                disabled={!!editingStop}
              >
                {draft.candidates.map((id) => (
                  <option value={id} key={id}>
                    {findPlace(id)?.name || id}
                  </option>
                ))}
              </select>
              {editingStop && (
                <small>
                  站次地点不可更换；如需换地点，请删除此安排并新建一站，保留历史执行身份。
                </small>
              )}
            </label>
            <div className="field-pair">
              <label>
                日期
                <input
                  name="day"
                  type="date"
                  defaultValue={editingStop?.day || day}
                  required
                />
              </label>
              <label>
                开始
                <input
                  name="start"
                  type="time"
                  defaultValue={editingStop?.start || "09:00"}
                  required
                />
              </label>
            </div>
            <div className="field-pair">
              <label>
                停留分钟
                <input
                  name="duration"
                  type="number"
                  min={1}
                  max={1440}
                  defaultValue={editingStop?.duration_minutes || 60}
                  required
                />
              </label>
              <label>
                到下一站分钟
                <input
                  name="travel"
                  disabled={draft.schema_version === 2}
                  defaultValue={editingStop?.travel_minutes ?? ""}
                  type="number"
                  min={0}
                  max={2880}
                  placeholder="未知，不能当作 0"
                />
                {draft.schema_version === 2 && (
                  <small>请在 Plan v2 的独立路段中填写</small>
                )}
              </label>
            </div>
            <label>
              出行方式
              <select name="mode" defaultValue={editingStop?.mode}>
                <option value="walking">步行</option>
                <option value="transit">公交</option>
                <option value="driving">驾车</option>
                <option value="bicycling">骑行</option>
              </select>
            </label>
            <label className="check-label">
              <input
                name="anchor"
                type="checkbox"
                defaultChecked={editingStop?.anchor}
              />
              固定锚点，不参与自动移动
            </label>
            <label>
              说明
              <textarea
                name="note"
                maxLength={2000}
                defaultValue={editingStop?.note}
              />
            </label>
            <button className="primary-button">加入草稿</button>
          </form>
        </Modal>
      )}
      {dialog === "reservation" && (
        <Modal title="手工添加预约摘要" onClose={() => setDialog(null)}>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const r: Reservation = {
                id: stableClientId("reservation"),
                title: String(f.get("title")),
                day: String(f.get("day")),
                time: String(f.get("time")),
                kind: f.get("kind") as Reservation["kind"],
                note: String(f.get("note") || ""),
                source_ref: String(f.get("source") || "") || null,
                timezone: String(f.get("timezone") || "") || null,
                fold:
                  f.get("fold") === ""
                    ? null
                    : (Number(f.get("fold")) as 0 | 1),
              };
              change({ ...draft, reservations: [...draft.reservations, r] });
              setDialog(null);
            }}
          >
            <label>
              标题
              <input name="title" required maxLength={200} />
            </label>
            <label>
              类型
              <select name="kind">
                <option value="stay">住宿</option>
                <option value="transport">交通</option>
                <option value="ticket">门票/预约</option>
                <option value="other">其他</option>
              </select>
            </label>
            <div className="field-pair">
              <input
                aria-label="预约日期"
                name="day"
                type="date"
                defaultValue={day}
                required
              />
              <input
                aria-label="预约时间"
                name="time"
                type="time"
                defaultValue="09:00"
                required
              />
            </div>
            <label>
              共享说明
              <textarea name="note" maxLength={2000} />
            </label>
            <label>
              预约当地时区
              <input name="timezone" placeholder={state.trip.timezone} />
            </label>
            <label>
              夏令时重复时刻
              <select name="fold">
                <option value="">通常时间 / 待消歧</option>
                <option value="0">首次出现</option>
                <option value="1">第二次出现</option>
              </select>
            </label>
            <label>
              已授权资料引用（可选）
              <input
                name="source"
                placeholder="shadow://archive/…"
                pattern="shadow://(archive|asset)/.+"
              />
            </label>
            <button className="primary-button">加入草稿</button>
          </form>
        </Modal>
      )}
      {dialog === "member" && (
        <Modal
          title="添加同行（需已登录过 Travel）"
          onClose={() => setDialog(null)}
        >
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void run(async () => {
                await api(`trips/${tripId}/members`, "POST", {
                  username: f.get("username"),
                  role: f.get("role"),
                });
                setDialog(null);
                await load();
              });
            }}
          >
            <label>
              精确用户名
              <input name="username" required />
            </label>
            <label>
              权限
              <select name="role">
                <option value="viewer">只读</option>
                <option value="editor">协作编辑</option>
              </select>
            </label>
            <button className="primary-button" disabled={busy}>
              授予旅程访问权限
            </button>
          </form>
        </Modal>
      )}
      {proposal && (
        <Modal title="审阅就近排序草案" onClose={() => setProposal(undefined)}>
          <p>这是一份确定性几何排序建议，不是 AI 编造的路线，也不保证最优。</p>
          {proposal.assumptions.map((a) => (
            <p className="lifecycle-hint" key={a}>
              {a}
            </p>
          ))}
          {proposal.changes.map((c) => (
            <div className="prep-row" key={c.id}>
              <span>
                {
                  findPlace(
                    draft.stops.find((s) => s.id === c.id)?.place_id || "",
                  )?.name
                }
              </span>
              <span>
                {c.from} → {c.to}
              </span>
            </div>
          ))}
          {!proposal.changes.length && <p>当前没有需要调整的顺序。</p>}
          {proposal.checks.errors.map((c, i) => (
            <p className="map-search-error" key={i}>
              {c.message}
            </p>
          ))}
          <button
            className="primary-button"
            disabled={
              !proposal.changes.length || proposal.checks.errors.length > 0
            }
            onClick={() => {
              if (
                proposal.base_revision !== state.revision ||
                new Date(proposal.expires_at) < new Date()
              ) {
                setError("草案已过期，请重新生成");
                return;
              }
              change(proposal.document);
              setProposal(undefined);
              setNotice("排序已放入草稿，尚未保存和确认。");
            }}
          >
            采用到草稿
          </button>
        </Modal>
      )}
      {visitPlace && (
        <VisitDialog
          timezone={state.trip.timezone}
          placeName={visitPlace.name}
          visits={visits.filter((v) => v.placeId === visitPlace.id)}
          onClose={() => setVisitPlace(undefined)}
          onReuse={() => setVisitPlace(undefined)}
          onSave={async (input) => {
            const result = await recordVisit(visitPlace.id, {
              ...input,
              tripId,
            });
            setVisitPlace(undefined);
            setNotice(
              result?.syncState === "pending"
                ? "已保存在本机，联网后由原账号同步。"
                : "到访已记录，私人文字不与同行自动共享。",
            );
          }}
        />
      )}
    </div>
  );
}
