import {
  ArrowLeft,
  CalendarPlus,
  Camera,
  Check,
  Clock3,
  ExternalLink,
  Heart,
  MapPin,
  Navigation,
  Pencil,
  Star,
  Users
} from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { AvatarStack, EmptyState, Modal, Toast } from "../components/Shared";
import { mapProviderForCountry } from "../map/provider";
import { useTravel } from "../state/TravelContext";
import { Preference } from "../types";

const preferenceLabels: { value: Preference; label: string }[] = [
  { value: "none", label: "未标记" },
  { value: "want", label: "想去" },
  { value: "planned", label: "计划去" },
  { value: "skip", label: "暂不考虑" }
];

export function PlacePage() {
  const { placeId } = useParams();
  const { placeById, maps, visits, members, setPreference, markVisited, updatePlace, recordVisit } = useTravel();
  const navigate = useNavigate();
  const place = placeById(placeId);
  const [toast, setToast] = useState<string>();
  const [editingNote, setEditingNote] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [addingVisit, setAddingVisit] = useState(false);
  const [visitDraft, setVisitDraft] = useState({
    visitedOn: new Date().toISOString().slice(0, 10),
    note: "",
    rating: "5"
  });
  const [saving, setSaving] = useState(false);

  if (!place) {
    return (
      <div className="content-page">
        <EmptyState icon={<MapPin />} title="没有找到这个地点">
          地点可能已被合并或移除。
        </EmptyState>
      </div>
    );
  }

  const activePlace = place;
  const placeMaps = maps.filter((map) => place.mapIds.includes(map.id));
  const placeVisits = visits.filter((visit) => visit.placeId === place.id);
  const visited = place.visitedBy.includes("me");
  const mapProvider = mapProviderForCountry();
  const externalMapUrl = mapProvider.externalPlaceUrl(place);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(undefined), 2200);
  }

  async function saveNote(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await updatePlace(activePlace.id, { note: noteDraft });
      setEditingNote(false);
      notify("备注已保存");
    } catch (error) {
      notify(error instanceof Error ? error.message : "备注保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveVisit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await recordVisit(activePlace.id, {
        mapId: activePlace.mapIds[0],
        visitedOn: visitDraft.visitedOn,
        note: visitDraft.note,
        rating: Number(visitDraft.rating)
      });
      setAddingVisit(false);
      setVisitDraft({ visitedOn: new Date().toISOString().slice(0, 10), note: "", rating: "5" });
      notify("到访记录已保存");
    } catch (error) {
      notify(error instanceof Error ? error.message : "到访记录保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="place-detail-page">
      <header className="place-detail-header">
        <button className="icon-button" type="button" onClick={() => navigate(-1)} aria-label="返回">
          <ArrowLeft size={20} />
        </button>
        <div className="place-title">
          <span className="eyebrow">{place.city} · {place.district} · {place.category}</span>
          <h1>{place.name}</h1>
          <p><MapPin size={15} /> {place.address}</p>
        </div>
        <div className="place-header-actions">
          {externalMapUrl ? (
            <a className="secondary-button" href={externalMapUrl} target="_blank" rel="noreferrer">
              <Navigation size={17} /> {mapProvider.label}打开
            </a>
          ) : (
            <button className="secondary-button" type="button" onClick={() => notify("外部地图跳转将在 Provider 地址配置后启用")}>
              <Navigation size={17} /> {mapProvider.label}打开
            </button>
          )}
          <button className="icon-button" type="button" aria-label="编辑地点备注" onClick={() => { setNoteDraft(place.note); setEditingNote(true); }}><Pencil size={18} /></button>
        </div>
      </header>

      <div className="place-detail-layout">
        <main className="place-main-column">
          <section className="place-hero-card">
            <div className="photo-mosaic">
              {(place.photos.length ? place.photos : ["等待第一张照片"]).map((photo, index) => (
                <div key={photo} className={`photo-tile photo-${index + 1}`}>
                  <span>{photo}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="detail-section">
            <div className="section-heading-row">
              <div><span className="eyebrow">SHARED NOTE</span><h2>同行备注</h2></div>
              <button className="text-button" type="button" onClick={() => { setNoteDraft(place.note); setEditingNote(true); }}><Pencil size={15} /> 编辑</button>
            </div>
            <p className="large-note">{place.note}</p>
            {place.recommended && (
              <div className="fact-grid">
                <div><span>推荐</span><strong>{place.recommended}</strong></div>
                <div><span>人均</span><strong>{place.price}</strong></div>
                <div><span>地图来源</span><strong>{place.provider === "amap" ? "高德地点" : "手动添加"}</strong></div>
              </div>
            )}
            <div className="tag-row roomy">{place.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
          </section>

          <section className="detail-section">
            <div className="section-heading-row">
              <div><span className="eyebrow">MY HISTORY</span><h2>我的到访</h2></div>
              <button className="secondary-button" type="button" onClick={() => setAddingVisit(true)}>
                <CalendarPlus size={16} /> 添加一次到访
              </button>
            </div>
            {placeVisits.length ? (
              <div className="place-visit-list">
                {placeVisits.map((visit) => (
                  <article key={visit.id}>
                    <span className="visit-date-badge">{visit.displayDate}</span>
                    <div>
                      <div className="rating-row">
                        {Array.from({ length: visit.rating ?? 0 }).map((_, index) => <Star key={index} size={14} fill="currentColor" />)}
                      </div>
                      <p>{visit.note}</p>
                      <small><Camera size={14} /> {visit.photoCount} 张照片 · 默认仅相关地图成员可见</small>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="inline-empty horizontal">
                <Clock3 size={22} />
                <div><strong>还没有到访记录</strong><span>“去过”会由一条真实到访记录推导。</span></div>
              </div>
            )}
          </section>
        </main>

        <aside className="place-side-column">
          <section className="personal-status-card">
            <div className={`visited-mark${visited ? " yes" : ""}`}>
              {visited ? <Check size={24} /> : <MapPin size={24} />}
            </div>
            <div><span>我的状态</span><strong>{visited ? "我去过" : "还没去"}</strong></div>
            {!visited && <button type="button" onClick={() => { void markVisited(place.id, place.mapIds[0]).then(() => notify("已记录为今天去过")).catch((error) => notify(error instanceof Error ? error.message : "标记失败")); }}>标记去过</button>}
          </section>

          <section className="side-card">
            <span className="eyebrow">MY INTENTION</span>
            <h2>这次想不想去</h2>
            <div className="preference-grid">
              {preferenceLabels.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  className={place.preference === value ? "active" : ""}
                  onClick={() => { void setPreference(place.id, value).catch((error) => notify(error instanceof Error ? error.message : "状态保存失败")); }}
                >
                  {value === "want" && <Heart size={15} />}
                  {value === "planned" && <CalendarPlus size={15} />}
                  {value === "skip" && <span>—</span>}
                  {value === "none" && <span>○</span>}
                  {label}
                </button>
              ))}
            </div>
            <div className="consensus-line"><AvatarStack members={members} /><span>2 人想去 · 1 人未标记</span></div>
          </section>

          <section className="side-card map-mini-card">
            <MapSurface places={[place]} selectedId={place.id} city={place.city} compact />
            <p>{place.coordinate.latitude.toFixed(4)}, {place.coordinate.longitude.toFixed(4)} · {mapProvider.coordinateSystem}</p>
          </section>

          <section className="side-card">
            <span className="eyebrow">IN MAPS</span>
            <h2>出现在 {placeMaps.length} 张地图</h2>
            <div className="map-reference-list">
              {placeMaps.map((map) => (
                <button key={map.id} type="button" onClick={() => navigate(`/maps/${map.id}`)}>
                  <span style={{ background: map.accent }}>{map.emoji}</span>
                  <div><strong>{map.title}</strong><small>{map.city} · {map.pointIds.length} 个地点</small></div>
                  <ExternalLink size={15} />
                </button>
              ))}
            </div>
          </section>

          <section className="privacy-note">
            <Users size={18} />
            <p>照片与个人体验不会因为这个地点出现在其他地图里而自动扩大可见范围。</p>
          </section>
        </aside>
      </div>
      {editingNote && (
        <Modal title="编辑同行备注" onClose={() => setEditingNote(false)}>
          <form className="form-stack" onSubmit={saveNote}>
            <label>备注<textarea autoFocus rows={7} value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} placeholder="营业时间、推荐菜、集合方式或自己的提醒" /></label>
            <div className="form-actions">
              <button className="secondary-button" type="button" onClick={() => setEditingNote(false)}>取消</button>
              <button className="primary-button" type="submit" disabled={saving}>{saving ? "保存中…" : "保存备注"}</button>
            </div>
          </form>
        </Modal>
      )}
      {addingVisit && (
        <Modal title="记录一次到访" onClose={() => setAddingVisit(false)}>
          <form className="form-stack" onSubmit={saveVisit}>
            <label>日期<input type="date" value={visitDraft.visitedOn} onChange={(event) => setVisitDraft({ ...visitDraft, visitedOn: event.target.value })} required /></label>
            <label>感受与备注<textarea rows={5} value={visitDraft.note} onChange={(event) => setVisitDraft({ ...visitDraft, note: event.target.value })} placeholder="这次去了哪里、吃了什么、下次还想怎样走" /></label>
            <label>评分<select value={visitDraft.rating} onChange={(event) => setVisitDraft({ ...visitDraft, rating: event.target.value })}>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 星</option>)}</select></label>
            <div className="form-actions">
              <button className="secondary-button" type="button" onClick={() => setAddingVisit(false)}>取消</button>
              <button className="primary-button" type="submit" disabled={saving}>{saving ? "保存中…" : "保存到访"}</button>
            </div>
          </form>
        </Modal>
      )}
      {toast && <Toast>{toast}</Toast>}
    </div>
  );
}
