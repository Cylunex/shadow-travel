import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CalendarDays, Plus, Route, MapPin } from "lucide-react";
import { Modal, EmptyState } from "../components/Shared";
import { useTravel } from "../state/TravelContext";
import { stableClientId } from "../offline";
import { api, tripList } from "./lifecycle";
import type { Trip } from "../types";

export function TripsPage() {
  const { maps } = useTravel();
  const navigate = useNavigate();
  const [trips, setTrips] = useState<Trip[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [creationId, setCreationId] = useState(() => stableClientId("trip"));
  useEffect(() => {
    tripList()
      .then(setTrips)
      .catch((e) => setError(e.message));
  }, []);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const trip = await api<Trip>("trips", "POST", {
        client_record_id: creationId,
        title: data.get("title"),
        start_date: data.get("start") || null,
        end_date: data.get("end") || null,
        source_map_id: data.get("map") || null,
        timezone: data.get("timezone"),
      });
      navigate(`/trips/${trip.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="content-page lifecycle-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">NEXT CHAPTER</span>
          <h1>旅程</h1>
          <p>把想去的地方，安排成一次真正的出发。</p>
        </div>
        <button
          className="primary-button"
          onClick={() => {
            setCreationId(stableClientId("trip"));
            setAdding(true);
          }}
          disabled={!navigator.onLine}
        >
          <Plus size={17} />
          新建旅程
        </button>
      </header>
      <div className="lifecycle-tabs">
        {[
          ["all", "全部"],
          ["planned", "准备中"],
          ["active", "旅途中"],
          ["completed", "已结束"],
        ].map(([key, name]) => (
          <button
            key={key}
            className={filter === key ? "active" : ""}
            onClick={() => setFilter(key)}
          >
            {name}
          </button>
        ))}
        <Link to="/capture">地点收集箱</Link>
        <Link to="/agent">Agent 审核</Link>
      </div>
      {error && (
        <p className="map-search-error" role="alert">
          {error}
        </p>
      )}
      <div className="trip-grid">
        {trips
          .filter((t) => filter === "all" || t.status === filter)
          .map((trip) => (
            <Link className="trip-card" to={`/trips/${trip.id}`} key={trip.id}>
              <span className="trip-glyph">
                <Route size={26} />
              </span>
              <span className="status-pill">
                {
                  {
                    planned: "准备中",
                    active: "旅途中",
                    completed: "已结束",
                    cancelled: "已取消",
                  }[trip.status]
                }
              </span>
              <h2>{trip.title}</h2>
              <p>
                <CalendarDays size={15} />
                {trip.startDate || "日期待定"}{" "}
                {trip.endDate && `— ${trip.endDate}`}
              </p>
              <small>
                <MapPin size={14} />
                {trip.timezone} · 点击规划与查看资料
              </small>
            </Link>
          ))}
      </div>
      {!trips.length && !error && (
        <EmptyState icon={<Route />} title="还没有旅程">
          创建一次旅行，从收藏中挑选地点；不用 AI 也能完整规划。
        </EmptyState>
      )}
      {adding && (
        <Modal title="新建旅程" onClose={() => setAdding(false)}>
          <form className="form-stack" onSubmit={create}>
            <label>
              名称
              <input
                name="title"
                required
                maxLength={160}
                placeholder="例如：京都的五天"
              />
            </label>
            <div className="field-pair">
              <label>
                开始
                <input name="start" type="date" />
              </label>
              <label>
                结束
                <input name="end" type="date" />
              </label>
            </div>
            <label>
              目的地时区
              <input
                name="timezone"
                required
                defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone}
                placeholder="Asia/Shanghai"
              />
            </label>
            <label>
              来源主题（可选）
              <select name="map">
                <option value="">独立旅程</option>
                {maps.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.title}
                  </option>
                ))}
              </select>
            </label>
            {error && <p role="alert">{error}</p>}
            <button className="primary-button" disabled={busy}>
              {busy ? "创建中…" : "创建旅程"}
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}
