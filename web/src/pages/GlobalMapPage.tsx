import {
  Check,
  Filter,
  List,
  Map as MapIcon,
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

export function GlobalMapPage() {
  const { maps, places, members } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [selected, setSelected] = useState<Place | undefined>(places[0]);
  const [mobileList, setMobileList] = useState(false);

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
    setMobileList(false);
  }

  return (
    <div className="global-map-page">
      <header className="map-page-header">
        <div>
          <span className="eyebrow">MY TRAVEL ATLAS</span>
          <h1>今天想去哪里？</h1>
          <p>把三张主题地图放在一起看，也保留每一次真正到达。</p>
        </div>
        <div className="header-actions">
          <AvatarStack members={members} label="3 位同行人" />
          <button className="secondary-button" type="button" onClick={() => navigate("/maps") }>
            <Plus size={18} />
            新建地图
          </button>
        </div>
      </header>

      <div className="map-workspace">
        <section className={`map-list-panel${mobileList ? " mobile-open" : ""}`}>
          <div className="panel-handle" />
          <div className="search-field">
            <Search size={18} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索地点、标签或城市"
              aria-label="搜索地点、标签或城市"
            />
            {query && (
              <button type="button" onClick={() => setQuery("")} aria-label="清空搜索">
                <X size={16} />
              </button>
            )}
          </div>

          <div className="filter-scroll" aria-label="地图筛选">
            {[
              ["all", "全部", places.length],
              ["want", "想去", places.filter((place) => place.preference !== "none").length],
              ["unvisited", "还没去", places.filter((place) => !place.visitedBy.includes("me")).length],
              ["visited", "去过", places.filter((place) => place.visitedBy.includes("me")).length]
            ].map(([value, label, count]) => (
              <button
                key={value}
                type="button"
                className={filter === value ? "active" : ""}
                onClick={() => setFilter(value as FilterMode)}
              >
                {label} <span>{count}</span>
              </button>
            ))}
            <button type="button">
              <Filter size={15} /> 更多
            </button>
          </div>

          <div className="panel-summary">
            <div>
              <strong>{visiblePlaces.length} 个地点</strong>
              <span>来自 {maps.length} 张地图</span>
            </div>
            <span>按添加顺序</span>
          </div>

          <div className="place-list">
            {visiblePlaces.map((place) => (
              <PlaceListItem
                key={place.id}
                place={place}
                active={selected?.id === place.id}
                onClick={() => choosePlace(place)}
              />
            ))}
            {visiblePlaces.length === 0 && (
              <div className="inline-empty">
                <Search size={22} />
                <strong>没有匹配的地点</strong>
                <span>试试清空关键词或换一个筛选条件。</span>
              </div>
            )}
          </div>
        </section>

        <div className="map-stage">
          <MapSurface
            places={visiblePlaces}
            selectedId={selected?.id}
            onSelect={choosePlace}
            city={filter === "all" ? "北京 · 贵阳" : selected?.city ?? "旅行地图"}
          />

          <button className="mobile-list-toggle" type="button" onClick={() => setMobileList(true)}>
            <List size={18} /> {visiblePlaces.length} 个地点
          </button>

          {selected && (
            <article className="selected-place-card">
              <button
                className="card-close"
                type="button"
                onClick={() => setSelected(undefined)}
                aria-label="关闭地点卡片"
              >
                <X size={17} />
              </button>
              <div className="selected-place-kicker">
                <span>{selected.category}</span>
                {selected.visitedBy.includes("me") && (
                  <small><Check size={13} /> 我去过</small>
                )}
              </div>
              <h2>{selected.name}</h2>
              <p>{selected.note}</p>
              <div className="tag-row">
                {selected.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}
              </div>
              <button className="text-button" type="button" onClick={() => navigate(`/places/${selected.id}`)}>
                查看地点详情 <span>→</span>
              </button>
            </article>
          )}
        </div>
      </div>

      <div className="view-switch" aria-label="视图切换">
        <button type="button" className={!mobileList ? "active" : ""} onClick={() => setMobileList(false)}>
          <MapIcon size={16} /> 地图
        </button>
        <button type="button" className={mobileList ? "active" : ""} onClick={() => setMobileList(true)}>
          <List size={16} /> 列表
        </button>
      </div>
    </div>
  );
}
