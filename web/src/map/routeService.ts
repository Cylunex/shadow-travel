import { request } from "../api";
import type { Place } from "../types";
import {
  coordinateForAMap,
  placeToCoordinate,
  planAMapRoute,
  type MapCoordinate,
  type AMapRouteMode,
} from "./amapRuntime";
import { resolveGooglePlaces } from "./googleRuntime";
export type VerifiedRoute = {
  path: MapCoordinate[];
  distanceMeters: number | null;
  durationSeconds: number | null;
};
export async function routeForPlaces(
  stops: Place[],
  mode: AMapRouteMode,
  city?: string,
): Promise<VerifiedRoute> {
  if (stops.length < 2 || stops.length > 8) throw new Error("每次核验 2–8 站");
  const abroad = (p: Place) =>
    p.provider === "google" || (!!p.countryCode && p.countryCode !== "CN");
  if (stops.some(abroad) && !stops.every(abroad))
    throw new Error("跨地图服务区域路线需要分段规划，不能假定道路相通");
  if (!stops.every(abroad)) {
    const points = await Promise.all(
      stops.map(async (p) => {
        if (!p.coordinate) throw new Error("缺少坐标，无法核验路线");
        return coordinateForAMap(p.coordinate);
      }),
    );
    return planAMapRoute(points, mode, city);
  }
  if (mode === "transit" && stops.length !== 2)
    throw new Error("Google 公交逐段核验，不支持中途站点");
  const live = await resolveGooglePlaces(stops);
  const route = await request<{
    points: MapCoordinate[];
    distance_meters: number | null;
    duration_seconds: number | null;
  }>("api/browser/v1/maps/routes", {
    method: "POST",
    cache: "no-store",
    body: JSON.stringify({
      country_code: stops[0].countryCode || "ZZ",
      mode,
      stops: live.map((p) => ({
        ...placeToCoordinate(p),
        coordinate_reference: "WGS84",
      })),
    }),
  });
  return {
    path: route.points,
    distanceMeters: route.distance_meters,
    durationSeconds: route.duration_seconds,
  };
}
