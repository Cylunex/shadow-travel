import { MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { AMapSurface } from "../map/AMapSurface";
import {
  MapCoordinate,
  isAMapConfigured,
  coordinateForAMap,
} from "../map/amapRuntime";
import { ClientMapProvider, mapProviderForCountry } from "../map/provider";
import { Place } from "../types";
import { isLocalReadMode } from "../offline";

export function MapSurface({
  places,
  selectedId,
  onSelect,
  routePlaces = [],
  city,
  compact = false,
  provider = mapProviderForCountry(),
  routePath,
  onMapClick,
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
}) {
  const signature = [...places, ...routePlaces]
    .filter((p) => p.coordinate.reference === "WGS84")
    .map((p) => `${p.id}:${p.coordinate.longitude}:${p.coordinate.latitude}`)
    .join("|");
  const [converted, setConverted] = useState<{
    signature: string;
    coordinates: Record<string, Place["coordinate"]>;
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
    if (!signature || !isAMapConfigured() || !online) return;
    let active = true;
    setConversionError("");
    Promise.all(
      [
        ...new Map(
          [...places, ...routePlaces]
            .filter((p) => p.coordinate.reference === "WGS84")
            .map((p) => [p.id, p]),
        ).values(),
      ].map(
        async (p) => [p.id, await coordinateForAMap(p.coordinate)] as const,
      ),
    )
      .then((values) => {
        if (active)
          setConverted({ signature, coordinates: Object.fromEntries(values) });
      })
      .catch((e) => {
        if (active) setConversionError(e.message);
      });
    return () => {
      active = false;
    };
  }, [signature, online]);
  if (
    signature &&
    online &&
    isAMapConfigured() &&
    converted?.signature !== signature
  )
    return (
      <section className="map-surface map-unavailable" role="status">
        {conversionError || "正在转换 WGS-84 坐标，完成后显示真实地图…"}
      </section>
    );
  const mapped = (items: Place[]) =>
    items.map((p) =>
      p.coordinate.reference === "WGS84" && converted?.coordinates[p.id]
        ? { ...p, coordinate: converted.coordinates[p.id] }
        : p,
    );
  if (provider.id === "amap" && isAMapConfigured() && online) {
    return (
      <AMapSurface
        places={mapped(places)}
        selectedId={selectedId}
        onSelect={onSelect}
        routePlaces={mapped(routePlaces)}
        routePath={routePath}
        city={city}
        compact={compact}
        provider={provider}
        onMapClick={onMapClick}
      />
    );
  }
  return (
    <section
      className={`map-surface map-unavailable${compact ? " compact" : ""}`}
      role="status"
    >
      <MapPin size={30} />
      <strong>
        {navigator.onLine ? "地图服务尚未就绪" : "离线模式 · 底图未下载"}
      </strong>
      <p>
        {navigator.onLine
          ? "需要配置对应地图服务；这里不会展示模拟底图。地点清单仍可使用。"
          : "已下载的地点与地址仍可阅读。恢复网络后可打开高德导航。"}
      </p>
    </section>
  );
}
