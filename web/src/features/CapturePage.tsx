import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Inbox, Search, MapPin, Check, Plus, ExternalLink } from "lucide-react";
import { Modal, EmptyState } from "../components/Shared";
import { MapSurface } from "../components/MapSurface";
import {
  searchAMapPlaces,
  reverseGeocodeAMap,
  type AMapSearchResult,
} from "../map/amapRuntime";
import { useTravel } from "../state/TravelContext";
import { api, type Capture } from "./lifecycle";
import type { Place } from "../types";
import { GoogleCapture } from "./GoogleCapture";

export function CapturePage() {
  const { places, maps, refresh } = useTravel();
  const [items, setItems] = useState<Capture[]>([]);
  const [active, setActive] = useState<Capture>();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [city, setCity] = useState("");
  const [filter, setFilter] = useState("pending");
  const [results, setResults] = useState<AMapSearchResult[]>([]);
  const [choice, setChoice] = useState<AMapSearchResult>();
  const [mode, setMode] = useState("search");
  const [mapId, setMapId] = useState("");
  const load = async () =>
    setItems((await api<{ captures: Capture[] }>("captures")).captures);
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  async function collect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    await run(async () => {
      const text = String(f.get("text"));
      const texts = f.has("split")
        ? text
            .split(/\r?\n/)
            .map((t) => t.trim())
            .filter(Boolean)
        : [text];
      if (texts.length > 100)
        throw new Error("一次最多收集 100 条，请分批保存");
      for (const text of texts)
        await api("captures", "POST", {
          text,
          source_url: f.get("url") || null,
          reason: f.get("reason") || "",
        });
      await load();
      setAdding(false);
    });
  }
  async function confirm(existingPlaceId?: string) {
    if (!active) return;
    await run(async () => {
      const body = existingPlaceId
        ? { existing_place_id: existingPlaceId }
        : choice
          ? {
              place: {
                name: choice.name,
                address: choice.address,
                city: choice.city || city,
                district: choice.district || "",
                longitude: choice.coordinate.longitude,
                latitude: choice.coordinate.latitude,
                coordinate_reference: "GCJ02",
                provider: choice.providerPlaceId ? "amap" : "manual",
                provider_place_id: choice.providerPlaceId || null,
              },
            }
          : null;
      if (!body) throw new Error("请先选择真实搜索结果或在地图上选点");
      const result = await api<{ place: Place }>(
        `captures/${active.id}/confirm`,
        "POST",
        body,
      );
      if (mapId)
        await api(`travel-maps/${mapId}/places/${result.place.id}`, "POST");
      await refresh();
      await load();
      setActive(undefined);
      setChoice(undefined);
    });
  }
  return (
    <div className="content-page lifecycle-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">CAPTURE → VERIFY → SAVE</span>
          <h1>地点收集箱</h1>
          <p>先收下灵感，核实具体是哪一家。文字和链接不会自动变成真实地点。</p>
        </div>
        <button
          className="primary-button"
          onClick={() => setAdding(true)}
          disabled={!navigator.onLine}
        >
          <Plus size={17} />
          收集地点
        </button>
      </header>
      <GoogleCapture />
      <div className="lifecycle-tabs">
        {[
          ["pending", "待整理"],
          ["confirmed", "已收藏"],
          ["dismissed", "已搁置"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={filter === key ? "active" : ""}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
        <Link to="/">地点地图</Link>
        <Link to="/maps">管理主题</Link>
      </div>
      {error && (
        <p className="lifecycle-alert" role="alert">
          {error}
        </p>
      )}
      <div className="capture-list">
        {items
          .filter((i) => i.status === filter)
          .map((item) => (
            <article className="lifecycle-card capture-row" key={item.id}>
              <span className="capture-glyph">
                <Inbox size={20} />
              </span>
              <div>
                <h3>{item.text}</h3>
                <p>{item.reason || "未填写收藏原因"}</p>
                <small>
                  {new Date(item.created_at).toLocaleString()} ·{" "}
                  {item.status === "confirmed"
                    ? "用户已确认"
                    : "具体地点未核验"}
                </small>
                {item.source_url && (
                  <a href={item.source_url} target="_blank" rel="noreferrer">
                    <ExternalLink size={13} />
                    查看原始来源
                  </a>
                )}
              </div>
              <div className="compact-actions">
                {item.status !== "confirmed" ? (
                  <>
                    <button
                      className="primary-button"
                      disabled={busy}
                      onClick={() => {
                        setActive(item);
                        setQuery(item.text.slice(0, 100));
                        setChoice(undefined);
                        setResults([]);
                      }}
                    >
                      整理
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await api(`captures/${item.id}`, "PATCH", {
                            status:
                              item.status === "dismissed"
                                ? "pending"
                                : "dismissed",
                          });
                          await load();
                        })
                      }
                    >
                      {item.status === "dismissed" ? "恢复" : "搁置"}
                    </button>
                  </>
                ) : (
                  <Link to={`/places/${item.place_id}`}>查看地点</Link>
                )}
              </div>
            </article>
          ))}
      </div>
      {!items.some((i) => i.status === filter) && (
        <EmptyState icon={<Inbox />} title="这里还没有内容">
          粘贴一段文字、一份清单或来源链接，之后再核实和收藏。
        </EmptyState>
      )}
      {adding && (
        <Modal title="收集地点灵感" onClose={() => setAdding(false)}>
          <form className="form-stack" onSubmit={collect}>
            <label>
              文字或地点清单
              <textarea
                autoFocus
                name="text"
                required
                rows={6}
                maxLength={20000}
                placeholder="每行一个地点，或保留完整素材"
              />
            </label>
            <label className="check-label">
              <input name="split" type="checkbox" />
              每行拆成一条待整理内容
            </label>
            <label>
              原始来源
              <input
                name="url"
                type="url"
                placeholder="https://…（不会自动抓取）"
              />
            </label>
            <label>
              为什么想去
              <textarea name="reason" maxLength={2000} />
            </label>
            {error && <p role="alert">{error}</p>}
            <button className="primary-button" disabled={busy}>
              {busy ? "保存中…" : "存入收集箱"}
            </button>
          </form>
        </Modal>
      )}
      {active && (
        <Modal title="核实并确认地点" onClose={() => setActive(undefined)}>
          <p className="lifecycle-hint">{active.text}</p>
          <div className="lifecycle-tabs">
            {[
              ["search", "高德搜索"],
              ["map", "地图选点"],
              ["existing", "已有收藏"],
              ["manual", "手工坐标"],
            ].map(([key, label]) => (
              <button
                key={key}
                className={mode === key ? "active" : ""}
                onClick={() => {
                  setMode(key);
                  setChoice(undefined);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <label>
            城市
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="城市，避免同名店误选"
            />
          </label>
          {mode === "search" && (
            <>
              <form
                className="inline-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    setResults(
                      await searchAMapPlaces(query, city || undefined),
                    );
                    setChoice(undefined);
                  });
                }}
              >
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="搜索地点"
                  required
                />
                <button className="secondary-button" disabled={busy}>
                  <Search size={16} />
                  搜索
                </button>
              </form>
              <div className="picker-list">
                {results.map((result, index) => (
                  <button
                    className={choice === result ? "selected" : ""}
                    key={result.providerPlaceId || index}
                    onClick={() => setChoice(result)}
                  >
                    <MapPin size={16} />
                    <span>
                      <strong>{result.name}</strong>
                      <small>
                        {result.address} · {result.district} · {result.category}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
              {!results.length && (
                <p className="lifecycle-hint">
                  请输入关键词搜索；搜索失败或结果为空时可手工选点。
                </p>
              )}
            </>
          )}
          {mode === "map" && (
            <div className="capture-map">
              <MapSurface
                places={[]}
                city={city || "全国"}
                onMapClick={(coordinate) =>
                  void run(async () => {
                    setChoice(await reverseGeocodeAMap(coordinate));
                  })
                }
              />
            </div>
          )}
          {mode === "manual" && (
            <form
              className="form-stack"
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                setChoice({
                  name: String(f.get("name")),
                  address: String(f.get("address")),
                  city,
                  coordinate: {
                    longitude: Number(f.get("lon")),
                    latitude: Number(f.get("lat")),
                  },
                });
              }}
            >
              <label>
                地点名称
                <input name="name" required />
              </label>
              <label>
                地址
                <input name="address" />
              </label>
              <div className="field-pair">
                <label>
                  经度 GCJ-02
                  <input
                    name="lon"
                    type="number"
                    step="any"
                    min={-180}
                    max={180}
                    required
                  />
                </label>
                <label>
                  纬度 GCJ-02
                  <input
                    name="lat"
                    type="number"
                    step="any"
                    min={-90}
                    max={90}
                    required
                  />
                </label>
              </div>
              <button className="secondary-button">预览手工地点</button>
            </form>
          )}
          {mode === "existing" && (
            <div className="picker-list">
              {places.map((p) => (
                <button
                  disabled={busy}
                  key={p.id}
                  onClick={() => void confirm(p.id)}
                >
                  <span>
                    <strong>{p.name}</strong>
                    <small>{p.address}</small>
                  </span>
                  <Check size={16} />
                </button>
              ))}
            </div>
          )}
          <label>
            同时放入主题（可选）
            <select value={mapId} onChange={(e) => setMapId(e.target.value)}>
              <option value="">只收藏地点，暂不归类</option>
              {maps.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title}
                </option>
              ))}
            </select>
          </label>
          {choice && (
            <div className="capture-confirm">
              <h3>{choice.name}</h3>
              <p>{choice.address}</p>
              <small>
                {choice.coordinate.longitude}, {choice.coordinate.latitude} ·
                GCJ-02
              </small>
              <button
                className="primary-button"
                disabled={busy || !(choice.city || city)}
                onClick={() => void confirm()}
              >
                <Check size={16} />
                确认收藏这个地点
              </button>
              {!(choice.city || city) && <p>请先填写城市。</p>}
            </div>
          )}
          {error && (
            <p role="alert" className="map-search-error">
              {error}
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
