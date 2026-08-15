import { Archive, ArrowRight, MapPinned, Plus, Search, Users } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AvatarStack, Modal, ProgressRing } from "../components/Shared";
import { useTravel } from "../state/TravelContext";

export function MapsPage() {
  const { maps, addMap } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState({ title: "", city: "", subtitle: "" });
  const visible = maps.filter((map) =>
    `${map.title} ${map.city} ${map.subtitle}`.toLowerCase().includes(query.toLowerCase())
  );

  function createMap(event: FormEvent) {
    event.preventDefault();
    if (!draft.title.trim() || !draft.city.trim()) return;
    const created = addMap(draft);
    setShowCreate(false);
    navigate(`/maps/${created.id}`);
  }

  return (
    <div className="content-page maps-index-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">THEME MAPS</span>
          <h1>主题地图</h1>
          <p>一张地图可以是一个年度计划，也可以只是一顿晚饭的念头。</p>
        </div>
        <button className="primary-button" type="button" onClick={() => setShowCreate(true)}>
          <Plus size={18} /> 新建地图
        </button>
      </header>

      <div className="index-toolbar">
        <div className="search-field wide">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索主题地图" />
        </div>
        <div className="segmented-control">
          <button type="button" className="active">使用中</button>
          <button type="button"><Archive size={15} /> 已归档</button>
        </div>
      </div>

      <section className="map-card-grid">
        {visible.map((map, index) => {
          const total = map.pointIds.length;
          const progress = total ? Math.round((map.completed / total) * 100) : 0;
          return (
            <article
              key={map.id}
              className={`theme-map-card theme-${index % 3}`}
              style={{ "--map-accent": map.accent, "--map-soft": map.accentSoft } as React.CSSProperties}
            >
              <button type="button" onClick={() => navigate(`/maps/${map.id}`)} aria-label={`打开${map.title}`}>
                <div className="theme-card-art">
                  <span className="theme-symbol">{map.emoji}</span>
                  <span className="contour contour-one" />
                  <span className="contour contour-two" />
                  {map.pointIds.slice(0, 5).map((id, pointIndex) => (
                    <span key={id} className={`mini-pin pin-${pointIndex + 1}`} />
                  ))}
                  <ProgressRing value={progress} label={`${map.completed}/${total || 0} 已去`} />
                </div>
                <div className="theme-card-content">
                  <span className="theme-card-city">{map.city}</span>
                  <h2>{map.title}</h2>
                  <p>{map.subtitle}</p>
                  <div className="theme-card-meta">
                    <AvatarStack members={map.members} />
                    <span><MapPinned size={15} /> {total} 个地点</span>
                    <span>更新于 {map.updatedAt}</span>
                  </div>
                  <span className="card-arrow"><ArrowRight size={19} /></span>
                </div>
              </button>
            </article>
          );
        })}

        <button className="new-map-card" type="button" onClick={() => setShowCreate(true)}>
          <span><Plus size={24} /></span>
          <strong>建立一张新地图</strong>
          <small>从一个城市、一份清单或一个念头开始</small>
        </button>
      </section>

      <aside className="maps-tip-card">
        <Users size={21} />
        <div>
          <strong>个人地图和同行地图，不需要分成两种模式</strong>
          <p>先自己创建，需要时再邀请同行人；你的到访和个人备注仍然属于你。</p>
        </div>
      </aside>

      {showCreate && (
        <Modal title="新建主题地图" onClose={() => setShowCreate(false)}>
          <form className="form-stack" onSubmit={createMap}>
            <label>
              地图名称
              <input
                autoFocus
                value={draft.title}
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                placeholder="例如：南京梧桐散步"
              />
            </label>
            <label>
              主要城市
              <input
                value={draft.city}
                onChange={(event) => setDraft({ ...draft, city: event.target.value })}
                placeholder="南京"
              />
            </label>
            <label>
              一句话介绍 <small>可选</small>
              <input
                value={draft.subtitle}
                onChange={(event) => setDraft({ ...draft, subtitle: event.target.value })}
                placeholder="秋天慢慢走完一条街"
              />
            </label>
            <div className="form-actions">
              <button className="secondary-button" type="button" onClick={() => setShowCreate(false)}>取消</button>
              <button className="primary-button" type="submit">创建地图</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
