import { Archive, ArrowRight, KeyRound, MapPinned, Plus, Route, Search, Users } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AvatarStack, Modal, ProgressRing } from "../components/Shared";
import { acceptMapInvitation } from "../api";
import { useTravel } from "../state/TravelContext";

export function MapsPage() {
  const { maps, addMap, refresh } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState({ title: "", city: "", subtitle: "", routeEnabled: false });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const [showJoin, setShowJoin] = useState(false);
  const [inviteToken, setInviteToken] = useState("");
  const visible = maps.filter((map) =>
    Boolean(map.archived) === showArchived &&
    `${map.title} ${map.city} ${map.subtitle}`.toLowerCase().includes(query.toLowerCase())
  );

  async function createMap(event: FormEvent) {
    event.preventDefault();
    if (!draft.title.trim() || !draft.city.trim()) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      const created = await addMap(draft);
      setShowCreate(false);
      navigate(`/maps/${created.id}`);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "创建地图失败");
    } finally {
      setSaving(false);
    }
  }

  async function joinMap(event: FormEvent) {
    event.preventDefault();
    if (!inviteToken.trim()) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      const result = await acceptMapInvitation(inviteToken.trim());
      await refresh();
      setShowJoin(false);
      navigate(`/maps/${result.map_id}`);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "加入地图失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="content-page maps-index-page">
      <header className="content-header">
        <div>
          <span className="eyebrow">MY COLLECTIONS</span>
          <h1>主题地图</h1>
          <p>用一张地图收好一个城市、一份年票清单，或一趟专门去吃东西的旅行。</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" type="button" onClick={() => { setSaveError(undefined); setShowJoin(true); }}><KeyRound size={17} /> 使用邀请</button>
          <button className="primary-button" type="button" onClick={() => setShowCreate(true)}><Plus size={18} /> 新建地图</button>
        </div>
      </header>

      <div className="index-toolbar">
        <div className="search-field wide">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索主题地图" />
        </div>
        <div className="segmented-control">
          <button type="button" className={!showArchived ? "active" : ""} onClick={() => setShowArchived(false)}>使用中</button>
          <button type="button" className={showArchived ? "active" : ""} onClick={() => setShowArchived(true)}><Archive size={15} /> 已归档</button>
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
              style={{ "--map-accent": "#159de5", "--map-soft": "rgba(21,157,229,.12)" } as React.CSSProperties}
            >
              <button type="button" onClick={() => navigate(`/maps/${map.id}`)} aria-label={`打开${map.title}`}>
                <div className="theme-card-art">
                  <span className="theme-symbol"><MapPinned size={19} /></span>
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
                    {map.routeEnabled && <span><Route size={15} /> 路线已启用</span>}
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
            <label className="choice-row">
              <input type="checkbox" checked={draft.routeEnabled} onChange={(event) => setDraft({ ...draft, routeEnabled: event.target.checked })} />
              <span><strong>为这张地图启用路线</strong><small>适合美食、散步等需要安排顺序的主题；公园打卡可以暂不启用。</small></span>
            </label>
            <div className="form-actions">
              <button className="secondary-button" type="button" onClick={() => setShowCreate(false)}>取消</button>
              <button className="primary-button" type="submit" disabled={saving}>{saving ? "正在创建…" : "创建地图"}</button>
            </div>
            {saveError && <div className="map-search-error">{saveError}</div>}
          </form>
        </Modal>
      )}
      {showJoin && (
        <Modal title="加入同行地图" onClose={() => setShowJoin(false)}>
          <form className="form-stack" onSubmit={joinMap}>
            <div className="assistant-boundary"><Users size={18} /><p>粘贴地图所有者发给你的一次性邀请令牌。加入后仍会独立保存你的意愿和到访记录。</p></div>
            <label>邀请令牌<input autoFocus value={inviteToken} onChange={(event) => setInviteToken(event.target.value)} placeholder="粘贴邀请令牌" /></label>
            <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setShowJoin(false)}>取消</button><button className="primary-button" type="submit" disabled={saving || !inviteToken.trim()}>{saving ? "正在加入…" : "加入地图"}</button></div>
            {saveError && <div className="map-search-error">{saveError}</div>}
          </form>
        </Modal>
      )}
    </div>
  );
}
