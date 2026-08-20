import {
  ArrowLeft, CalendarClock, Check, ChevronDown, ChevronUp, ClipboardPaste, Copy,
  ExternalLink, Heart, List, LoaderCircle, Map as MapIcon, MapPinned, MapPin,
  Navigation, Plus, Route, Search, SlidersHorizontal, Sparkles, UserPlus, X
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  CollaborationState, RouteDraft, applyAgentDraft, createAssistantRouteDraft,
  createMapInvitation, loadCollaboration
} from "../api";
import { MapSurface } from "../components/MapSurface";
import { PlaceListItem } from "../components/PlaceListItem";
import { AvatarStack, EmptyState, Modal, Toast } from "../components/Shared";
import { VisitDialog } from "../components/VisitDialog";
import {
  AMapSearchResult, MapCoordinate, reverseGeocodeAMap, searchAMapPlaces
} from "../map/amapRuntime";
import { mapProviderForCountry } from "../map/provider";
import { useTravel } from "../state/TravelContext";
import { Place, Preference } from "../types";

type FilterMode = "all" | "unvisited" | "want" | "planned" | "visited";
type SheetSnap = "peek" | "half" | "full";
type AddMode = "search" | "map" | "list";

const filters: Array<{ value: FilterMode; label: string }> = [
  { value: "all", label: "全部" }, { value: "unvisited", label: "还没去" },
  { value: "want", label: "想去" }, { value: "planned", label: "计划去" },
  { value: "visited", label: "已去过" }
];
const preferences: Array<{ value: Preference; label: string }> = [
  { value: "none", label: "未标记" }, { value: "want", label: "想去" },
  { value: "planned", label: "计划去" }, { value: "skip", label: "暂不考虑" }
];

