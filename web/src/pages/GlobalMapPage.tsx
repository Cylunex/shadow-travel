import {
  ArrowRight,
  Check,
  Layers3,
  List,
  Map as MapIcon,
  MapPinned,
  Plus,
  Search,
  X
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { PlaceListItem } from "../components/PlaceListItem";
import { AvatarStack } from "../components/Shared";
import { useTravel } from "../state/TravelContext";
import { Place } from "../types";

type FilterMode = "all" | "want" | "unvisited" | "visited";
type PanelMode = "maps" | "places";

export function GlobalMapPage() {
  const { maps, places, members } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [selected, setSelected] = useState<Place>();
  const [panelMode, setPanelMode] = useState<PanelMode>("maps");
  const [mobilePanel, setMobilePanel] = useState(false);

  const visiblePlaces = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return places.filter((place) => {
      const matchesQuery =
        !normalized ||
        [place.name, place.city, place.district, place.category, ...place.tags]
          .join(" ")
          .toLowerCase()
          .includes(normalized);
      const visited = place.visitedBy.includes("me");
      const matchesFilter =
        filter === "all" ||
        (filter === "want" && ["want", "planned"].includes(place.preference)) ||
        (filter === "visited" && visited) ||
        (filter === "unvisited" && !visited);
      return matchesQuery && matchesFilter;
    });
  }, [filter, places, query]);

  function choosePlace(place: Place) {
    setSelected(place);
    setMobilePanel(false);
  }

  function updateQuery(value: string) {
    setQuery(value);
    if (value.trim()) setPanelMode("places");
  }

  return (
    <div className="global-map-page">
      <header className="atlas-topbar">
        <div className="search-field atlas-search">
          <Search size={17} />
          <input value={query} onChange={(event) => updateQuery(event.target.value)} placeholder="搜索地点、城市、标签" aria-label="搜索地点、城市或标签" />
          {query && <button type="button" onClick={() => setQuery("")} aria-label="清空搜索"><X size={15} /></button>}
        </div>
        <div className="atlas-top-actions">
          {members.length > 1 && <AvatarStack members={members} label={`${members.length} 位同行人`} />}
          <button className="secondary-button" type="button" onClick={() => navigate("/maps")}><Plus size={17} /> 新建主题</button>
        </div>
      </header>

      <div className={`map-workspace${selected ? " has-detail" : ""}`}>
        <aside className={`map-list-panel atlas-panel${mobilePanel ? " mobile-open" : ""}`}>
          <div className="panel-handle" />
          <div className="atlas-panel-heading">
            <div><span className="eyebrow">MY ATLAS</span><strong>{panelMode === "maps" ? "主题地图" : "地点清单"}</strong></div>
            <button className="panel-add" type="button" onClick={() => navigate("/maps")} aria-label="新建主题地图"><Plus size={17} /></button>
          </div>
          <div className="segmented-control atlas-panel-switch">
            <button type="button" className={panelMode === "maps" ? "active" : ""} onClick={() => setPanelMode("maps")}><Layers3 size={14} /> 主题</button>
            <button type="button" className={panelMode === "places" ? "active" : ""} onClick={() => setPanelMode("places")}><MapPinned size={14} /> 地点</button>
          </div>

          {panelMode === "maps" ? (
            <div className="atlas-theme-list">
              {maps.map((map) => (
                <button key={map.id} type="button" onClick={() => navigate(`/maps/${map.id}`)} style={{ "--map-accent": map.accent } as React.CSSProperties}>
                  <span className="atlas-theme-symbol">{map.emoji}</span>
                  <span><strong>{map.title}</strong><small>{map.city} · {map.pointIds.length} 个地点</small></span>
                  <span className="atlas-theme-progress">{map.completed}/{map.pointIds.length}</span>
                </button>
              ))}
              {!maps.length && <div className="inline-empty"><Layers3 size={22} /><strong>还没有主题地图</strong><span>从一座城市或一份清单开始。</span></div>}
            </div>
          ) : (
            <>
              <div className="panel-summary"><strong>{visiblePlaces.length} 个地点</strong><span>来自 {maps.length} 张地图</span></div>
              <div className="place-list">
                {visiblePlaces.map((place) => <PlaceListItem key={place.id} place={place} active={selected?.id === place.id} onClick={() => choosePlace(place)} />)}
                {!visiblePlaces.length && <div className="inline-empty"><Search size={22} /><strong>没有匹配地点</strong><span>清空搜索或切换筛选状态。</span></div>}
              </div>
            </>
          )}
          <button className="atlas-panel-footer" type="button" onClick={() => navigate("/maps")}>管理全部主题 <ArrowRight size={15} /></button>
        </aside>

        <main className="map-stage">
          <div className="atlas-filter-bar" aria-label="地图筛选">
            {[
              ["all", "全部", places.length],
              ["want", "想去", places.filter((place) => ["want", "planned"].includes(place.preference)).length],
              ["unvisited", "还没去", places.filter((place) => !place.visitedBy.includes("me")).length],
              ["visited", "去过", places.filter((place) => place.visitedBy.includes("me")).length]
            ].map(([value, label, count]) => (
              <button key={value} type="button" className={filter === value ? "active" : ""} onClick={() => setFilter(value as FilterMode)}>{label}<span>{count}</span></button>
            ))}
          </div>
          <MapSurface places={visiblePlaces} selectedId={selected?.id} onSelect={choosePlace} city={selected?.city ?? "我的旅行地图"} />
          <button className="mobile-list-toggle" type="button" onClick={() => setMobilePanel(true)}><List size={17} /> 主题与地点</button>
        </main>

        {selected && (
          <article className="selected-place-card">
            <button className="card-close" type="button" onClick={() => setSelected(undefined)} aria-label="关闭地点详情"><X size={17} /></button>
            <div className="place-card-visual"><MapPinArtwork place={selected} /></div>
            <div className="selected-place-content">
              <div className="selected-place-kicker">
                <span>{selected.category}</span>
                {selected.visitedBy.includes("me") && <small><Check size={13} /> 我去过</small>}
              </div>
              <h2>{selected.name}</h2>
              <span className="place-location">{selected.city} · {selected.district}</span>
              <p>{selected.note || "还没有备注，可以在地点详情中补充。"}</p>
              <div className="tag-row">{selected.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}</div>
              <button className="primary-button" type="button" onClick={() => navigate(`/places/${selected.id}`)}>查看地点详情 <ArrowRight size={16} /></button>
            </div>
          </article>
        )}
      </div>

      <div className="view-switch" aria-label="视图切换">
        <button type="button" className={!mobilePanel ? "active" : ""} onClick={() => setMobilePanel(false)}><MapIcon size={16} /> 地图</button>
        <button type="button" className={mobilePanel ? "active" : ""} onClick={() => setMobilePanel(true)}><List size={16} /> 清单</button>
      </div>
    </div>
  );
}

function MapPinArtwork({ place }: { place: Place }) {
  return <div className="place-artwork"><span>{place.category.slice(0, 1) || "旅"}</span><small>{place.city}</small></div>;
}
