import {
  ArrowLeft,
  CalendarPlus,
  Camera,
  Check,
  Clock3,
  ExternalLink,
  Heart,
  ImagePlus,
  LoaderCircle,
  MapPinned,
  MapPin,
  Navigation,
  Pencil,
  ShieldCheck,
  Users
} from "lucide-react";
import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { AvatarStack, EmptyState, Modal, Toast } from "../components/Shared";
import { VisitDialog } from "../components/VisitDialog";
import { PhotoRecord, loadPhotoUrl, loadPlacePhotos, uploadPlacePhoto } from "../api";
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
  const { placeById, maps, visits, members, capabilities, setPreference, updatePlace, recordVisit } = useTravel();
  const navigate = useNavigate();
  const place = placeById(placeId);
  const [toast, setToast] = useState<string>();
  const [editingNote, setEditingNote] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [addingVisit, setAddingVisit] = useState(false);
  const [saving, setSaving] = useState(false);
  const [photos, setPhotos] = useState<Array<{ record: PhotoRecord; url: string }>>([]);
  const [photosLoading, setPhotosLoading] = useState(false);
  const [photoUploading, setPhotoUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activePlace = place;
  const activeMapId = activePlace?.mapIds[0];

  const refreshPhotos = useCallback(async () => {
    if (!capabilities.media || !activePlace || !activeMapId) return;
    setPhotosLoading(true);
    try {
      const records = await loadPlacePhotos(activeMapId, activePlace.id);
      const resolved = await Promise.all(records.map(async (record) => ({ record, url: await loadPhotoUrl(record.id) })));
      setPhotos(resolved);
    } catch {
      setPhotos([]);
    } finally {
      setPhotosLoading(false);
    }
  }, [activeMapId, activePlace, capabilities.media]);

  useEffect(() => { void refreshPhotos(); }, [refreshPhotos]);

  if (!activePlace) {
    return (
      <div className="content-page">
        <EmptyState icon={<MapPin />} title="没有找到这个地点">
          地点可能已被合并或移除。
        </EmptyState>
      </div>
    );
  }

  const placeData = activePlace;
  const placeMaps = maps.filter((map) => placeData.mapIds.includes(map.id));
  const placeVisits = visits.filter((visit) => visit.placeId === placeData.id);
  const visited = placeData.visitedBy.includes("me");
  const mapProvider = mapProviderForCountry();
  const externalMapUrl = mapProvider.externalPlaceUrl(placeData);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(undefined), 2200);
  }

  async function saveNote(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await updatePlace(placeData.id, { note: noteDraft });
      setEditingNote(false);
      notify("备注已保存");
    } catch (error) {
      notify(error instanceof Error ? error.message : "备注保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function uploadPhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const mapId = placeData.mapIds[0];
    event.target.value = "";
    if (!file || !mapId) return;
    setPhotoUploading(true);
    try {
      await uploadPlacePhoto(mapId, placeData.id, file);
      await refreshPhotos();
      notify("照片已保存为私密内容");
    } catch (error) {
      notify(error instanceof Error ? error.message : "照片上传失败");
    } finally {
      setPhotoUploading(false);
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
              {photos.map(({ record, url }, index) => <figure key={record.id} className={`photo-tile photo-${index + 1}`}><img src={url} alt={record.caption || `${place.name}的旅行照片`} />{record.caption && <figcaption>{record.caption}</figcaption>}</figure>)}
              {!photos.length && <div className="photo-empty"><span>{place.category.slice(0, 1) || "旅"}</span><strong>{photosLoading ? "正在读取照片…" : capabilities.media ? "留下这里的第一张照片" : "照片能力尚未配置"}</strong><small>{capabilities.media ? "原始 EXIF 与 GPS 会在媒体中心清理" : "配置 Shadow Media 后即可在这里上传私密照片"}</small></div>}
            </div>
            <div className="photo-toolbar">
              <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={uploadPhoto} hidden />
              <span><ShieldCheck size={15} /> 照片默认仅自己可见，主动共享后主题成员可见</span>
              {capabilities.media && <button className="secondary-button" type="button" onClick={() => fileInputRef.current?.click()} disabled={photoUploading}>{photoUploading ? <LoaderCircle className="spin" size={16} /> : <ImagePlus size={16} />}{photoUploading ? "上传中…" : "上传照片"}</button>}
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
                      {visit.rating && <span className="personal-rating">个人感受 {visit.rating}/5</span>}
                      <p>{visit.note}</p>
                      <small><Camera size={14} /> {visit.photoCount} 张照片 · 默认仅自己可见</small>
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
            {!visited && <button type="button" onClick={() => setAddingVisit(true)}>标记去过</button>}
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
                  onClick={() => { void setPreference(place.id, value, place.mapIds[0]).catch((error) => notify(error instanceof Error ? error.message : "状态保存失败")); }}
                >
                  {value === "want" && <Heart size={15} />}
                  {value === "planned" && <CalendarPlus size={15} />}
                  {value === "skip" && <span>—</span>}
                  {value === "none" && <span>○</span>}
                  {label}
                </button>
              ))}
            </div>
            {members.length > 1 && <div className="consensus-line"><AvatarStack members={members} /><span>同行人分别保存自己的意愿和到访</span></div>}
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
                  <span><MapPinned size={15} /></span>
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
      {addingVisit && <VisitDialog placeName={placeData.name} visits={placeVisits} onClose={() => setAddingVisit(false)} onReuse={() => setAddingVisit(false)} onSave={async (draft) => { await recordVisit(placeData.id, { mapId: placeData.mapIds[0], ...draft }); setAddingVisit(false); notify("到访已保存，可继续补照片和记录"); }} />}
      {toast && <Toast>{toast}</Toast>}
    </div>
  );
}
