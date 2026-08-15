import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Bike,
  Bus,
  Car,
  Clock3,
  ExternalLink,
  Footprints,
  GripVertical,
  MapPin,
  MoreHorizontal,
  Plus,
  Route as RouteIcon,
  Sparkles
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MapSurface } from "../components/MapSurface";
import { EmptyState, Toast } from "../components/Shared";
import { AMapRouteResult, placeToCoordinate, planAMapRoute } from "../map/amapRuntime";
import { mapProviderForCountry } from "../map/provider";
import { useTravel } from "../state/TravelContext";

const modes = [
  { value: "walking", label: "步行", icon: Footprints },
  { value: "transit", label: "公交", icon: Bus },
  { value: "driving", label: "驾车", icon: Car },
  { value: "bicycling", label: "骑行", icon: Bike }
];

type RouteMode = "walking" | "transit" | "driving" | "bicycling";

export function RoutePage() {
  const { routeId } = useParams();
  const { routes, mapById, placeById, reorderRouteStop } = useTravel();
  const navigate = useNavigate();
  const route = routes.find((item) => item.id === routeId);
  const [mode, setMode] = useState<RouteMode>(route?.mode ?? "walking");
  const [toast, setToast] = useState<string>();
  const [routeResult, setRouteResult] = useState<AMapRouteResult>();
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError] = useState<string>();
  const mapProvider = mapProviderForCountry();
  const map = route ? mapById(route.mapId) : undefined;
  const stops = useMemo(() => route ? route.stopIds.map((id) => placeById(id)).filter(Boolean) as NonNullable<ReturnType<typeof placeById>>[] : [], [placeById, route]);
  const stopSignature = stops.map((place) => place.id).join(",");

  useEffect(() => {
    if (!route || stops.length < 2) return;
    let active = true;
    setRouteLoading(true);
    setRouteError(undefined);
    planAMapRoute(stops.map(placeToCoordinate), mode, map?.city).then((result) => {
      if (active) setRouteResult(result);
    }).catch((error) => {
      if (active) {
        setRouteResult(undefined);
        setRouteError(error instanceof Error ? error.message : "路线规划失败");
      }
    }).finally(() => {
      if (active) setRouteLoading(false);
    });
    return () => { active = false; };
  }, [map?.city, mode, route, stopSignature]);

  if (!route) {
    return <div className="content-page"><EmptyState icon={<RouteIcon />} title="没有找到这条路线">路线可能还没有保存。</EmptyState></div>;
  }
  const externalMapUrl = mapProvider.externalRouteUrl(stops, mode);
  const distance = routeResult?.distanceMeters ? formatDistance(routeResult.distanceMeters) : route.distance;
  const duration = routeResult?.durationSeconds ? formatDuration(routeResult.durationSeconds) : route.duration;

  return (
    <div className="route-page">
      <header className="route-header">
        <button className="icon-button" type="button" onClick={() => navigate(`/maps/${route.mapId}`)} aria-label="返回主题地图"><ArrowLeft size={20} /></button>
        <div><span className="eyebrow">{map?.title ?? "主题地图"}</span><h1>{route.title}</h1><p>{route.note}</p></div>
        <button className="icon-button" type="button" aria-label="更多"><MoreHorizontal size={20} /></button>
      </header>

      <div className="route-layout">
        <aside className="route-planner">
          <div className="route-summary">
            <span><RouteIcon size={20} /></span>
            <div><strong>{distance}</strong><small>{duration}</small></div>
            <div><strong>{stops.length} 站</strong><small>{routeLoading ? "正在规划" : routeError ? "直线预览" : "高德路线"}</small></div>
          </div>
          <div className="mode-switch">
            {modes.map(({ value, label, icon: Icon }) => (
              <button key={value} type="button" className={mode === value ? "active" : ""} onClick={() => setMode(value as RouteMode)}>
                <Icon size={17} /> {label}
              </button>
            ))}
          </div>
          <div className="stop-list">
            {stops.map((place, index) => (
              <article key={place.id}>
                <GripVertical className="grip" size={18} />
                <span className="stop-number">{index + 1}</span>
                <button className="stop-content" type="button" onClick={() => navigate(`/places/${place.id}`)}>
                  <strong>{place.name}</strong><small>{place.district} · {place.category}</small>
                </button>
                <div className="stop-actions">
                  <button type="button" onClick={() => reorderRouteStop(route.id, index, -1)} disabled={index === 0} aria-label="上移"><ArrowUp size={15} /></button>
                  <button type="button" onClick={() => reorderRouteStop(route.id, index, 1)} disabled={index === stops.length - 1} aria-label="下移"><ArrowDown size={15} /></button>
                </div>
                {index < stops.length - 1 && <span className="stop-connector"><Clock3 size={13} /> 约 {18 + index * 5} 分钟</span>}
              </article>
            ))}
          </div>
          <button className="add-stop-button" type="button"><Plus size={17} /> 从地图中添加一站</button>
          <div className="route-actions">
            <button className="secondary-button" type="button" onClick={() => { setToast("已生成一个新的顺序草案，确认后才会保存"); window.setTimeout(() => setToast(undefined), 2200); }}><Sparkles size={16} /> 让助手优化顺序</button>
            {externalMapUrl ? <a className="primary-button" href={externalMapUrl} target="_blank" rel="noreferrer">{mapProvider.label}打开路线 <ExternalLink size={16} /></a> : <button className="primary-button" type="button" onClick={() => { setToast("外部地图跳转暂未配置"); window.setTimeout(() => setToast(undefined), 2200); }}>{mapProvider.label}打开路线 <ExternalLink size={16} /></button>}
          </div>
        </aside>
        <main className="route-map-area">
          <MapSurface places={stops} routePlaces={stops} routePath={routeResult?.path} city={map?.city ?? "路线"} />
          <div className={`route-map-note${routeError ? " error" : ""}`}><MapPin size={16} /><span>{routeLoading ? "正在向高德请求路线…" : routeError ? `${routeError}，当前显示站点连线。` : `已按${modes.find((item) => item.value === mode)?.label}计算真实路线。`}</span></div>
        </main>
      </div>
      {toast && <Toast>{toast}</Toast>}
    </div>
  );
}

function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} 公里` : `${Math.round(meters)} 米`;
}

function formatDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分` : `${minutes} 分钟`;
}
