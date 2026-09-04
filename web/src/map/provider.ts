import { Place } from "../types";

export interface ClientMapProvider {
  readonly id: "amap" | "google";
  readonly label: string;
  readonly coordinateSystem: "GCJ-02" | "WGS-84";
  externalPlaceUrl(place: Place): string | undefined;
  externalRouteUrl(
    stops: Place[],
    mode: "walking" | "transit" | "driving" | "bicycling",
  ): string | undefined;
}

function amapExternalUrl(place: Place): string {
  if (!place.coordinate) return "";
  const url = new URL("https://uri.amap.com/marker");
  url.searchParams.set(
    "position",
    `${place.coordinate.longitude},${place.coordinate.latitude}`,
  );
  url.searchParams.set("name", place.name);
  url.searchParams.set("src", "shadow-travel");
  url.searchParams.set(
    "coordinate",
    place.coordinate.reference === "WGS84" ? "wgs84" : "gaode",
  );
  url.searchParams.set("callnative", "1");
  return url.toString();
}

function amapRouteUrl(
  stops: Place[],
  mode: "walking" | "transit" | "driving" | "bicycling",
): string | undefined {
  if (
    stops.length < 2 ||
    stops.some((p) => !p.coordinate || p.provider === "google")
  )
    return undefined;
  // URI API accepts one via point, and only for driving. Never silently drop stops.
  if (
    stops.length > (mode === "driving" ? 3 : 2) ||
    stops.some((p) => p.coordinate?.reference === "WGS84")
  )
    return undefined;
  const first = stops[0];
  const last = stops[stops.length - 1];
  const url = new URL("https://uri.amap.com/navigation");
  url.searchParams.set(
    "from",
    `${first.coordinate!.longitude},${first.coordinate!.latitude},${first.name}`,
  );
  url.searchParams.set(
    "to",
    `${last.coordinate!.longitude},${last.coordinate!.latitude},${last.name}`,
  );
  if (stops.length === 3 && mode === "driving") {
    const via = stops[1];
    url.searchParams.set(
      "via",
      `${via.coordinate!.longitude},${via.coordinate!.latitude},${via.name}`,
    );
  }
  url.searchParams.set(
    "mode",
    { walking: "walk", transit: "bus", driving: "car", bicycling: "ride" }[
      mode
    ],
  );
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
  externalRouteUrl: amapRouteUrl,
};

const googleProvider: ClientMapProvider = {
  id: "google",
  label: "Google Maps",
  coordinateSystem: "WGS-84",
  externalPlaceUrl: (place) => {
    if (
      !(place.provider === "google" && place.providerPlaceId) &&
      (!place.coordinate || place.coordinate.reference !== "WGS84")
    )
      return undefined;
    const url = new URL("https://www.google.com/maps/search/");
    url.searchParams.set("api", "1");
    url.searchParams.set(
      "query",
      place.coordinate
        ? `${place.coordinate.latitude},${place.coordinate.longitude}`
        : place.name,
    );
    if (place.provider === "google" && place.providerPlaceId)
      url.searchParams.set("query_place_id", place.providerPlaceId);
    return url.toString();
  },
  externalRouteUrl: (stops, mode) => {
    // Mobile Maps URLs support at most three intermediate waypoints.
    if (
      stops.length < 2 ||
      stops.length > 5 ||
      (mode === "transit" && stops.length > 2) ||
      stops.some(
        (p) =>
          p.provider !== "google" &&
          (!p.coordinate || p.coordinate.reference !== "WGS84"),
      )
    )
      return undefined;
    const url = new URL("https://www.google.com/maps/dir/");
    const label = (p: Place) =>
      p.coordinate
        ? `${p.coordinate.latitude},${p.coordinate.longitude}`
        : p.name;
    url.searchParams.set("api", "1");
    url.searchParams.set("travelmode", mode);
    url.searchParams.set("origin", label(stops[0]));
    url.searchParams.set("destination", label(stops.at(-1)!));
    if (stops[0].provider === "google" && stops[0].providerPlaceId)
      url.searchParams.set("origin_place_id", stops[0].providerPlaceId);
    if (stops.at(-1)!.provider === "google" && stops.at(-1)!.providerPlaceId)
      url.searchParams.set(
        "destination_place_id",
        stops.at(-1)!.providerPlaceId!,
      );
    const via = stops.slice(1, -1);
    if (via.length) {
      url.searchParams.set("waypoints", via.map(label).join("|"));
      if (via.every((p) => p.provider === "google" && p.providerPlaceId))
        url.searchParams.set(
          "waypoint_place_ids",
          via.map((p) => p.providerPlaceId).join("|"),
        );
    }
    return url.toString().length <= 2048 ? url.toString() : undefined;
  },
};

export function mapProviderForCountry(countryCode = "CN"): ClientMapProvider {
  return countryCode.toUpperCase() === "CN" ? amapProvider : googleProvider;
}
