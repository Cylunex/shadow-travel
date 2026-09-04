import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "./lifecycle";
import type { Trip } from "../types";
import "./agent.css";

type Grant = {
  id: string;
  agent_id: string;
  resource_type: string;
  trip_id: string | null;
  allow_propose: boolean;
  allow_reservations: boolean;
  expires_at: string;
  revoked: boolean;
};
type Review = {
  review_id: string;
  agent_id: string;
  trip_id: string | null;
  state: string;
  revision: number;
  changeset_hash: string;
  summary: string;
  expires_at: string;
  proposal: { operations: Record<string, unknown>[]; [key: string]: unknown };
  preview: {
    changes: { op: string; before: unknown; after: unknown }[];
    checks: { errors: { message: string }[]; warnings: { message: string }[] };
    inferred: string[];
    uncertainties: string[];
    notice: string;
  };
  result: { trip_id: string; plan_revision: number } | null;
};

const states: Record<string, string> = {
  pending: "待审核",
  conflicted: "版本冲突",
  committed: "已保存",
  rejected: "已退回",
  expired: "已过期",
};
const operations: Record<string, string> = {
  CREATE_TRIP: "创建旅程",
  UPDATE_TRIP: "更新旅程",
  ADD_STOP: "添加站次",
  MOVE_STOP: "移动站次",
  REMOVE_STOP: "移除站次",
  UPSERT_RESERVATION: "保存预订摘要",
  REMOVE_RESERVATION: "移除预订摘要",
  INVALIDATE_TRANSPORT_ESTIMATES: "交通估计需重新核验",
};
const labels: Record<string, string> = {
  title: "名称",
  start_date: "开始日期",
  end_date: "结束日期",
  timezone: "时区",
  status: "状态",
  day: "日期",
  start: "开始时间",
  time: "时间",
  note: "备注",
  kind: "类型",
  duration_minutes: "停留分钟",
  place_id: "地点 ID",
  stop_id: "站次 ID",
  reservation_id: "预订 ID",
  id: "ID",
  anchor: "固定站次",
  fold: "夏令时偏移",
};

function ChangeValue({ value }: { value: unknown }) {
  if (value == null) return <span className="agent-muted">无</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  return (
    <dl className="agent-change-fields">
      {Object.entries(value)
        .filter(([key]) => key !== "op")
        .map(([key, v]) => (
          <div key={key}>
            <dt>{labels[key] || key}</dt>
            <dd>
              <ChangeValue value={v} />
            </dd>
          </div>
        ))}
    </dl>
  );
}

