import {
  ArrowLeft,
  Check,
  Copy,
  List,
  LoaderCircle,
  Map as MapIcon,
  MapPin,
  Plus,
  Route,
  Search,
  Sparkles,
  UserPlus
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { PlaceListItem } from "../components/PlaceListItem";
import { AvatarStack, EmptyState, Modal, ProgressRing, Toast } from "../components/Shared";
import { CollaborationState, RouteDraft, applyAgentDraft, createAssistantRouteDraft, createMapInvitation, loadCollaboration } from "../api";
import { AMapSearchResult, MapCoordinate, reverseGeocodeAMap, searchAMapPlaces } from "../map/amapRuntime";
import { useTravel } from "../state/TravelContext";
import { Place } from "../types";

export function ThemeMapPage() {
  const { mapId } = useParams();
  const { mapById, placesForMap, routes, markVisited, addPlace, refresh, capabilities } = useTravel();
  const navigate = useNavigate();
  const map = mapById(mapId);
  const [selected, setSelected] = useState<Place | undefined>();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "unvisited" | "want">("all");
  const [view, setView] = useState<"map" | "list">("map");
  const [showAdd, setShowAdd] = useState(false);
  const [toast, setToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("已记录为今天去过，可在地点详情补照片");
  const [placeQuery, setPlaceQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AMapSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string>();
  const [pickingOnMap, setPickingOnMap] = useState(false);
  const [showAssistant, setShowAssistant] = useState(false);
  const [assistantGoal, setAssistantGoal] = useState("");
  const [assistantDraft, setAssistantDraft] = useState<RouteDraft>();
  const [assistantError, setAssistantError] = useState<string>();
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [showCollaboration, setShowCollaboration] = useState(false);
  const [collaboration, setCollaboration] = useState<CollaborationState>();
  const [inviteToken, setInviteToken] = useState<string>();
  const [collaborationError, setCollaborationError] = useState<string>();
  const [collaborationBusy, setCollaborationBusy] = useState(false);
  const places = map ? placesForMap(map.id) : [];
  const visible = useMemo(
    () => places.filter((place) => {
      const matchesQuery = `${place.name} ${place.tags.join(" ")}`.includes(query);
      const matchesFilter = filter === "all" ||
        (filter === "unvisited" && !place.visitedBy.includes("me")) ||
        (filter === "want" && ["want", "planned"].includes(place.preference));
      return matchesQuery && matchesFilter;
    }),
    [filter, places, query]
  );

  if (!map) {
    return (
      <div className="content-page">
        <EmptyState icon={<MapIcon />} title="没有找到这张地图">
          它可能已归档，或者当前演示数据里还不存在。
        </EmptyState>
      </div>
    );
  }

  const progress = places.length ? Math.round((map.completed / places.length) * 100) : 0;
  const mapRoute = routes.find((route) => route.mapId === map.id);
  const activeMapId = map.id;
  const activeMapCity = map.city;

  async function mark(place: Place) {
    try {
      await markVisited(place.id, activeMapId);
      setToastMessage("已记录为今天去过，可在地点详情补照片");
      setToast(true);
      window.setTimeout(() => setToast(false), 2200);
    } catch (error) {
      setToastMessage(error instanceof Error ? error.message : "标记失败");
      setToast(true);
    }
  }

  async function searchPlaces(event: FormEvent) {
    event.preventDefault();
    if (!placeQuery.trim()) return;
    setSearching(true);
    setSearchError(undefined);
    try {
      setSearchResults(await searchAMapPlaces(placeQuery, activeMapCity));
    } catch (error) {
      setSearchResults([]);
      setSearchError(error instanceof Error ? error.message : "地点搜索失败");
    } finally {
      setSearching(false);
    }
  }

  async function saveSearchResult(result: AMapSearchResult) {
    setSearching(true);
    setSearchError(undefined);
    try {
      const place = await addPlace(activeMapId, {
        name: result.name,
        address: result.address,
        city: result.city || activeMapCity,
        district: result.district || "",
        category: result.category,
        providerPlaceId: result.providerPlaceId,
        longitude: result.coordinate.longitude,
        latitude: result.coordinate.latitude
      });
      setSelected(place);
      setShowAdd(false);
      setPickingOnMap(false);
      setPlaceQuery("");
      setSearchResults([]);
      setToastMessage(`已添加“${place.name}”`);
      setToast(true);
      window.setTimeout(() => setToast(false), 2200);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "保存地点失败");
    } finally {
      setSearching(false);
    }
  }

  async function chooseMapPoint(coordinate: MapCoordinate) {
    setPickingOnMap(false);
    setShowAdd(true);
    setSearching(true);
    setSearchError(undefined);
    try {
      const result = await reverseGeocodeAMap(coordinate);
      setPlaceQuery(result.name);
      setSearchResults([result]);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "无法识别这个位置");
    } finally {
      setSearching(false);
    }
  }

  async function generateRouteDraft(event: FormEvent) {
    event.preventDefault();
    if (!assistantGoal.trim()) return;
    setAssistantBusy(true);
    setAssistantError(undefined);
    try {
      setAssistantDraft(await createAssistantRouteDraft(activeMapId, { goal: assistantGoal, mode: "walking" }));
    } catch (error) {
      setAssistantError(error instanceof Error ? error.message : "路线草案生成失败");
    } finally {
      setAssistantBusy(false);
    }
  }

  async function applyDraft() {
    if (!assistantDraft) return;
    setAssistantBusy(true);
    setAssistantError(undefined);
    try {
      const result = await applyAgentDraft(assistantDraft.id);
      await refresh();
      setShowAssistant(false);
      navigate(`/routes/${result.route.id}`);
    } catch (error) {
      setAssistantError(error instanceof Error ? error.message : "路线草案应用失败");
    } finally {
      setAssistantBusy(false);
    }
  }

  async function openCollaboration() {
    setShowCollaboration(true);
    setCollaborationBusy(true);
    setCollaborationError(undefined);
    try {
      setCollaboration(await loadCollaboration(activeMapId));
    } catch (error) {
      setCollaborationError(error instanceof Error ? error.message : "协作信息加载失败");
    } finally {
      setCollaborationBusy(false);
    }
  }

  async function makeInvitation() {
    setCollaborationBusy(true);
    setCollaborationError(undefined);
    try {
      const invitation = await createMapInvitation(activeMapId);
      setInviteToken(invitation.token);
    } catch (error) {
      setCollaborationError(error instanceof Error ? error.message : "邀请创建失败");
    } finally {
      setCollaborationBusy(false);
    }
  }

  return (
    <div className="theme-map-page">
      <header className="theme-map-header" style={{ "--theme-accent": map.accent } as React.CSSProperties}>
        <button className="icon-button back" type="button" onClick={() => navigate("/maps")} aria-label="返回主题地图">
          <ArrowLeft size={20} />
        </button>
        <div className="theme-title-block">
          <span className="theme-monogram">{map.emoji}</span>
          <div>
            <span className="eyebrow">{map.city} · 使用中</span>
            <h1>{map.title}</h1>
            <p>{map.subtitle}</p>
          </div>
        </div>
        <div className="theme-header-stats">
          <ProgressRing value={progress} label="我的进度" />
          <AvatarStack members={map.members} label={`${map.members.length} 位成员`} />
        </div>
        <button className="collab-button" type="button" onClick={() => void openCollaboration()}><UserPlus size={16} /> 同行</button>
      </header>

      <div className="theme-tabs-row">
        <div className="segmented-control">
          <button type="button" className={view === "map" ? "active" : ""} onClick={() => setView("map")}>
            <MapIcon size={16} /> 地图
          </button>
          <button type="button" className={view === "list" ? "active" : ""} onClick={() => setView("list")}>
            <List size={16} /> 列表
          </button>
        </div>
        <div className="theme-quick-stats">
          <span><strong>{places.length}</strong> 地点</span>
          <span><strong>{places.filter((place) => place.visitedBy.includes("me")).length}</strong> 去过</span>
          <span><strong>{places.filter((place) => place.preference === "planned").length}</strong> 计划</span>
          {map.period && <span>{map.period}</span>}
        </div>
        {capabilities.llm && (map.routeEnabled || mapRoute) && places.length >= 2 && <button className="assistant-action" type="button" onClick={() => setShowAssistant(true)}><Sparkles size={16} /> 整理路线</button>}
        <button className="primary-button" type="button" onClick={() => setShowAdd(true)}><Plus size={17} /> 添加地点</button>
      </div>

      <div className={`theme-map-body view-${view}`}>
        <aside className="theme-points-panel">
          <div className="search-field">
            <Search size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索这张地图" />
          </div>
          <div className="filter-scroll compact-filters">
            <button className={filter === "all" ? "active" : ""} type="button" onClick={() => setFilter("all")}>全部 {places.length}</button>
            <button className={filter === "unvisited" ? "active" : ""} type="button" onClick={() => setFilter("unvisited")}>还没去</button>
            <button className={filter === "want" ? "active" : ""} type="button" onClick={() => setFilter("want")}>想去</button>
          </div>
          <div className="panel-summary">
            <strong>{visible.length} 个地点</strong>
            <span>按添加顺序</span>
          </div>
          <div className="place-list">
            {visible.map((place) => (
              <PlaceListItem key={place.id} place={place} active={selected?.id === place.id} onClick={() => setSelected(place)} />
            ))}
          </div>
          {mapRoute && (
            <button className="route-summary-card" type="button" onClick={() => navigate(`/routes/${mapRoute.id}`)}>
              <span><Route size={18} /></span>
              <div><strong>{mapRoute.title}</strong><small>{mapRoute.stopIds.length} 站 · {mapRoute.distance}</small></div>
              <span>→</span>
            </button>
          )}
        </aside>

        <div className="theme-map-canvas">
          <MapSurface places={visible} selectedId={selected?.id} onSelect={setSelected} city={map.city} onMapClick={pickingOnMap ? chooseMapPoint : undefined} />
          {pickingOnMap && <div className="map-pick-banner"><MapPin size={17} /><span>点击地图选择一个位置</span><button type="button" onClick={() => setPickingOnMap(false)}>取消</button></div>}
          {selected && (
            <article className="point-drawer">
              <header>
                <div>
                  <span className="eyebrow">{selected.category} · {selected.district}</span>
                  <h2>{selected.name}</h2>
                </div>
                <button className="icon-button" type="button" onClick={() => setSelected(undefined)} aria-label="收起地点详情">×</button>
              </header>
              <p>{selected.note}</p>
              <div className="tag-row">{selected.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              <div className="member-consensus">
                <AvatarStack members={map.members} />
                <span>{map.members.length > 1 ? "同行人可以分别标记自己的意愿" : "状态与到访记录只属于你"}</span>
              </div>
              <div className="drawer-actions">
                {!selected.visitedBy.includes("me") && (
                  <button className="primary-button" type="button" onClick={() => mark(selected)}><Check size={17} /> 标记去过</button>
                )}
                <button className="secondary-button" type="button" onClick={() => navigate(`/places/${selected.id}`)}>查看详情</button>
              </div>
            </article>
          )}
        </div>
      </div>

      {showAdd && (
        <Modal title="添加地点" onClose={() => setShowAdd(false)}>
          <div className="add-place-search">
            <form className="add-place-query" onSubmit={searchPlaces}>
              <div className="search-field wide"><Search size={18} /><input autoFocus value={placeQuery} onChange={(event) => setPlaceQuery(event.target.value)} placeholder={`搜索${map.city}的地点`} aria-label="地点名称或地址" /></div>
              <button className="primary-button" type="submit" disabled={searching || !placeQuery.trim()}>{searching ? <LoaderCircle className="spin" size={17} /> : <Search size={17} />} 搜索</button>
            </form>
            <p>搜索结果将由 MapProvider 匹配高德地点；保存前可以确认名称、地址和坐标。</p>
            {searchError && <div className="map-search-error">{searchError}</div>}
            {searchResults.length > 0 && <div className="map-search-results" aria-label="地点搜索结果">
              {searchResults.map((result, index) => <button key={`${result.providerPlaceId ?? result.name}-${index}`} type="button" onClick={() => saveSearchResult(result)}><MapPin size={18} /><span><strong>{result.name}</strong><small>{[result.district, result.address].filter(Boolean).join(" · ") || "地图选点"}</small></span><Plus size={17} /></button>)}
            </div>}
            {!searching && searchResults.length === 0 && !searchError && <>
            <div className="add-methods">
              <button type="button" onClick={() => { setShowAdd(false); setPickingOnMap(true); }}><MapIcon size={19} /><span><strong>在地图上选点</strong><small>点击底图后会自动解析地址</small></span></button>
            </div>
            </>}
          </div>
        </Modal>
      )}
      {showAssistant && (
        <Modal title="整理路线草案" onClose={() => setShowAssistant(false)}>
          {!assistantDraft ? (
            <form className="form-stack" onSubmit={generateRouteDraft}>
              <div className="assistant-boundary"><Sparkles size={18} /><p>助手只会使用这张地图中已有的地点生成草案，不会直接修改路线。</p></div>
              <label>你希望怎样走<textarea autoFocus rows={5} value={assistantGoal} onChange={(event) => setAssistantGoal(event.target.value)} placeholder="例如：安排半天步行美食路线，早餐开始，最后到夜市，不要太赶。" /></label>
              <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setShowAssistant(false)}>取消</button><button className="primary-button" type="submit" disabled={assistantBusy || !assistantGoal.trim()}>{assistantBusy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />} 生成草案</button></div>
              {assistantError && <div className="map-search-error">{assistantError}</div>}
            </form>
          ) : (
            <div className="route-draft-preview">
              <span className="eyebrow">PENDING DRAFT</span>
              <h3>{assistantDraft.payload.title}</h3>
              <p>{assistantDraft.payload.summary}</p>
              <ol>{assistantDraft.payload.ordered_place_ids.map((placeId) => <li key={placeId}>{places.find((place) => place.id === placeId)?.name ?? "未知地点"}</li>)}</ol>
              <small>应用后才会生成正式路线，你仍然可以继续调整顺序。</small>
              <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setAssistantDraft(undefined)}>重新生成</button><button className="primary-button" type="button" onClick={() => void applyDraft()} disabled={assistantBusy}>{assistantBusy ? "应用中…" : "应用到路线"}</button></div>
              {assistantError && <div className="map-search-error">{assistantError}</div>}
            </div>
          )}
        </Modal>
      )}
      {showCollaboration && (
        <Modal title="同行协作" onClose={() => setShowCollaboration(false)}>
          <div className="collaboration-panel">
            {collaborationBusy && !collaboration && <div className="inline-empty"><LoaderCircle className="spin" size={20} /><span>正在读取成员…</span></div>}
            {collaboration && <div className="member-list">{collaboration.members.map((member) => <div key={member.id}><span>{member.name.slice(0, 1)}</span><div><strong>{member.name}</strong><small>@{member.username}</small></div><em>{member.role === "owner" ? "所有者" : member.role === "editor" ? "可编辑" : "只读"}</em></div>)}</div>}
            {collaboration?.my_role === "owner" && !inviteToken && <button className="secondary-button full-width" type="button" onClick={() => void makeInvitation()} disabled={collaborationBusy}><UserPlus size={16} /> 创建 7 天有效邀请</button>}
            {inviteToken && <div className="invite-token-box"><span>邀请令牌只显示这一次</span><code>{inviteToken}</code><button className="primary-button" type="button" onClick={() => { void navigator.clipboard.writeText(inviteToken); setToastMessage("邀请令牌已复制"); setToast(true); window.setTimeout(() => setToast(false), 2200); }}><Copy size={16} /> 复制邀请令牌</button></div>}
            {collaborationError && <div className="map-search-error">{collaborationError}</div>}
          </div>
        </Modal>
      )}
      {toast && <Toast>{toastMessage}</Toast>}
    </div>
  );
}
