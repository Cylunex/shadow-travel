import { Camera, LockKeyhole, MapPin, MapPinned, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useTravel } from "../state/TravelContext";

export function VisitsPage() {
  const { visits, placeById, mapById } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [city, setCity] = useState("all");
  const [theme, setTheme] = useState("all");
  const [photo, setPhoto] = useState("all");
  const [year, setYear] = useState("all");
  const visible = useMemo(
    () => visits.filter((visit) => {
      const place = placeById(visit.placeId);
      const matchesQuery = `${place?.name ?? ""} ${visit.note}`.includes(query);
      return matchesQuery && (city === "all" || place?.city === city) &&
        (theme === "all" || visit.mapId === theme) &&
        (year === "all" || visit.date.startsWith(year)) &&
        (photo === "all" || (photo === "yes" ? visit.photoCount > 0 : visit.photoCount === 0));
    }),
    [city, photo, placeById, query, theme, visits, year]
  );
  const cities = Array.from(new Set(visits.map((visit) => placeById(visit.placeId)?.city).filter(Boolean))) as string[];

  return (
    <div className="content-page visits-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">VISIT JOURNAL</span>
          <h1>到访记录</h1>
          <p>地点可以重复去，记忆也不必被压成一个“去过”开关。</p>
        </div>
      </header>

      <section className="visit-stat-strip">
        <div><strong>{visits.length}</strong><span>今年到访</span></div>
        <div><strong>{new Set(visits.map((visit) => visit.placeId)).size}</strong><span>不同地点</span></div>
        <div><strong>{visits.reduce((total, visit) => total + visit.photoCount, 0)}</strong><span>旅行照片</span></div>
        <div><strong>{new Set(visits.map((visit) => placeById(visit.placeId)?.city).filter(Boolean)).size}</strong><span>到访城市</span></div>
      </section>

      <div className="index-toolbar">
        <div className="search-field wide"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索到访地点" /></div>
        <label className="record-filter"><span>城市</span><select value={city} onChange={(event) => setCity(event.target.value)}><option value="all">全部城市</option>{cities.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="record-filter"><span>主题</span><select value={theme} onChange={(event) => setTheme(event.target.value)}><option value="all">全部主题</option>{Array.from(new Set(visits.map((visit) => visit.mapId).filter(Boolean))).map((id) => <option key={id} value={id}>{mapById(id)?.title ?? "未知主题"}</option>)}</select></label>
        <label className="record-filter"><span>照片</span><select value={photo} onChange={(event) => setPhoto(event.target.value)}><option value="all">不限</option><option value="yes">有照片</option><option value="no">无照片</option></select></label>
        <label className="record-filter"><span>时间</span><select value={year} onChange={(event) => setYear(event.target.value)}><option value="all">全部</option>{Array.from(new Set(visits.map((visit) => visit.date.slice(0, 4)))).map((item) => <option key={item}>{item}</option>)}</select></label>
      </div>

      <section className="timeline">
        <div className="timeline-month"><span>全部记录</span><small>{visible.length} 次到访</small></div>
        {visible.map((visit, index) => {
          const place = placeById(visit.placeId);
          const map = mapById(visit.mapId);
          if (!place) return null;
          return (
            <article key={visit.id} className="timeline-entry">
              <time><strong>{visit.displayDate}</strong><span>{visit.date.slice(0, 4)}</span></time>
              <span className="timeline-dot" />
              <button type="button" onClick={() => navigate(`/places/${place.id}`)}>
                <div className="timeline-card-top">
                  <div><span className="eyebrow">{place.city} · {place.category}</span><h2>{place.name}</h2></div>
                  {map && <span className="map-pill"><MapPinned size={12} /> {map.title}</span>}
                </div>
                {visit.rating && <span className="personal-rating">个人感受 {visit.rating}/5</span>}
                <p>{visit.note}</p>
                <div className="timeline-meta"><span><MapPin size={14} /> {place.district}</span><span><Camera size={14} /> {visit.photoCount} 张照片</span><span><LockKeyhole size={14} /> 个人记录</span></div>
              </button>
              {index === 0 && <span className="latest-label">最近一次</span>}
            </article>
          );
        })}
      </section>
    </div>
  );
}
