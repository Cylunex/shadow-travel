import { Place, Preference, TravelMap, TravelRoute, Visit } from "./types";

export type CurrentUser = {
  shadow_user_id: string;
  username: string;
  display_name: string;
  email: string;
};

export const basePath = import.meta.env.BASE_URL;

export type TravelWorkspace = {
  maps: TravelMap[];
  places: Place[];
  visits: Visit[];
  routes: TravelRoute[];
  members: TravelMap["members"];
};

export async function currentUser(signal?: AbortSignal): Promise<CurrentUser | null> {
  const response = await fetch(`${basePath}api/browser/v1/me`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal
  });
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Travel API returned HTTP ${response.status}`);
  }
  return (await response.json()) as CurrentUser;
}

export function login(): void {
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const target = `${basePath}auth/login?return_to=${encodeURIComponent(returnTo)}`;
  window.location.replace(target);
}

export async function logout(): Promise<void> {
  await request("auth/logout", { method: "POST" });
  window.location.assign(basePath);
}

export async function loadWorkspace(signal?: AbortSignal): Promise<TravelWorkspace> {
  return request<TravelWorkspace>("api/browser/v1/workspace", { signal });
}

export async function createTravelMap(input: {
  title: string;
  city: string;
  subtitle: string;
}): Promise<TravelMap> {
  return request<TravelMap>("api/browser/v1/travel-maps", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function createTravelPlace(mapId: string, input: {
  name: string;
  address: string;
  city: string;
  district: string;
  category?: string;
  providerPlaceId?: string;
  longitude: number;
  latitude: number;
  note?: string;
}): Promise<Place> {
  return request<Place>(`api/browser/v1/travel-maps/${mapId}/places`, {
    method: "POST",
    body: JSON.stringify({
      ...input,
      category: input.category?.split(";")[0]?.split("|")[0] || "地点",
      provider: input.providerPlaceId ? "amap" : "manual",
      provider_place_id: input.providerPlaceId,
      coordinate_reference: "GCJ02"
    })
  });
}

export async function updatePlacePreference(placeId: string, preference: Preference): Promise<void> {
  await request(`api/browser/v1/places/${placeId}/preference`, {
    method: "PUT",
    body: JSON.stringify({ preference })
  });
}

export async function updateTravelPlace(
  placeId: string,
  input: { note?: string; name?: string; category?: string; tags?: string[] }
): Promise<void> {
  await request(`api/browser/v1/places/${placeId}`, {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export async function createVisit(placeId: string, input: {
  mapId?: string;
  visitedOn?: string;
  note?: string;
  rating?: number;
} = {}): Promise<Visit> {
  const today = input.visitedOn || new Date().toISOString().slice(0, 10);
  return request<Visit>(`api/browser/v1/places/${placeId}/visits`, {
    method: "POST",
    body: JSON.stringify({
      map_id: input.mapId,
      visited_on: today,
      note: input.note || "",
      rating: input.rating
    })
  });
}

export async function updateTravelRoute(routeId: string, stopIds: string[]): Promise<TravelRoute> {
  return request<TravelRoute>(`api/browser/v1/routes/${routeId}`, {
    method: "PATCH",
    body: JSON.stringify({ stop_ids: stopIds })
  });
}

async function request<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${basePath}${path}`, {
    ...init,
    credentials: "same-origin",
    headers
  });
  if (!response.ok) {
    let code = `HTTP ${response.status}`;
    try {
      const payload = await response.json() as { detail?: { code?: string } };
      code = payload.detail?.code || code;
    } catch {
      // Keep the safe status-only fallback.
    }
    throw new Error(`操作失败：${code}`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}