export function AgentPage({ demo }: { demo: boolean }) {
  const [params] = useSearchParams();
  const [grants, setGrants] = useState<Grant[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [trips, setTrips] = useState<Pick<Trip, "id" | "title">[]>([]);
  const [selected, setSelected] = useState<string>(params.get("review") || "");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState(false);
  const [editJson, setEditJson] = useState("");
  const [resourceType, setResourceType] = useState("trip");
  const review = reviews.find((r) => r.review_id === selected);
  const disabled = demo || !navigator.onLine || busy;
  async function load() {
    if (demo) {
      setLoading(false);
      return;
    }
    try {
      const [g, r, t] = await Promise.all([
        api<{ grants: Grant[] }>("agent/grants"),
        api<{ reviews: Review[] }>("agent/reviews"),
        api<{ trips: Pick<Trip, "id" | "title">[] }>("trips"),
      ]);
      setGrants(g.grants);
      setReviews(r.reviews);
      setTrips(t.trips);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, [demo]);
  async function act(fn: () => Promise<unknown>) {
    if (disabled) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      setMessage("操作已保存");
      setEditing(false);
    } catch (e) {
      setError(`${(e as Error).message}。未覆盖原数据；请刷新并核对最新版本。`);
    } finally {
      await load();
      setBusy(false);
    }
  }
  function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void act(async () => {
      await api("agent/grants", "POST", {
        agent_id: data.get("agent"),
        resource_type: resourceType,
        trip_id: resourceType === "trip" ? data.get("trip") : null,
        allow_read: true,
        allow_propose: data.get("propose") === "on",
        allow_reservations: data.get("reservations") === "on",
        expires_days: Number(data.get("days")),
      });
      form.reset();
    });
  }
  function decide(action: "commit" | "reject") {
    if (!review) return;
    void act(() =>
      api(`agent/reviews/${review.review_id}/${action}`, "POST", {
        expected_revision: review.revision,
        changeset_hash: review.changeset_hash,
      }),
    );
  }
  return (
    <div className="content-page lifecycle-page agent-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">TRAVEL AGENT</span>
          <h1>
            <Bot size={24} /> Agent 审核与授权
          </h1>
          <p>助手提出变更，你决定是否保存。私人记录不会交给 Agent。</p>
        </div>
        <button
          className="secondary-button"
          disabled={disabled}
          onClick={() => {
            setError("");
            void load();
          }}
        >
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      <div className="lifecycle-tabs">
        <Link to="/trips">返回旅程</Link>
        <Link to="/settings">我的设置</Link>
      </div>
      <p className="agent-notice">
        <ShieldCheck size={18} />
        此处使用真实 Travel 登录确认。Nexus
        签名确认凭证尚未接入；机器接口不能直接提交。
      </p>
      {demo && (
        <p role="status">演示模式不创建授权或审核结果，请使用真实登录会话。</p>
      )}
      {error && (
        <p className="map-search-error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {loading && <p role="status">正在读取审核队列…</p>}
      <div className="agent-layout">
        <section className="agent-panel">
          <h2>待审核变更</h2>
          {!loading && !reviews.length && (
            <p>
              暂无提案。授权后，助手可提出创建旅程、调整站次或录入预订摘要。
            </p>
          )}
          <div className="agent-review-list">
            {reviews.map((r) => (
              <button
                key={r.review_id}
                disabled={busy}
                className={`agent-review-row ${selected === r.review_id ? "selected" : ""}`}
                onClick={() => {
                  setSelected(r.review_id);
                  setEditing(false);
                  setError("");
                  setMessage("");
                }}
              >
                <strong>{r.summary}</strong>
                <span>
                  {states[r.state] || r.state} · v{r.revision} · {r.agent_id}
                </span>
              </button>
            ))}
          </div>
          {review && (
            <article className="agent-review-detail">
              <h3>{review.summary}</h3>
              <p>
                {states[review.state]} · 修订 {review.revision} · 有效至{" "}
                {new Date(review.expires_at).toLocaleString()}
              </p>
              <p>{review.preview.notice}</p>
              {review.preview.inferred.length > 0 && (
                <p>
                  <strong>助手推断：</strong>
                  {review.preview.inferred.join("；")}
                </p>
              )}
              {review.preview.uncertainties.length > 0 && (
                <p>
                  <strong>待核实：</strong>
                  {review.preview.uncertainties.join("；")}
                </p>
              )}
              {review.preview.checks.errors.map((c, i) => (
                <p key={i} className="map-search-error">
                  {c.message}
                </p>
              ))}
              {review.preview.checks.warnings.map((c, i) => (
                <p key={i} className="agent-muted">
                  {c.message}
                </p>
              ))}
              <div className="agent-changes">
                {review.preview.changes.map((c, i) => (
                  <section key={i}>
                    <h4>{operations[c.op] || c.op}</h4>
                    <div className="agent-diff">
                      <div>
                        <strong>修改前</strong>
                        <ChangeValue value={c.before} />
                      </div>
                      <div>
                        <strong>修改后</strong>
                        <ChangeValue value={c.after} />
                      </div>
                    </div>
                  </section>
                ))}
              </div>
              {review.result && (
                <Link
                  className="primary-button"
                  to={`/trips/${review.result.trip_id}`}
                >
                  查看已保存旅程 · 计划草稿 v{review.result.plan_revision}
                </Link>
              )}
              {["pending", "conflicted"].includes(review.state) && (
                <>
                  <div className="agent-actions">
                    <button
                      className="primary-button"
                      disabled={
                        disabled ||
                        editing ||
                        review.state === "conflicted" ||
                        review.preview.checks.errors.length > 0
                      }
                      onClick={() => decide("commit")}
                    >
                      确认保存变更
                    </button>
                    <button
                      className="secondary-button"
                      disabled={disabled}
                      onClick={() => decide("reject")}
                    >
                      退回提案
                    </button>
                    <button
                      className="secondary-button"
                      disabled={disabled}
                      onClick={() => {
                        setEditing(!editing);
                        setEditJson(JSON.stringify(review.proposal, null, 2));
                      }}
                    >
                      编辑提案
                    </button>
                  </div>
                  {review.state === "conflicted" && (
                    <p role="status">
                      旅程已被修改。请让助手读取最新版本后重新提案，或核对差异后编辑版本字段；不会自动覆盖。
                    </p>
                  )}
                  {editing && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        void act(async () =>
                          api(`agent/reviews/${review.review_id}`, "PUT", {
                            expected_revision: review.revision,
                            proposal: JSON.parse(editJson),
                          }),
                        );
                      }}
                    >
                      <label>
                        结构化提案（只接受已支持的操作；修改后必须再次确认）
                        <textarea
                          className="agent-editor"
                          rows={16}
                          value={editJson}
                          onChange={(e) => setEditJson(e.target.value)}
                          required
                        />
                      </label>
                      <button className="secondary-button" disabled={disabled}>
                        校验并保存新修订
                      </button>
                    </form>
                  )}
                </>
              )}
            </article>
          )}
        </section>
        <aside className="agent-panel">
          <h2>资源授权</h2>
          <p>授权不会配置 Token。Agent ID 必须与管理员已配置的机器身份一致。</p>
          <form className="agent-grant-form" onSubmit={grant}>
            <label>
              Agent ID
              <input
                name="agent"
                required
                maxLength={64}
                pattern="[A-Za-z0-9._-]+"
                placeholder="已配置的 Agent ID"
              />
            </label>
            <label>
              授权范围
              <select
                value={resourceType}
                onChange={(e) => setResourceType(e.target.value)}
              >
                <option value="trip">单个旅程（推荐）</option>
                <option value="workspace">我的全部旅程及创建新旅程</option>
              </select>
            </label>
            {resourceType === "trip" && (
              <label>
                旅程
                <select name="trip" required>
                  <option value="">选择你拥有的旅程</option>
                  {trips.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              有效天数
              <input
                name="days"
                type="number"
                min={1}
                max={90}
                defaultValue={30}
                required
              />
            </label>
            <label className="agent-checkbox">
              <input name="propose" type="checkbox" />
              允许提出变更（仍需逐次审核）
            </label>
            <label className="agent-checkbox">
              <input name="reservations" type="checkbox" />
              允许读取和提议修改预订摘要
            </label>
            <button className="primary-button" disabled={disabled}>
              确认授权
            </button>
          </form>
          <div className="agent-grants">
            {grants.map((g) => (
              <section key={g.id}>
                <strong>{g.agent_id}</strong>
                <p>
                  {g.resource_type === "workspace"
                    ? "我的全部旅程"
                    : trips.find((t) => t.id === g.trip_id)?.title ||
                      "单个旅程"}{" "}
                  · {g.allow_propose ? "读与提案" : "只读"}
                  {g.allow_reservations && " · 预订摘要"}
                </p>
                <small>
                  {g.revoked
                    ? "已撤销"
                    : `有效至 ${new Date(g.expires_at).toLocaleDateString()}`}
                </small>
                {!g.revoked && (
                  <button
                    className="secondary-button"
                    disabled={disabled}
                    onClick={() =>
                      void act(() => api(`agent/grants/${g.id}`, "DELETE"))
                    }
                  >
                    撤销授权
                  </button>
                )}
              </section>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
