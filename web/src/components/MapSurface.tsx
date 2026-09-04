import { MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { AMapSurface } from "../map/AMapSurface";
import { GoogleSurface } from "../map/GoogleSurface";
import {
  type MapCoordinate,
  isAMapConfigured,
  coordinateForAMap,
} from "../map/amapRuntime";
import { type ClientMapProvider, mapProviderForCountry } from "../map/provider";
import { isLocated, type Place, type LocatedPlace } from "../types";
import { isLocalReadMode } from "../offline";

export function MapSurface({
  places,
  selectedId,
  onSelect,
  routePlaces = [],
  city,
  compact = false,
  provider,
  routePath,
  onMapClick,
  onGoogleMapClick,
}: {
  places: Place[];
  selectedId?: string;
  onSelect?: (place: Place) => void;
  routePlaces?: Place[];
  city: string;
  compact?: boolean;
  provider?: ClientMapProvider;
  routePath?: MapCoordinate[];
  onMapClick?: (coordinate: MapCoordinate) => void;
  onGoogleMapClick?: (coordinate: MapCoordinate) => void;
}) {
  const [region, setRegion] = useState<"amap" | "google">();
  const selected = places.find((p) => p.id === selectedId) || places[0];
  const auto =
    selected?.provider === "google" ||
    (selected?.countryCode && selected.countryCode !== "CN")
      ? "google"
      : "amap";
  const actual =
    provider ||
    mapProviderForCountry((region || auto) === "google" ? "ZZ" : "CN");
  const filtered = places.filter((p) =>
    actual.id === "google"
      ? p.provider === "google" || (p.countryCode && p.countryCode !== "CN")
      : p.provider !== "google" && (!p.countryCode || p.countryCode === "CN"),
  );
  const located = filtered.filter(isLocated);
  const signature = located
    .filter((p) => p.coordinate.reference === "WGS84")
    .map((p) => `${p.id}:${p.coordinate.longitude}:${p.coordinate.latitude}`)
    .join("|");
  const [converted, setConverted] = useState<{
    signature: string;
    coordinates: Record<string, LocatedPlace["coordinate"]>;
  }>();
  const [conversionError, setConversionError] = useState("");
  const [online, setOnline] = useState(navigator.onLine && !isLocalReadMode());
  useEffect(() => {
    const update = () => setOnline(navigator.onLine && !isLocalReadMode());
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    if (actual.id !== "amap" || !signature || !isAMapConfigured() || !online)
      return;
    let active = true;
    setConversionError("");
    Promise.all(
      located
        .filter((p) => p.coordinate.reference === "WGS84")
        .map(
          async (p) => [p.id, await coordinateForAMap(p.coordinate)] as const,
        ),
    )
      .then(
        (values) =>
          active &&
          setConverted({ signature, coordinates: Object.fromEntries(values) }),
      )
      .catch((e) => active && setConversionError(e.message));
    return () => {
      active = false;
    };
  }, [signature, online, actual.id]);
  const mapped = (items: LocatedPlace[]) =>
    items.map((p) =>
      converted?.signature === signature && converted.coordinates[p.id]
        ? { ...p, coordinate: converted.coordinates[p.id] }
        : p,
    );
  let surface;
  if (actual.id === "google" && online)
    surface = (
      <GoogleSurface
        places={filtered}
        selectedId={selectedId}
        onSelect={onSelect}
        routePath={routePath}
        compact={compact}
        onMapClick={onGoogleMapClick}
      />
    );
  else if (actual.id === "amap" && isAMapConfigured() && online)
    surface =
      signature && converted?.signature !== signature ? (
        <section className="map-surface map-unavailable" role="status">
          {conversionError || "正在转换 WGS-84 坐标…"}
        </section>
      ) : (
        <AMapSurface
          places={mapped(located)}
          selectedId={selectedId}
          onSelect={onSelect}
          routePlaces={mapped(
            routePlaces
              .filter(isLocated)
              .filter((p) => located.some((l) => l.id === p.id)),
          )}
          routePath={routePath}
          city={city}
          compact={compact}
          provider={actual}
          onMapClick={onMapClick}
        />
      );
  else
    surface = (
      <section
        className={`map-surface map-unavailable${compact ? " compact" : ""}`}
        role="status"
      >
        <MapPin size={30} />
        <strong>{online ? "地图服务尚未就绪" : "离线模式 · 底图未下载"}</strong>
        <p>
          {online
            ? "请配置地图服务；地点清单仍可使用，不显示模拟底图。"
            : "仅下载自己的计划与地点引用，底图和实时详情需联网。"}
        </p>
      </section>
    );
  return (
    <div className="provider-surface">
      {surface}
      {!provider && !compact && (
        <label className="provider-switch">
          底图
          <select
            aria-label="地图区域"
            value={actual.id}
            onChange={(e) => setRegion(e.target.value as "amap" | "google")}
          >
            <option value="amap">中国大陆 · 高德</option>
            <option value="google">海外 · Google</option>
          </select>
          {filtered.length < places.length && (
            <small>
              当前区域 {filtered.length}/{places.length}
            </small>
          )}
        </label>
      )}
    </div>
  );
}