export function ThemeMapPage() {
  const { mapId } = useParams();
  const {
    mapById, placesForMap, routes, visits, setPreference, recordVisit, addPlace,
    refresh, capabilities
  } = useTravel();
  const navigate = useNavigate();
  const map = mapById(mapId);
  const [selectedId, setSelectedId] = useState<string>();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [category, setCategory] = useState("all");
  const [view, setView] = useState<"map" | "list">("map");
  const [sheetSnap, setSheetSnap] = useState<SheetSnap>("half");
  const [showAdd, setShowAdd] = useState(false);
  const [addMode, setAddMode] = useState<AddMode>("search");
  const [visitPlace, setVisitPlace] = useState<Place>();
  const [toastMessage, setToastMessage] = useState<string>();
  const [toastActionPlaceId, setToastActionPlaceId] = useState<string>();
  const [placeQuery, setPlaceQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AMapSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string>();
  const [pickingOnMap, setPickingOnMap] = useState(false);
  const [pastedList, setPastedList] = useState("");
  const [listDraft, setListDraft] = useState<AMapSearchResult[]>([]);
  const [listMisses, setListMisses] = useState<string[]>([]);
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
  const selected = places.find((place) => place.id === selectedId);
  const categories = useMemo(() => Array.from(new Set(places.map((place) => place.category))).sort(), [places]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return places.filter((place) => {
      const visited = place.visitedBy.includes("me");
      const matchesQuery = !normalized || [place.name, place.address, place.district, place.category, ...place.tags]
        .join(" ").toLocaleLowerCase().includes(normalized);
      const matchesFilter = filter === "all" || (filter === "unvisited" && !visited) ||
        (filter === "visited" && visited) || (filter === "want" && place.preference === "want") ||
        (filter === "planned" && place.preference === "planned");
      return matchesQuery && matchesFilter && (category === "all" || place.category === category);
    });
  }, [category, filter, places, query]);

  if (!map) return <div className="content-page"><EmptyState icon={<MapIcon />} title="没有找到这张地图">它可能已归档，或者当前数据里还不存在。</EmptyState></div>;

  const activeMap = map;
  const mapRoute = routes.find((route) => route.mapId === activeMap.id);
  const mapProvider = mapProviderForCountry();
  const visitedCount = places.filter((place) => place.visitedBy.includes("me")).length;
  const plannedCount = places.filter((place) => place.preference === "planned").length;
  const progressValue = places.length ? Math.round((visitedCount / places.length) * 100) : 0;

  function notify(message: string, actionPlaceId?: string) {
    setToastMessage(message); setToastActionPlaceId(actionPlaceId);
    window.setTimeout(() => { setToastMessage(undefined); setToastActionPlaceId(undefined); }, actionPlaceId ? 5000 : 2400);
  }
  function choosePlace(place: Place) { setSelectedId(place.id); setSheetSnap("peek"); }

  async function searchPlaces(event: FormEvent) {
    event.preventDefault(); if (!placeQuery.trim()) return;
    setSearching(true); setSearchError(undefined);
    try { setSearchResults(await searchAMapPlaces(placeQuery, activeMap.city)); }
    catch (error) { setSearchResults([]); setSearchError(error instanceof Error ? error.message : "地点搜索失败"); }
    finally { setSearching(false); }
  }

  async function saveSearchResult(result: AMapSearchResult, close = true) {
    setSearching(true); setSearchError(undefined);
    try {
      const place = await addPlace(activeMap.id, {
        name: result.name, address: result.address, city: result.city || activeMap.city,
        district: result.district || "", category: result.category,
        providerPlaceId: result.providerPlaceId, longitude: result.coordinate.longitude,
        latitude: result.coordinate.latitude
      });
      setSelectedId(place.id); setPickingOnMap(false);
      if (close) { setShowAdd(false); setPlaceQuery(""); setSearchResults([]); notify(`已添加“${place.name}”`); }
    } catch (error) { setSearchError(error instanceof Error ? error.message : "保存地点失败"); throw error; }
    finally { setSearching(false); }
  }

  async function chooseMapPoint(coordinate: MapCoordinate) {
    setPickingOnMap(false); setShowAdd(true); setAddMode("search"); setSearching(true); setSearchError(undefined);
    try { const result = await reverseGeocodeAMap(coordinate); setPlaceQuery(result.name); setSearchResults([result]); }
    catch (error) { setSearchError(error instanceof Error ? error.message : "无法识别这个位置"); }
    finally { setSearching(false); }
  }

  async function previewPastedList(event: FormEvent) {
    event.preventDefault();
    const names = Array.from(new Set(pastedList.split(/\r?\n|、|，/).map((item) => item.trim()).filter(Boolean))).slice(0, 20);
    if (!names.length) return;
    setSearching(true); setSearchError(undefined); setListDraft([]); setListMisses([]);
    const matched: AMapSearchResult[] = []; const missed: string[] = [];
    for (const name of names) {
      try { const results = await searchAMapPlaces(name, activeMap.city, 3); if (results[0]) matched.push(results[0]); else missed.push(name); }
      catch { missed.push(name); }
    }
    setListDraft(matched); setListMisses(missed);
    if (!matched.length) setSearchError("清单中没有可由高德核验的地点");
    setSearching(false);
  }

  async function applyListDraft() {
    setSearching(true); setSearchError(undefined); const count = listDraft.length;
    try {
      for (const result of listDraft) await saveSearchResult(result, false);
      setListDraft([]); setPastedList(""); setShowAdd(false); notify(`已添加 ${count} 个经高德核验的地点`);
    } catch (error) { setSearchError(error instanceof Error ? error.message : "清单导入失败"); }
    finally { setSearching(false); }
  }

  async function generateRouteDraft(event: FormEvent) {
    event.preventDefault(); if (!assistantGoal.trim()) return;
    setAssistantBusy(true); setAssistantError(undefined);
    try { setAssistantDraft(await createAssistantRouteDraft(activeMap.id, { goal: assistantGoal, mode: "walking" })); }
    catch (error) { setAssistantError(error instanceof Error ? error.message : "路线草案生成失败"); }
    finally { setAssistantBusy(false); }
  }
  async function applyDraft() {
    if (!assistantDraft) return; setAssistantBusy(true); setAssistantError(undefined);
    try { const result = await applyAgentDraft(assistantDraft.id); await refresh(); setShowAssistant(false); navigate(`/routes/${result.route.id}`); }
    catch (error) { setAssistantError(error instanceof Error ? error.message : "路线草案应用失败"); }
    finally { setAssistantBusy(false); }
  }
  async function openCollaboration() {
    setShowCollaboration(true); setCollaborationBusy(true); setCollaborationError(undefined);
    try { setCollaboration(await loadCollaboration(activeMap.id)); }
    catch (error) { setCollaborationError(error instanceof Error ? error.message : "协作信息加载失败"); }
    finally { setCollaborationBusy(false); }
  }
  async function makeInvitation() {
    setCollaborationBusy(true); setCollaborationError(undefined);
    try { const invitation = await createMapInvitation(activeMap.id); setInviteToken(invitation.token); }
    catch (error) { setCollaborationError(error instanceof Error ? error.message : "邀请创建失败"); }
    finally { setCollaborationBusy(false); }
  }

  const routePlaces = mapRoute ? mapRoute.stopIds.map((id) => places.find((place) => place.id === id)).filter(Boolean) as Place[] : [];
  return (
    <div className="theme-map-page">
      <header className="theme-map-header">
        <button className="icon-button back" type="button" onClick={() => navigate("/maps")} aria-label="返回主题列表"><ArrowLeft size={19} /></button>
        <span className="theme-monogram"><MapPinned size={20} /></span>
        <div className="theme-title-block"><div><h1>{map.title}</h1><span>{map.city}</span></div><p>{map.subtitle || "一张私人主题地图"}</p></div>
        <div className="theme-progress-compact" aria-label={`完成进度 ${visitedCount}/${places.length}`}><div><strong>{visitedCount} / {places.length}</strong><span>已去</span></div><span><i style={{ width: `${progressValue}%` }} /></span></div>
        <button className="collab-button" type="button" onClick={() => void openCollaboration()}><AvatarStack members={map.members} /><span>同行</span><UserPlus size={15} /></button>
      </header>

      <div className="theme-tabs-row">
        <div className="segmented-control"><button type="button" className={view === "map" ? "active" : ""} onClick={() => { setView("map"); setSheetSnap("peek"); }}><MapIcon size={15} /> 地图</button><button type="button" className={view === "list" ? "active" : ""} onClick={() => { setView("list"); setSheetSnap("full"); }}><List size={15} /> 列表</button></div>
        <div className="theme-quick-stats"><span><strong>{places.length}</strong> 地点</span><span><strong>{visitedCount}</strong> 已去</span><span><strong>{plannedCount}</strong> 计划</span>{map.period && <span className="period-stat">{map.period}</span>}</div>
        <button className="assistant-action" type="button" disabled={!mapRoute && !capabilities.llm} title={!mapRoute && !capabilities.llm ? "智能路线能力尚未配置" : undefined} onClick={() => mapRoute ? navigate(`/routes/${mapRoute.id}`) : setShowAssistant(true)}><Sparkles size={15} /> 整理路线</button>
        <button className="primary-button add-place-desktop" type="button" onClick={() => setShowAdd(true)}><Plus size={16} /> 添加地点</button>
      </div>

      <div className={`theme-map-body view-${view}`}>
        <aside className={`theme-points-panel sheet-${sheetSnap}`}>
          <button className="sheet-handle" type="button" onClick={() => setSheetSnap(sheetSnap === "peek" ? "half" : sheetSnap === "half" ? "full" : "peek")} aria-label="调整地点列表高度"><span />{sheetSnap === "full" ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</button>
          <div className="theme-panel-tools"><div className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索地点、标签" />{query && <button type="button" onClick={() => setQuery("")} aria-label="清空搜索"><X size={14} /></button>}</div><label className="category-filter"><SlidersHorizontal size={15} /><select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="按分类筛选"><option value="all">全部分类</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div>
          <div className="filter-scroll compact-filters">{filters.map((item) => <button key={item.value} className={filter === item.value ? "active" : ""} type="button" onClick={() => setFilter(item.value)}>{item.label}</button>)}</div>
          <div className="panel-summary"><strong>{visible.length} 个地点</strong><span>按添加顺序</span></div>
          <div className="place-list">{visible.map((place, index) => { const routeIndex = mapRoute?.stopIds.indexOf(place.id); return <PlaceListItem key={place.id} place={place} index={index} active={selectedId === place.id} routeIndex={routeIndex !== undefined && routeIndex >= 0 ? routeIndex : undefined} onClick={() => choosePlace(place)} />; })}{!visible.length && <div className="inline-empty"><Search size={20} /><strong>没有匹配地点</strong><span>尝试清空搜索或切换筛选。</span></div>}</div>
          {mapRoute && <button className="route-summary-card" type="button" onClick={() => navigate(`/routes/${mapRoute.id}`)}><span><Route size={17} /></span><div><strong>{mapRoute.title}</strong><small>{mapRoute.stopIds.length} 站 · {mapRoute.distance}</small></div><ExternalLink size={15} /></button>}
        </aside>

        <main className="theme-map-canvas">
          <MapSurface places={visible} selectedId={selectedId} onSelect={choosePlace} routePlaces={routePlaces} city={map.city} onMapClick={pickingOnMap ? chooseMapPoint : undefined} />
          {pickingOnMap && <div className="map-pick-banner"><MapPin size={16} /><span>点击地图选择一个位置</span><button type="button" onClick={() => setPickingOnMap(false)}>取消</button></div>}
          {!selected && <button className="map-add-fab" type="button" onClick={() => setShowAdd(true)} aria-label="添加地点"><Plus size={22} /></button>}
          {selected && <article className="point-drawer"><button className="card-close" type="button" onClick={() => setSelectedId(undefined)} aria-label="关闭地点卡片"><X size={17} /></button><div className="point-cover"><MapPinned size={26} /><span>{selected.category}</span></div><div className="point-drawer-content"><header><div><span className="eyebrow">{selected.category} · {selected.district}</span><h2>{selected.name}</h2><small><MapPin size={13} /> {selected.address || `${selected.city}${selected.district}`}</small></div></header><p>{selected.note || "还没有共享备注，可以在详情中补充。"}</p><div className="point-facts">{selected.recommended && <span><strong>推荐</strong>{selected.recommended}</span>}{selected.price && <span><strong>人均</strong>{selected.price}</span>}<span><strong>同行</strong>{map.members.length > 1 ? `${map.members.length} 人独立记录` : "仅自己"}</span></div><div className="tag-row">{selected.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}</div><div className="inline-preferences" aria-label="我的意愿">{preferences.map((item) => <button key={item.value} className={selected.preference === item.value ? `active preference-${item.value}` : ""} type="button" onClick={() => void setPreference(selected.id, item.value, map.id).catch((error) => notify(error instanceof Error ? error.message : "意愿保存失败"))}>{item.value === "want" ? <Heart size={13} /> : item.value === "planned" ? <CalendarClock size={13} /> : null}{item.label}</button>)}</div><div className="drawer-actions">{!selected.visitedBy.includes("me") ? <button className="primary-button" type="button" onClick={() => setVisitPlace(selected)}><Check size={16} /> 标记去过</button> : <span className="visited-summary"><Check size={15} /> 已去过</span>}<button className="secondary-button" type="button" onClick={() => navigate(`/places/${selected.id}`)}>查看详情</button><a className="icon-button" href={mapProvider.externalPlaceUrl(selected)} target="_blank" rel="noreferrer" aria-label="在高德地图打开"><Navigation size={17} /></a></div></div></article>}
        </main>
      </div>

      {showAdd && <Modal title="添加地点" onClose={() => setShowAdd(false)}><div className="add-place-search"><div className="add-mode-tabs"><button type="button" className={addMode === "search" ? "active" : ""} onClick={() => setAddMode("search")}><Search size={16} /> 高德搜索</button><button type="button" className={addMode === "map" ? "active" : ""} onClick={() => setAddMode("map")}><MapIcon size={16} /> 地图选点</button><button type="button" className={addMode === "list" ? "active" : ""} onClick={() => setAddMode("list")}><ClipboardPaste size={16} /> 粘贴清单</button></div>
        {addMode === "search" && <><form className="add-place-query" onSubmit={searchPlaces}><div className="search-field wide"><Search size={17} /><input autoFocus value={placeQuery} onChange={(event) => setPlaceQuery(event.target.value)} placeholder={`搜索${map.city}的地点`} /></div><button className="primary-button" type="submit" disabled={searching || !placeQuery.trim()}>{searching ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />} 搜索</button></form><p>结果来自高德地点服务，确认名称、分类、行政区和地址后再加入主题。</p>{searchResults.length > 0 && <div className="map-search-results">{searchResults.map((result, index) => <button key={`${result.providerPlaceId ?? result.name}-${index}`} type="button" onClick={() => void saveSearchResult(result)}><MapPin size={17} /><span><strong>{result.name}</strong><small>{result.category || "地点"} · {[result.district, result.address].filter(Boolean).join(" · ")}</small></span><Plus size={16} /></button>)}</div>}</>}
        {addMode === "map" && <div className="add-map-method"><MapPinned size={28} /><h3>在真实地图上选择位置</h3><p>关闭面板后点击地图，高德会反查地点与地址，仍需你确认才能保存。</p><button className="primary-button" type="button" onClick={() => { setShowAdd(false); setPickingOnMap(true); }}>开始选点</button></div>}
        {addMode === "list" && <form className="paste-list-form" onSubmit={previewPastedList}><div className="assistant-boundary"><ClipboardPaste size={17} /><p>每行一个地点，最多 20 个。系统只采用高德核验结果，不由模型编造 POI 或坐标。</p></div><textarea rows={7} value={pastedList} onChange={(event) => { setPastedList(event.target.value); setListDraft([]); }} placeholder={`黔灵山公园\n青云市集\n甲秀楼`} />{listDraft.length > 0 && <div className="list-draft"><header><strong>已核验 {listDraft.length} 个地点</strong>{listMisses.length > 0 && <span>{listMisses.length} 个未匹配</span>}</header>{listDraft.map((item) => <div key={`${item.providerPlaceId}-${item.name}`}><MapPin size={15} /><span><strong>{item.name}</strong><small>{item.district} · {item.address}</small></span><Check size={15} /></div>)}</div>}<div className="form-actions">{listDraft.length > 0 && <button className="secondary-button" type="button" onClick={() => setListDraft([])}>重新核验</button>}<button className="primary-button" type={listDraft.length ? "button" : "submit"} disabled={searching || !pastedList.trim()} onClick={listDraft.length ? () => void applyListDraft() : undefined}>{searching ? "核验中…" : listDraft.length ? `确认添加 ${listDraft.length} 个` : "生成核验草案"}</button></div></form>}{searchError && <div className="map-search-error">{searchError}</div>}</div></Modal>}

      {visitPlace && <VisitDialog placeName={visitPlace.name} visits={visits.filter((visit) => visit.placeId === visitPlace.id)} onClose={() => setVisitPlace(undefined)} onReuse={() => { setVisitPlace(undefined); navigate(`/places/${visitPlace.id}`); }} onSave={async (draft) => { await recordVisit(visitPlace.id, { mapId: map.id, ...draft }); setVisitPlace(undefined); notify("已记录到访，照片和个人记录仍保持私密", visitPlace.id); }} />}

      {showAssistant && <Modal title="整理路线草案" onClose={() => setShowAssistant(false)}>{!assistantDraft ? <form className="form-stack" onSubmit={generateRouteDraft}><div className="assistant-boundary"><Sparkles size={17} /><p>助手只使用这张主题中已核验的地点生成待确认草案，不会直接修改正式路线。</p></div><label>路线目标<textarea autoFocus rows={4} value={assistantGoal} onChange={(event) => setAssistantGoal(event.target.value)} placeholder="例如：半天步行路线，最后到夜市，不要太赶。" /></label><div className="form-actions"><button className="secondary-button" type="button" onClick={() => setShowAssistant(false)}>取消</button><button className="primary-button" type="submit" disabled={assistantBusy || !assistantGoal.trim()}>{assistantBusy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />} 生成草案</button></div>{assistantError && <div className="map-search-error">{assistantError}</div>}</form> : <div className="route-draft-preview"><span className="eyebrow">待确认草案</span><h3>{assistantDraft.payload.title}</h3><p>{assistantDraft.payload.summary}</p><ol>{assistantDraft.payload.ordered_place_ids.map((placeId) => <li key={placeId}>{places.find((place) => place.id === placeId)?.name ?? "未知地点"}</li>)}</ol><small>应用后才会创建正式路线，之后仍可调整顺序。</small><div className="form-actions"><button className="secondary-button" type="button" onClick={() => setAssistantDraft(undefined)}>重新生成</button><button className="primary-button" type="button" onClick={() => void applyDraft()} disabled={assistantBusy}>{assistantBusy ? "应用中…" : "应用到路线"}</button></div>{assistantError && <div className="map-search-error">{assistantError}</div>}</div>}</Modal>}

      {showCollaboration && <Modal title="同行协作" onClose={() => setShowCollaboration(false)}><div className="collaboration-panel">{collaborationBusy && !collaboration && <div className="inline-empty"><LoaderCircle className="spin" size={20} /><span>正在读取成员…</span></div>}{collaboration && <div className="member-list">{collaboration.members.map((member) => <div key={member.id}><span>{member.name.slice(0, 1)}</span><div><strong>{member.name}</strong><small>@{member.username}</small></div><em>{member.role === "owner" ? "所有者" : member.role === "editor" ? "可编辑" : "只读"}</em></div>)}</div>}{collaboration?.my_role === "owner" && !inviteToken && <button className="secondary-button full-width" type="button" onClick={() => void makeInvitation()} disabled={collaborationBusy}><UserPlus size={16} /> 创建 7 天有效邀请</button>}{inviteToken && <div className="invite-token-box"><span>邀请令牌只显示这一次</span><code>{inviteToken}</code><button className="primary-button" type="button" onClick={() => { void navigator.clipboard.writeText(inviteToken); notify("邀请令牌已复制"); }}><Copy size={16} /> 复制邀请令牌</button></div>}{collaborationError && <div className="map-search-error">{collaborationError}</div>}</div></Modal>}
      {toastMessage && <Toast action={toastActionPlaceId ? <button type="button" onClick={() => navigate(`/places/${toastActionPlaceId}`)}>补照片和记录</button> : undefined}>{toastMessage}</Toast>}
    </div>
  );
}
