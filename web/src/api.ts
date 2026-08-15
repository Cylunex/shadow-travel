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

export type TravelCapabilities = {
  media: boolean;
  llm: boolean;
  international_maps: boolean;
};

export type RouteDraft = {
  id: string;
  map_id: string;
  status: string;
  draft_type: "route";
  payload: {
    title: string;
    ordered_place_ids: string[];
    summary: string;
    stop_notes: Array<{ place_id: string; note: string }>;
    mode: TravelRoute["mode"];
    requested_goal: string;
  };
};

export type PhotoRecord = {
  id: string;
  media_id: string;
  map_id: string;
  place_id: string;
  visit_id?: string;
  caption: string;
  captured_at?: string;
  has_private_location: boolean;
  exif_policy: "strip_all";
  created_at: string;
};

export type CollaborationState = {
  my_role: "owner" | "editor" | "viewer";
  members: Array<{ id: string; name: string; username: string; role: "owner" | "editor" | "viewer"; joined_at: string }>;
  invitations: Array<{ id: string; map_id: string; role: "editor" | "viewer"; expires_at: string }>;
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

export async function loadCapabilities(signal?: AbortSignal): Promise<TravelCapabilities> {
  return request<TravelCapabilities>("api/browser/v1/capabilities", { signal });
}

export async function createTravelMap(input: {
  title: string;
  city: string;
  subtitle: string;
  routeEnabled?: boolean;
}): Promise<TravelMap> {
  return request<TravelMap>("api/browser/v1/travel-maps", {
    method: "POST",
    body: JSON.stringify({ ...input, route_enabled: input.routeEnabled ?? false })
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

export async function updateTravelRoute(
  routeId: string,
  input: { stopIds?: string[]; mode?: TravelRoute["mode"] }
): Promise<TravelRoute> {
  return request<TravelRoute>(`api/browser/v1/routes/${routeId}`, {
    method: "PATCH",
    body: JSON.stringify({ stop_ids: input.stopIds, mode: input.mode })
  });
}

export async function createAssistantRouteDraft(
  mapId: string,
  input: { goal: string; mode: TravelRoute["mode"]; maxStops?: number }
): Promise<RouteDraft> {
  return request<RouteDraft>(`api/browser/v1/travel-maps/${mapId}/assistant/route-drafts`, {
    method: "POST",
    body: JSON.stringify({ goal: input.goal, mode: input.mode, max_stops: input.maxStops ?? 8 })
  });
}

export async function applyAgentDraft(draftId: string): Promise<{ draft: RouteDraft; route: TravelRoute }> {
  return request<{ draft: RouteDraft; route: TravelRoute }>(`api/browser/v1/agent-drafts/${draftId}/apply`, {
    method: "POST"
  });
}

export async function loadPlacePhotos(mapId: string, placeId: string): Promise<PhotoRecord[]> {
  const payload = await request<{ photos: PhotoRecord[] }>(`api/browser/v1/travel-maps/${mapId}/places/${placeId}/photos`);
  return payload.photos;
}

export async function loadPhotoUrl(photoId: string): Promise<string> {
  const payload = await request<{ url: string }>(`api/browser/v1/photos/${photoId}/access`, { method: "POST" });
  return payload.url;
}

export async function uploadPlacePhoto(
  mapId: string,
  placeId: string,
  file: File,
  caption = ""
): Promise<PhotoRecord> {
  const upload = await request<{
    intent_id: string;
    target: { method?: string; url: string; headers?: Record<string, string> };
  }>(`api/browser/v1/travel-maps/${mapId}/places/${placeId}/photos/uploads`, {
    method: "POST",
    body: JSON.stringify({
      original_filename: file.name,
      content_type: file.type,
      size_bytes: file.size,
      caption
    })
  });
  const targetResponse = await fetch(upload.target.url, {
    method: upload.target.method || "PUT",
    headers: upload.target.headers,
    body: file
  });
  if (!targetResponse.ok) throw new Error(`图片上传失败：HTTP ${targetResponse.status}`);
  return request<PhotoRecord>(`api/browser/v1/travel-maps/${mapId}/places/${placeId}/photos/complete`, {
    method: "POST",
    body: JSON.stringify({ intent_id: upload.intent_id })
  });
}

export async function loadCollaboration(mapId: string): Promise<CollaborationState> {
  return request<CollaborationState>(`api/browser/v1/travel-maps/${mapId}/collaboration`);
}

export async function createMapInvitation(
  mapId: string,
  role: "editor" | "viewer" = "editor"
): Promise<{ id: string; token: string; expires_at: string; role: string }> {
  return request(`api/browser/v1/travel-maps/${mapId}/invitations`, {
    method: "POST",
    body: JSON.stringify({ role, expires_in_days: 7 })
  });
}

export async function acceptMapInvitation(token: string): Promise<{ map_id: string }> {
  return request<{ map_id: string }>("api/browser/v1/invitations/accept", {
    method: "POST",
    body: JSON.stringify({ token })
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
