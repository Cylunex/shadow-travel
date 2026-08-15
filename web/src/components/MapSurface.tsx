import { LocateFixed, Minus, Navigation, Plus } from "lucide-react";
import { CSSProperties, useMemo, useState } from "react";

import { AMapSurface } from "../map/AMapSurface";
import { MapCoordinate, isAMapConfigured } from "../map/amapRuntime";
import { ClientMapProvider, mapProviderForCountry } from "../map/provider";
import { Place } from "../types";

type Segment = { left: number; top: number; width: number; angle: number };

export function MapSurface({
  places,
  selectedId,
  onSelect,
  routePlaces = [],
  city,
  compact = false,
  provider = mapProviderForCountry(),
  routePath,
  onMapClick
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
  const [zoom, setZoom] = useState(1);
  const selectedPlace = places.find((place) => place.id === selectedId);
  const segments = useMemo(
    () =>
      routePlaces.slice(0, -1).map((place, index): Segment => {
        const next = routePlaces[index + 1];
        const dx = next.coordinate.x - place.coordinate.x;
        const dy = next.coordinate.y - place.coordinate.y;
        return {
          left: place.coordinate.x,
          top: place.coordinate.y,
          width: Math.sqrt(dx * dx + dy * dy),
          angle: (Math.atan2(dy, dx) * 180) / Math.PI
        };
      }),
    [routePlaces]
  );

  if (provider.id === "amap" && isAMapConfigured()) {
    return <AMapSurface places={places} selectedId={selectedId} onSelect={onSelect} routePlaces={routePlaces} routePath={routePath} city={city} compact={compact} provider={provider} onMapClick={onMapClick} />;
  }

  return (
    <section className={`map-surface${compact ? " compact" : ""}`} aria-label={`${city}地图`}>
      <div className="map-visual" style={{ "--map-zoom": zoom } as CSSProperties}>
        <div className="map-land land-one" />
        <div className="map-land land-two" />
        <div className="map-water water-one" />
        <div className="map-road road-a" />
        <div className="map-road road-b" />
        <div className="map-road road-c" />
        <div className="map-road road-d" />
        <span className="map-label label-city">{city}</span>
        <span className="map-label label-one">老城区</span>
        <span className="map-label label-two">城市公园</span>
        {segments.map((segment, index) => (
          <span
            key={`${segment.left}-${segment.top}-${index}`}
            className="route-segment"
            style={
              {
                left: `${segment.left}%`,
                top: `${segment.top}%`,
                width: `${segment.width}%`,
                transform: `rotate(${segment.angle}deg)`
              } as CSSProperties
            }
          />
        ))}
        {places.map((place, index) => {
          const routeIndex = routePlaces.findIndex((item) => item.id === place.id);
          const visited = place.visitedBy.includes("me");
          return (
            <button
              key={place.id}
              type="button"
              className={`map-marker${selectedId === place.id ? " selected" : ""}${
                visited ? " visited" : ""
              }${routeIndex >= 0 ? " route-stop" : ""}`}
              style={
                {
                  left: `${place.coordinate.x}%`,
                  top: `${place.coordinate.y}%`,
                  "--marker-delay": `${index * 25}ms`
                } as CSSProperties
              }
              onClick={() => onSelect?.(place)}
              aria-label={`${place.name}${visited ? "，已去过" : "，还没去"}`}
            >
              {routeIndex >= 0 ? routeIndex + 1 : visited ? "✓" : ""}
              <span>{place.shortName}</span>
            </button>
          );
        })}
      </div>

      <div className="map-provider-badge">
        <span>{provider.id.toUpperCase()}</span>
        <small>{provider.label}接入位</small>
      </div>

      <div className="map-sdk-state unconfigured">地图 Key 未配置，当前显示轻量预览</div>

      {!compact && (
        <div className="map-controls" aria-label="地图控制">
          <button type="button" onClick={() => setZoom((value) => Math.min(1.16, value + 0.04))}>
            <Plus size={18} />
          </button>
          <button type="button" onClick={() => setZoom((value) => Math.max(0.92, value - 0.04))}>
            <Minus size={18} />
          </button>
          <button type="button" onClick={() => setZoom(1)}>
            <LocateFixed size={18} />
          </button>
        </div>
      )}

      {selectedPlace && provider.externalPlaceUrl(selectedPlace) && !compact && (
        <a
          className="map-navigate"
          href={provider.externalPlaceUrl(selectedPlace)}
          target="_blank"
          rel="noreferrer"
          aria-label={`在${provider.label}打开${selectedPlace.name}`}
        >
          <Navigation size={16} />
          {provider.label}打开
        </a>
      )}
    </section>
  );
}
