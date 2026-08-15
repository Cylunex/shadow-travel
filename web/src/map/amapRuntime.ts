import { load } from "@amap/amap-jsapi-loader";

import { Place } from "../types";

const plugins = [
  "AMap.ToolBar",
  "AMap.Scale",
  "AMap.PlaceSearch",
  "AMap.AutoComplete",
  "AMap.Geocoder",
  "AMap.Driving",
  "AMap.Walking",
  "AMap.Riding",
  "AMap.Transfer"
];

let loaderPromise: Promise<typeof AMap> | undefined;

export type MapCoordinate = { longitude: number; latitude: number };

export type AMapSearchResult = {
  providerPlaceId?: string;
  name: string;
  address: string;
  province?: string;
  city?: string;
  district?: string;
  category?: string;
  coordinate: MapCoordinate;
};

export type AMapRouteMode = "walking" | "transit" | "driving" | "bicycling";

export type AMapRouteResult = {
  path: MapCoordinate[];
  distanceMeters: number;
  durationSeconds: number;
};

export function isAMapConfigured(): boolean {
  return Boolean(__SHADOW_AMAP_CONFIG__?.key && __SHADOW_AMAP_CONFIG__?.securityJsCode);
}

export function loadAMap(): Promise<typeof AMap> {
  if (!__SHADOW_AMAP_CONFIG__) {
    return Promise.reject(new Error("AMap JS API is not configured"));
  }
  if (!loaderPromise) {
    window._AMapSecurityConfig = {
      securityJsCode: __SHADOW_AMAP_CONFIG__.securityJsCode
    };
    loaderPromise = load({
      key: __SHADOW_AMAP_CONFIG__.key,
      version: "2.0",
      plugins
    }) as Promise<typeof AMap>;
  }
  return loaderPromise;
}

export async function searchAMapPlaces(
  query: string,
  city?: string,
  limit = 12
): Promise<AMapSearchResult[]> {
  const AMapApi = await loadAMap();
  const PlaceSearch = pluginConstructor<AMapPlaceSearch>(AMapApi, "PlaceSearch");
  const service = new PlaceSearch({
    city: city || "全国",
    citylimit: Boolean(city),
    pageSize: Math.max(1, Math.min(limit, 25)),
    pageIndex: 1,
    extensions: "base"
  });
  const result = await callbackRequest<Record<string, unknown>>((done) =>
    service.search(query.trim(), done)
  );
  const poiList = record(result.poiList);
  const pois = Array.isArray(poiList?.pois) ? poiList.pois : [];
  return pois.flatMap((value) => {
    const poi = record(value);
    const location = coordinateFrom(poi?.location);
    if (!poi || !location) return [];
    return [{
      providerPlaceId: text(poi.id),
      name: text(poi.name) || "未命名地点",
      address: text(poi.address) || "",
      province: text(poi.pname),
      city: text(poi.cityname),
      district: text(poi.adname),
      category: text(poi.type),
      coordinate: location
    }];
  });
}

export async function reverseGeocodeAMap(point: MapCoordinate): Promise<AMapSearchResult> {
  const AMapApi = await loadAMap();
  const Geocoder = pluginConstructor<AMapGeocoder>(AMapApi, "Geocoder");
  const service = new Geocoder({ extensions: "base" });
  const result = await callbackRequest<Record<string, unknown>>((done) =>
    service.getAddress([point.longitude, point.latitude], done)
  );
  const regeocode = record(result.regeocode);
  const component = record(regeocode?.addressComponent);
  return {
    name: text(regeocode?.formattedAddress) || "地图选点",
    address: text(regeocode?.formattedAddress) || "",
    province: text(component?.province),
    city: text(component?.city),
    district: text(component?.district),
    coordinate: point
  };
}

export async function planAMapRoute(
  stops: MapCoordinate[],
  mode: AMapRouteMode,
  city?: string
): Promise<AMapRouteResult> {
  if (stops.length < 2) throw new Error("路线至少需要两个地点");
  const AMapApi = await loadAMap();
  const combined: AMapRouteResult = { path: [], distanceMeters: 0, durationSeconds: 0 };
  for (let index = 0; index < stops.length - 1; index += 1) {
    const leg = await planLeg(AMapApi, stops[index], stops[index + 1], mode, city);
    combined.path.push(...(index === 0 ? leg.path : leg.path.slice(1)));
    combined.distanceMeters += leg.distanceMeters;
    combined.durationSeconds += leg.durationSeconds;
  }
  return combined;
}

