import { LocateFixed, Minus, Navigation, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Place } from "../types";
import { ClientMapProvider } from "./provider";
import { MapCoordinate, loadAMap } from "./amapRuntime";

export function AMapSurface({
  places,
  selectedId,
  onSelect,
  routePlaces,
  routePath,
  city,
  compact,
  provider,
  onMapClick
}: {
  places: Place[];
  selectedId?: string;
  onSelect?: (place: Place) => void;
  routePlaces: Place[];
  routePath?: MapCoordinate[];
  city: string;
  compact: boolean;
  provider: ClientMapProvider;
  onMapClick?: (coordinate: MapCoordinate) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<AMap.Map | null>(null);
  const overlaysRef = useRef<Array<AMap.Marker | AMap.Polyline>>([]);
  const onMapClickRef = useRef(onMapClick);
  const [AMapApi, setAMapApi] = useState<typeof AMap>();
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const selectedPlace = places.find((place) => place.id === selectedId);
  onMapClickRef.current = onMapClick;

  useEffect(() => {
    let disposed = false;
    let map: AMap.Map | undefined;
    loadAMap().then((api) => {
      if (disposed || !containerRef.current) return;
      map = new api.Map(containerRef.current, {
        viewMode: "2D",
        zoom: compact ? 13 : 11,
        center: initialCenter(places),
        mapStyle: "amap://styles/normal",
        showLabel: true
      });
      mapRef.current = map;
      setAMapApi(api);
      setStatus("ready");
      map.on("click", (event: unknown) => {
        const lnglat = (event as { lnglat?: AMap.LngLat }).lnglat;
        if (lnglat && onMapClickRef.current) {
          onMapClickRef.current({ longitude: lnglat.getLng(), latitude: lnglat.getLat() });
        }
      });
    }).catch(() => {
      if (!disposed) setStatus("error");
    });
    return () => {
      disposed = true;
      map?.destroy();
      mapRef.current = null;
    };
  }, [compact]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !AMapApi) return;
    if (overlaysRef.current.length) map.remove(overlaysRef.current);

    const routeIds = new Map(routePlaces.map((place, index) => [place.id, index + 1]));
    const markers = places.map((place) => {
      const content = document.createElement("button");
      content.type = "button";
      content.className = `amap-place-marker${place.visitedBy.includes("me") ? " visited" : ""}${selectedId === place.id ? " selected" : ""}${routeIds.has(place.id) ? " route-stop" : ""}`;
      content.setAttribute("aria-label", `${place.name}${place.visitedBy.includes("me") ? "，已去过" : "，还没去"}`);
      const dot = document.createElement("span");
      dot.textContent = String(routeIds.get(place.id) ?? (place.visitedBy.includes("me") ? "✓" : ""));
      const label = document.createElement("em");
      label.textContent = place.shortName;
      content.append(dot, label);
      const marker = new AMapApi.Marker({
        position: [place.coordinate.longitude, place.coordinate.latitude],
        anchor: "bottom-center",
        content,
        title: place.name,
        zIndex: selectedId === place.id ? 120 : 100
      });
      marker.on("click", () => onSelect?.(place));
      return marker;
    });

    const path = routePath?.length ? routePath : routePlaces.map((place) => place.coordinate);
    const line = path.length > 1 ? new AMapApi.Polyline({
      path: path.map((point) => new AMapApi.LngLat(point.longitude, point.latitude)),
      strokeColor: "#285c4b",
      strokeWeight: 6,
      strokeOpacity: .82,
      borderWeight: 2,
      outlineColor: "#ffffff",
      lineJoin: "round",
      lineCap: "round",
      showDir: true,
      zIndex: 80
    }) : undefined;
    const overlays: Array<AMap.Marker | AMap.Polyline> = line ? [...markers, line] : markers;
    overlaysRef.current = overlays;
    map.add(overlays);
    if (overlays.length) map.setFitView(overlays, false, compact ? [28, 28, 28, 28] : [80, 80, 80, 80], compact ? 15 : 14);
  }, [AMapApi, compact, onSelect, places, routePath, routePlaces, selectedId]);

  useEffect(() => {
    if (selectedPlace && mapRef.current) {
      mapRef.current.setZoomAndCenter(Math.max(mapRef.current.getZoom(), 14), [selectedPlace.coordinate.longitude, selectedPlace.coordinate.latitude]);
    }
  }, [selectedPlace]);

  const externalUrl = selectedPlace ? provider.externalPlaceUrl(selectedPlace) : undefined;

  return (
    <section className={`map-surface real-map${compact ? " compact" : ""}`} aria-label={`${city}${provider.label}`}>
      <div ref={containerRef} className="amap-container" />
      {status !== "ready" && <div className={`map-sdk-state ${status}`}><span />{status === "loading" ? "正在加载高德地图…" : "地图加载失败，请检查 Key 白名单或网络"}</div>}
      <div className="map-provider-badge"><span>{provider.id.toUpperCase()}</span><small>{provider.label} · {provider.coordinateSystem}</small></div>
      {!compact && <div className="map-controls" aria-label="地图控制">
        <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label="放大地图"><Plus size={18} /></button>
        <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label="缩小地图"><Minus size={18} /></button>
        <button type="button" onClick={() => mapRef.current?.setFitView()} aria-label="显示全部点位"><LocateFixed size={18} /></button>
      </div>}
      {externalUrl && !compact && <a className="map-navigate" href={externalUrl} target="_blank" rel="noreferrer" aria-label={`在${provider.label}打开${selectedPlace?.name}`}><Navigation size={16} />{provider.label}打开</a>}
      {onMapClick && status === "ready" && !compact && <span className="map-click-hint">点击地图空白处添加地点</span>}
    </section>
  );
}

function initialCenter(places: Place[]): [number, number] {
  if (!places.length) return [116.397428, 39.90923];
  const total = places.reduce((value, place) => ({ longitude: value.longitude + place.coordinate.longitude, latitude: value.latitude + place.coordinate.latitude }), { longitude: 0, latitude: 0 });
  return [total.longitude / places.length, total.latitude / places.length];
}
