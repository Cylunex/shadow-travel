import { Place } from "../types";

export interface ClientMapProvider {
  readonly id: "amap" | "google";
  readonly label: string;
  readonly coordinateSystem: "GCJ-02" | "WGS-84";
  externalPlaceUrl(place: Place): string | undefined;
  externalRouteUrl(stops: Place[], mode: "walking" | "transit" | "driving" | "bicycling"): string | undefined;
}

function amapExternalUrl(place: Place): string {
  const url = new URL("https://uri.amap.com/marker");
  url.searchParams.set("position", `${place.coordinate.longitude},${place.coordinate.latitude}`);
  url.searchParams.set("name", place.name);
  url.searchParams.set("src", "shadow-travel");
  url.searchParams.set("coordinate", "gaode");
  url.searchParams.set("callnative", "1");
  return url.toString();
}

function amapRouteUrl(stops: Place[], mode: "walking" | "transit" | "driving" | "bicycling"): string | undefined {
  if (stops.length < 2) return undefined;
  const first = stops[0];
  const last = stops[stops.length - 1];
  const url = new URL("https://uri.amap.com/navigation");
  url.searchParams.set("from", `${first.coordinate.longitude},${first.coordinate.latitude},${first.name}`);
  url.searchParams.set("to", `${last.coordinate.longitude},${last.coordinate.latitude},${last.name}`);
  if (stops.length > 2) {
    const via = stops[Math.floor(stops.length / 2)];
    url.searchParams.set("via", `${via.coordinate.longitude},${via.coordinate.latitude},${via.name}`);
  }
  url.searchParams.set("mode", { walking: "walk", transit: "bus", driving: "car", bicycling: "ride" }[mode]);
  url.searchParams.set("policy", "0");
  url.searchParams.set("src", "shadow-travel");
  url.searchParams.set("callnative", "1");
  return url.toString();
}

const amapProvider: ClientMapProvider = {
  id: "amap",
  label: "高德地图",
  coordinateSystem: "GCJ-02",
  externalPlaceUrl: amapExternalUrl,
  externalRouteUrl: amapRouteUrl
};

const googleProvider: ClientMapProvider = {
  id: "google",
  label: "Google Maps",
  coordinateSystem: "WGS-84",
  externalPlaceUrl: () => undefined,
  externalRouteUrl: () => undefined
};

export function mapProviderForCountry(countryCode = "CN"): ClientMapProvider {
  return countryCode.toUpperCase() === "CN" ? amapProvider : googleProvider;
}
