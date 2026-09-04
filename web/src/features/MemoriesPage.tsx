import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Plus,
  LockKeyhole,
  Route,
  Download,
  Pencil,
  Trash2,
} from "lucide-react";
import { Modal, EmptyState } from "../components/Shared";
import { useTravel } from "../state/TravelContext";
import { localDate } from "../domain";
import { api, download, tripList, type Memory } from "./lifecycle";
import { basePath, loadPhotoUrl } from "../api";
import type { Trip } from "../types";

export function MemoriesPage() {
  const { visits, placeById } = useTravel();
  const [items, setItems] = useState<Memory[]>([]);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [edit, setEdit] = useState<Memory>();
  const [trail, setTrail] = useState(false);
  const [preview, setPreview] = useState<Memory["document"]>();
  const [gpx, setGpx] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [photoOptions, setPhotoOptions] = useState<
    { id: string; caption: string; date: string; place_id: string }[]
  >([]);
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({});
  const [photoDate, setPhotoDate] = useState("");
  const [selectedPhotos, setSelectedPhotos] = useState<string[]>([]);
  useEffect(() => {
    if (adding) setSelectedPhotos(edit?.document.photo_ids || []);
  }, [adding, edit?.id]);
  const load = async () =>
    setItems((await api<{ memories: Memory[] }>("memories")).memories);
  useEffect(() => {
    void Promise.all([load(), tripList().then(setTrips)]).catch((e) =>
      setError(e.message),
    );
  }, []);
  useEffect(() => {
    if (!adding) return;
    let cancelled = false;
    api<{ photos: typeof photoOptions }>(
      `memory-photo-options${photoDate ? `?on=${photoDate}` : ""}`,
    )
      .then(async (result) => {
        if (cancelled) return;
        setPhotoOptions(result.photos);
        const resolved = await Promise.all(
          result.photos
            .slice(0, 50)
            .map(async (photo) => [
              photo.id,
              await loadPhotoUrl(photo.id).catch(() => ""),
            ]),
        );
        if (!cancelled) setPhotoUrls(Object.fromEntries(resolved));
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [adding, photoDate]);
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
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await run(async () => {
      await api(
        edit ? `memories/${edit.id}` : "memories",
        edit ? "PUT" : "POST",
        {
          kind: edit?.kind || f.get("kind"),
          title: f.get("title"),
          occurred_on: f.get("date"),
          trip_id: f.get("trip") || null,
          text: f.get("text") || "",
          visit_ids: f.getAll("visits"),
          memory_ids: f.getAll("memories"),
          photo_ids: selectedPhotos,
        },
      );
      await load();
      setAdding(false);
      setEdit(undefined);
    });
  }
  return (
    <div className="content-page lifecycle-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">YOUR PRIVATE JOURNAL</span>
          <h1>回忆</h1>
          <p>到访是事实，片段是感受。没有定位也可以留下记录。</p>
        </div>
        <div className="compact-actions">
          <button
            className="secondary-button"
            disabled={!navigator.onLine}
            onClick={() => {
              setTrail(true);
              setPreview(undefined);
            }}
          >
            导入 GPX
          </button>
          <button
            className="primary-button"
            disabled={!navigator.onLine}
            onClick={() => {
              setEdit(undefined);
              setAdding(true);
            }}
          >
            <Plus size={16} />
            写一段回忆
          </button>
        </div>
      </header>
      <div className="lifecycle-tabs">
        <button className="active">片段与故事</button>
        <Link to="/visits">全部到访时间线 · {visits.length}</Link>
        <select
          aria-label="筛选旅程"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">全部旅程</option>
          {trips.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
      </div>
      {error && (
        <p className="lifecycle-alert" role="alert">
          {error}
        </p>
      )}
      <div className="memory-list">
        {items
          .filter((m) => !filter || m.trip_id === filter)
          .map((item) => (
            <article className="lifecycle-card memory-card" key={item.id}>
              <div className="memory-date">
                {item.occurred_on}
                <small>
                  <LockKeyhole size={12} />
                  仅自己
                </small>
              </div>
              <div>
                <span className="eyebrow">
                  {item.kind === "journey"
                    ? "JOURNEY"
                    : item.kind === "trail"
                      ? "TRAIL · WGS-84"
                      : "MEMORY"}
                </span>
                <h2>{item.title}</h2>
                <p className="memory-text">{item.document.text}</p>
                {item.document.visit_ids?.map((id) => {
                  const visit = visits.find((v) => v.id === id);
                  return (
                    <Link
                      key={id}
                      to={visit ? `/places/${visit.placeId}` : "/visits"}
                    >
                      {visit
                        ? `${visit.date} · ${placeById(visit.placeId)?.name || "到访"}`
                        : "原始到访已不可用"}
                    </Link>
                  );
                })}
                {item.document.memory_ids?.map((id) => (
                  <blockquote key={id}>
                    {items.find((m) => m.id === id)?.document.text ||
                      "原始片段已移除"}
                  </blockquote>
                ))}
                {item.kind === "trail" && (
                  <>
                    <p>
                      <Route size={15} />
                      {item.document.point_count} 点 · 约{" "}
                      {((item.document.distance_meters || 0) / 1000).toFixed(2)}{" "}
                      km · 不是到访事实
                    </p>
                    <TrailPreview document={item.document} />
                    <a
                      href={`${basePath}api/browser/v1/trails/${item.id}/export.gpx`}
                    >
                      <Download size={14} />
                      导出 GPX
                    </a>
                  </>
                )}
                <div className="compact-actions">
                  {item.kind !== "trail" && (
                    <button
                      onClick={() => {
                        setEdit(item);
                        setAdding(true);
                      }}
                    >
                      <Pencil size={14} />
                      编辑
                    </button>
                  )}
                  <button
                    onClick={() =>
                      download(
                        JSON.stringify(item, null, 2),
                        `memory-${item.id}.json`,
                      )
                    }
                  >
                    导出记录
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "删除此回忆？原始到访、照片和其他片段不会删除。",
                        )
                      )
                        void run(async () => {
                          await api(`memories/${item.id}`, "DELETE");
                          await load();
                        });
                    }}
                  >
                    <Trash2 size={14} />
                    删除
                  </button>
                </div>
              </div>
            </article>
          ))}
      </div>
      {!items.length && (
        <EmptyState icon={<BookOpen />} title="记录旅途，也记录日常">
          写一个片段，或将已有到访组织成自己的旅行故事。
        </EmptyState>
      )}
      {adding && (
        <Modal
          title={edit ? "编辑回忆" : "记录旅行片段"}
          onClose={() => setAdding(false)}
        >
          <form className="form-stack" onSubmit={save}>
            <label>
              类型
              <select
                name="kind"
                disabled={!!edit}
                defaultValue={edit?.kind || "memory"}
              >
                <option value="memory">私密片段</option>
                <option value="journey">旅行故事（引用到访与片段）</option>
              </select>
            </label>
            <label>
              标题
              <input
                name="title"
                required
                maxLength={200}
                defaultValue={edit?.title}
              />
            </label>
            <div className="field-pair">
              <label>
                日期
                <input
                  name="date"
                  type="date"
                  required
                  defaultValue={edit?.occurred_on || localDate()}
                />
              </label>
              <label>
                来源旅程
                <select name="trip" defaultValue={edit?.trip_id || ""}>
                  <option value="">无旅程</option>
                  {edit?.trip_id &&
                    !trips.some((t) => t.id === edit.trip_id) && (
                      <option value={edit.trip_id}>
                        原旅程（已无访问权，保留来源）
                      </option>
                    )}
                  {trips.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              内容
              <textarea
                rows={6}
                name="text"
                maxLength={20000}
                defaultValue={edit?.document.text}
              />
            </label>
            <details>
              <summary>关联我的到访（不会复制原记录）</summary>
              <div className="picker-list">
                {visits
                  .filter((v) => !v.id.startsWith("local:"))
                  .map((v) => (
                    <label key={v.id}>
                      <input
                        type="checkbox"
                        name="visits"
                        value={v.id}
                        defaultChecked={edit?.document.visit_ids?.includes(
                          v.id,
                        )}
                      />
                      {v.date} · {placeById(v.placeId)?.name}
                    </label>
                  ))}
              </div>
            </details>
            <details>
              <summary>故事引用片段</summary>
              <div className="picker-list">
                {items
                  .filter((m) => m.kind === "memory" && m.id !== edit?.id)
                  .map((m) => (
                    <label key={m.id}>
                      <input
                        type="checkbox"
                        name="memories"
                        value={m.id}
                        defaultChecked={edit?.document.memory_ids?.includes(
                          m.id,
                        )}
                      />
                      {m.title}
                    </label>
                  ))}
              </div>
            </details>
            <details>
              <summary>从我的照片选择（只引用，不复制原图）</summary>
              <label>
                按到访日期筛选
                <input
                  type="date"
                  value={photoDate}
                  onChange={(e) => setPhotoDate(e.target.value)}
                />
              </label>
              <div className="picker-list">
                {photoOptions.map((photo) => (
                  <label key={photo.id}>
                    <input
                      type="checkbox"
                      name="photos"
                      value={photo.id}
                      checked={selectedPhotos.includes(photo.id)}
                      onChange={(event) =>
                        setSelectedPhotos((current) =>
                          event.target.checked
                            ? [...current, photo.id]
                            : current.filter((id) => id !== photo.id),
                        )
                      }
                    />
                    {photoUrls[photo.id] && (
                      <img
                        className="photo-option"
                        src={photoUrls[photo.id]}
                        alt={photo.caption || "我的旅行照片"}
                      />
                    )}
                    <span>
                      {photo.caption ||
                        placeById(photo.place_id)?.name ||
                        "照片"}
                      <small>{photo.date} · 私密</small>
                    </span>
                  </label>
                ))}
              </div>
              {!photoOptions.length && (
                <p className="lifecycle-hint">
                  当前日期没有可引用的照片。可先在地点详情上传；跨应用资产选择仍需要专门授权。
                </p>
              )}
            </details>
            {error && <p role="alert">{error}</p>}
            <button className="primary-button" disabled={busy}>
              保存私密记录
            </button>
          </form>
        </Modal>
      )}
      {trail && (
        <Modal title="导入 GPX 参考路径" onClose={() => setTrail(false)}>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void run(async () => {
                await api("trails", "POST", {
                  title: f.get("title"),
                  occurred_on: f.get("date"),
                  trip_id: f.get("trip") || null,
                  gpx,
                });
                await load();
                setTrail(false);
              });
            }}
          >
            <label>
              标题
              <input name="title" required maxLength={200} />
            </label>
            <label>
              日期
              <input
                name="date"
                type="date"
                defaultValue={localDate()}
                required
              />
            </label>
            <label>
              旅程
              <select name="trip">
                <option value="">独立参考路径</option>
                {trips.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              GPX 文件（最多 2 MB / 20000 点）
              <input
                type="file"
                accept=".gpx,application/gpx+xml"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  setPreview(undefined);
                  if (!file) return;
                  void run(async () => {
                    if (file.size > 2_000_000)
                      throw new Error("GPX 文件超过 2 MB");
                    const text = await file.text();
                    setGpx(text);
                    setPreview(
                      await api("trails/preview", "POST", {
                        title: file.name.slice(0, 200),
                        occurred_on: localDate(),
                        gpx: text,
                      }),
                    );
                  });
                }}
              />
            </label>
            {preview && (
              <>
                <TrailPreview document={preview} />
                <p>
                  {preview.point_count} 点 ·{" "}
                  {((preview.distance_meters || 0) / 1000).toFixed(2)} km ·
                  WGS-84
                </p>
              </>
            )}
            <p className="lifecycle-hint">
              此预览是原始路径几何，不是导航底图。保留分段和缺失海拔，不会自动创建到访；海拔基准与时间需自行核实。
            </p>
            {error && <p role="alert">{error}</p>}
            <button className="primary-button" disabled={!preview || busy}>
              确认保存参考路径
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}

function TrailPreview({ document }: { document: Memory["document"] }) {
  const points = document.segments?.flat() || [];
  if (!points.length) return null;
  const xs = points.map((p) => p.longitude),
    ys = points.map((p) => p.latitude);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  return (
    <svg
      className="trail-preview"
      viewBox="0 0 600 200"
      role="img"
      aria-label="GPX 路径几何预览，无底图"
    >
      {document.segments?.map((segment, i) => (
        <polyline
          key={i}
          points={segment
            .filter(
              (_, index) =>
                index % Math.max(1, Math.floor(segment.length / 1500)) === 0 ||
                index === segment.length - 1,
            )
            .map(
              (p) =>
                `${20 + ((p.longitude - minX) / (maxX - minX || 1)) * 560},${180 - ((p.latitude - minY) / (maxY - minY || 1)) * 160}`,
            )
            .join(" ")}
          fill="none"
          stroke="var(--travel)"
          strokeWidth={2}
        />
      ))}
    </svg>
  );
}