async function planLeg(
  AMapApi: typeof AMap,
  origin: MapCoordinate,
  destination: MapCoordinate,
  mode: AMapRouteMode,
  city?: string
): Promise<AMapRouteResult> {
  const constructorName = mode === "bicycling" ? "Riding" : mode === "transit" ? "Transfer" : title(mode);
  const Service = pluginConstructor<AMapRouteService>(AMapApi, constructorName);
  const service = new Service(mode === "transit" ? { city: city || "全国", cityd: city || "全国" } : {});
  const result = await callbackRequest<Record<string, unknown>>((done) =>
    service.search(
      [origin.longitude, origin.latitude],
      [destination.longitude, destination.latitude],
      done
    )
  );
  const primary = firstRouteRecord(result);
  const path = collectCoordinates(primary ?? result);
  return {
    path: path.length ? path : [origin, destination],
    distanceMeters: numeric(primary?.distance) ?? numeric(result.distance) ?? 0,
    durationSeconds: numeric(primary?.time) ?? numeric(primary?.duration) ?? numeric(result.time) ?? 0
  };
}

function callbackRequest<T>(start: (done: (status: string, result: T) => void) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    start((status, result) => {
      if (status === "complete") resolve(result);
      else if (status === "no_data") reject(new Error("没有找到匹配结果"));
      else reject(new Error("高德地图服务暂时不可用"));
    });
  });
}

type Constructor<T> = new (options?: Record<string, unknown>) => T;
type AMapPlaceSearch = { search: (query: string, callback: (status: string, result: Record<string, unknown>) => void) => void };
type AMapGeocoder = { getAddress: (point: [number, number], callback: (status: string, result: Record<string, unknown>) => void) => void };
type AMapRouteService = { search: (origin: [number, number], destination: [number, number], callback: (status: string, result: Record<string, unknown>) => void) => void };

function pluginConstructor<T>(AMapApi: typeof AMap, name: string): Constructor<T> {
  const value = (AMapApi as unknown as Record<string, unknown>)[name];
  if (typeof value !== "function") throw new Error(`AMap.${name} plugin is unavailable`);
  return value as Constructor<T>;
}

function firstRouteRecord(result: Record<string, unknown>): Record<string, unknown> | undefined {
  for (const key of ["routes", "plans"]) {
    const values = result[key];
    if (Array.isArray(values) && values.length) return record(values[0]);
  }
  return undefined;
}

function collectCoordinates(value: unknown): MapCoordinate[] {
  const result: MapCoordinate[] = [];
  const visited = new Set<unknown>();
  function visit(current: unknown, key = "") {
    if (!current || visited.has(current)) return;
    if (typeof current === "object") visited.add(current);
    if (key === "path" && Array.isArray(current)) {
      for (const point of current) {
        const coordinate = coordinateFrom(point);
        if (coordinate) result.push(coordinate);
      }
      if (result.length) return;
    }
    if (Array.isArray(current)) current.forEach((item) => visit(item, key));
    else if (typeof current === "object") Object.entries(current as Record<string, unknown>).forEach(([childKey, child]) => visit(child, childKey));
  }
  visit(value);
  return result.filter((point, index, values) => index === 0 || point.longitude !== values[index - 1].longitude || point.latitude !== values[index - 1].latitude);
}

function coordinateFrom(value: unknown): MapCoordinate | undefined {
  if (Array.isArray(value) && value.length >= 2) {
    const longitude = Number(value[0]);
    const latitude = Number(value[1]);
    if (Number.isFinite(longitude) && Number.isFinite(latitude)) return { longitude, latitude };
  }
  if (!value || typeof value !== "object") return undefined;
  const source = value as {
    getLng?: () => number;
    getLat?: () => number;
    lng?: number;
    lat?: number;
  };
  const longitude = typeof source.getLng === "function" ? Number(source.getLng()) : Number(source.lng);
  const latitude = typeof source.getLat === "function" ? Number(source.getLat()) : Number(source.lat);
  return Number.isFinite(longitude) && Number.isFinite(latitude) ? { longitude, latitude } : undefined;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" ? value as Record<string, unknown> : undefined;
}

function text(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(String).join("");
  return undefined;
}

function numeric(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function title(value: string): string {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}

export function placeToCoordinate(place: Place): MapCoordinate {
  return { longitude: place.coordinate.longitude, latitude: place.coordinate.latitude };
}
