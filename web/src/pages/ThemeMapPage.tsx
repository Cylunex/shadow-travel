import {
  ArrowLeft,
  Check,
  ChevronDown,
  Copy,
  Filter,
  List,
  LoaderCircle,
  Map as MapIcon,
  MapPin,
  MoreHorizontal,
  Plus,
  Route,
  Search,
  Settings2,
  Share2,
  UserPlus,
  Users
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { PlaceListItem } from "../components/PlaceListItem";
import { AvatarStack, EmptyState, Modal, ProgressRing, Toast } from "../components/Shared";
import { AMapSearchResult, MapCoordinate, reverseGeocodeAMap, searchAMapPlaces } from "../map/amapRuntime";
import { useTravel } from "../state/TravelContext";
import { Place } from "../types";

export function ThemeMapPage() {
  const { mapId } = useParams();
  const { mapById, placesForMap, routes, markVisited, addPlace } = useTravel();
  const navigate = useNavigate();
  const map = mapById(mapId);
  const [selected, setSelected] = useState<Place | undefined>();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"map" | "list">("map");
  const [showAdd, setShowAdd] = useState(false);
  const [toast, setToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("已记录为今天去过，可在地点详情补照片");
  const [placeQuery, setPlaceQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AMapSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string>();
  const [pickingOnMap, setPickingOnMap] = useState(false);
  const places = map ? placesForMap(map.id) : [];
  const visible = useMemo(
    () => places.filter((place) => `${place.name} ${place.tags.join(" ")}`.includes(query)),
    [places, query]
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

  function mark(place: Place) {
    markVisited(place.id, activeMapId);
    setToastMessage("已记录为今天去过，可在地点详情补照片");
    setToast(true);
    window.setTimeout(() => setToast(false), 2200);
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

  function saveSearchResult(result: AMapSearchResult) {
    const place = addPlace(activeMapId, {
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
        <div className="theme-header-actions">
          <button className="secondary-button" type="button"><UserPlus size={17} /> 邀请同行</button>
          <button className="icon-button" type="button" aria-label="分享"><Share2 size={18} /></button>
          <button className="icon-button" type="button" aria-label="更多"><MoreHorizontal size={20} /></button>
        </div>
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
        <button className="primary-button" type="button" onClick={() => setShowAdd(true)}><Plus size={17} /> 添加地点</button>
      </div>

      <div className={`theme-map-body view-${view}`}>
        <aside className="theme-points-panel">
          <div className="search-field">
            <Search size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索这张地图" />
          </div>
          <div className="filter-scroll compact-filters">
            <button className="active" type="button">全部 {places.length}</button>
            <button type="button">还没去</button>
            <button type="button">想去</button>
            <button type="button"><Filter size={14} /></button>
          </div>
          <div className="panel-summary">
            <span>按添加时间</span>
            <button type="button">默认排序 <ChevronDown size={14} /></button>
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
          <div className="map-layer-control">
            <button type="button" className="active"><span className="legend-dot shared" /> 共享点位</button>
            <button type="button"><span className="legend-dot mine" /> 我的记录</button>
            <button type="button"><Users size={15} /> 同行记录</button>
          </div>
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
                <span>{selected.preference === "planned" ? "2 人计划去" : "同行意愿尚未统一"}</span>
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
              <button type="button" onClick={() => setSearchError("请先粘贴地点名称或地址；外部链接解析会在导入模块统一处理。") }><Copy size={19} /><span><strong>粘贴地图链接</strong><small>匹配后再确认，不直接信任链接内容</small></span></button>
              <button type="button" onClick={() => setSearchError("手动地点也需要名称和坐标，请先在地图上选点。") }><Settings2 size={19} /><span><strong>手动填写</strong><small>保留来源和坐标系说明</small></span></button>
            </div>
            </>}
          </div>
        </Modal>
      )}
      {toast && <Toast>{toastMessage}</Toast>}
    </div>
  );
}
