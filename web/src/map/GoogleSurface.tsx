import { useEffect, useRef, useState } from "react";
import { LocateFixed } from "lucide-react";
import type { Place } from "../types";
import type { MapCoordinate } from "./amapRuntime";
import {
  loadGoogle,
  resolveGooglePlaces,
  type LiveGooglePlace,
} from "./googleRuntime";

export function GoogleSurface({
  places,
  selectedId,
  onSelect,
  routePath,
  compact,
  onMapClick,
}: {
  places: Place[];
  selectedId?: string;
  onSelect?: (p: Place) => void;
  routePath?: MapCoordinate[];
  compact?: boolean;
  onMapClick?: (p: MapCoordinate) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | undefined>(undefined);
  const callbacks = useRef({ onSelect, onMapClick });
  callbacks.current = { onSelect, onMapClick };
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [resolved, setResolved] = useState<{
    signature: string;
    places: LiveGooglePlace[];
  }>();
  const selectedIndex = places.findIndex((p) => p.id === selectedId);
  const visible =
    selectedIndex >= 20
      ? [
          places[selectedIndex],
          ...places.filter((p) => p.id !== selectedId),
        ].slice(0, 20)
      : places.slice(0, 20);
  const signature = visible.map((p) => p.id).join("|");
  useEffect(() => {
    let active = true;
    setError("");
    const authFailure = () =>
      setError("Google 地图授权失败，请检查域名限制与计费配置");
    window.addEventListener("google-map-auth-failure", authFailure);
    loadGoogle()
      .then((api) => {
        if (!active || !container.current) return;
        map.current = new api.maps.Map(container.current, {
          center: { lat: 20, lng: 0 },
          zoom: 2,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          mapId: import.meta.env.VITE_GOOGLE_MAP_ID,
          colorScheme: api.maps.ColorScheme.LIGHT,
        });
        map.current.addListener("click", (e: google.maps.MapMouseEvent) => {
          if (e.latLng)
            callbacks.current.onMapClick?.({
              longitude: e.latLng.lng(),
              latitude: e.latLng.lat(),
            });
        });
        setReady(true);
      })
      .catch((e) => active && setError(e.message));
    const resize = new ResizeObserver(() => {
      if (map.current) google.maps.event.trigger(map.current, "resize");
    });
    if (container.current) resize.observe(container.current);
    return () => {
      active = false;
      resize.disconnect();
      window.removeEventListener("google-map-auth-failure", authFailure);
      if (map.current) google.maps.event.clearInstanceListeners(map.current);
      map.current = undefined;
      setReady(false);
    };
  }, [retry]);
  useEffect(() => {
    if (!ready || !map.current) return;
    let active = true;
    setError("");
    resolveGooglePlaces(visible)
      .then((live) => {
        if (active) setResolved({ signature, places: live });
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [ready, signature]);
  useEffect(() => {
    if (!ready || !map.current || resolved?.signature !== signature) return;
    const live = resolved.places;
    const markers: google.maps.marker.AdvancedMarkerElement[] = [];
    const bounds = new google.maps.LatLngBounds();
    live.forEach((p) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `amap-place-marker preference-${p.preference}${p.visitedBy.includes("me") ? " visited" : ""}${p.id === selectedId ? " selected" : ""}`;
      button.setAttribute("aria-label", p.name);
      const dot = document.createElement("span");
      dot.textContent = p.visitedBy.includes("me") ? "✓" : "";
      const text = document.createElement("em");
      text.textContent = p.shortName;
      button.append(dot, text);
      const position = {
        lat: p.coordinate.latitude,
        lng: p.coordinate.longitude,
      };
      const marker = new google.maps.marker.AdvancedMarkerElement({
        map: map.current,
        position,
        title: p.name,
        content: button,
      });
      button.onclick = () =>
        callbacks.current.onSelect?.(places.find((row) => row.id === p.id)!);
      markers.push(marker);
      bounds.extend(position);
    });
    if (live.length) map.current.fitBounds(bounds, 80);
    if (live.length === 1) map.current.setZoom(14);
    return () => {
      markers.forEach((m) => {
        m.map = null;
      });
    };
  }, [ready, signature, selectedId, resolved]);
  useEffect(() => {
    if (!ready || !map.current || !routePath?.length) return;
    const line = new google.maps.Polyline({
      map: map.current,
      path: routePath.map((p) => ({ lat: p.latitude, lng: p.longitude })),
      strokeColor: "#159DE5",
      strokeWeight: 5,
    });
    return () => line.setMap(null);
  }, [ready, routePath]);
  return (
    <section
      className={`map-surface real-map${compact ? " compact" : ""}`}
      aria-label="Google Maps · WGS-84"
    >
      <div ref={container} className="amap-container" />
      {(!ready || error) && (
        <div className="map-sdk-state" role="status">
          {error || "正在加载 Google 地图…"}
          {error && (
            <button
              className="secondary-button"
              onClick={() => setRetry((n) => n + 1)}
            >
              重试
            </button>
          )}
        </div>
      )}
      {places.length > 20 && (
        <span className="map-click-hint">
          当前显示前 20 个地点，请筛选后查看更多
        </span>
      )}
      {!!resolved?.places.some((p) => p.attributions?.length) && (
        <small className="google-attributions">
          {[
            ...new Set(
              resolved.places.flatMap((p) =>
                (p.attributions || []).map((a) => a.provider),
              ),
            ),
          ].join(" · ")}
        </small>
      )}
      <button
        className="map-navigate"
        disabled={!ready}
        onClick={() => {
          if (!navigator.geolocation) return setError("浏览器不支持定位");
          navigator.geolocation.getCurrentPosition(
            (p) => {
              map.current?.setCenter({
                lat: p.coords.latitude,
                lng: p.coords.longitude,
              });
              map.current?.setZoom(15);
            },
            () => setError("未能获取位置，请检查定位权限"),
            { timeout: 8000 },
          );
        }}
      >
        <LocateFixed size={16} />
        当前位置
      </button>
    </section>
  );
}
