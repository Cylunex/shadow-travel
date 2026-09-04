import { request, basePath } from "../api";
import {
  isLocalReadMode,
  localEntries,
  localWrite,
  currentOfflineUser,
} from "../offline";
import type { Place, Trip, Visit } from "../types";

export type Stop = {
  id: string;
  place_id: string;
  day: string;
  start: string;
  duration_minutes: number;
  travel_minutes: number | null;
  mode: "walking" | "transit" | "driving" | "bicycling";
  anchor: boolean;
  note: string;
  timezone?: string | null;
  fold?: 0 | 1 | null;
  reservation_refs?: string[];
};
export type Reservation = {
  id: string;
  title: string;
  day: string;
  time: string;
  kind: "stay" | "transport" | "ticket" | "other";
  note: string;
  source_ref?: string | null;
  timezone?: string | null;
  fold?: 0 | 1 | null;
};
export type PrepTask = {
  id: string;
  title: string;
  done: boolean;
  due?: string | null;
  assignee?: string | null;
};
export type PlanDocument = {
  schema_version: 1 | 2;
  segments?: {
    id: string;
    from_stop_id: string;
    to_stop_id: string;
    mode: Stop["mode"];
    manual_minutes: number | null;
    note: string;
  }[];
  migration_notes?: string[];
  timezone?: string | null;
  candidates: string[];
  candidate_metadata?: Record<
    string,
    {
      priority: "optional" | "normal" | "must";
      reason: string;
      duration_minutes: number;
      alternate_group: string | null;
    }
  >;
  stops: Stop[];
  reservations: Reservation[];
  tasks: PrepTask[];
  budget: number | null;
  currency: string;
  constraints: string;
};
export type PlanState = {
  manifest?: {
    schema_version: 2;
    owner: string;
    instance: string;
    plan_revision: number;
    run_plan_revision: number | null;
    content_scope: string[];
    sha256: string;
  };
  trip: Trip;
  role: "owner" | "editor" | "viewer";
  revision: number;
  approved_revision: number | null;
  document: PlanDocument;
  places: Place[];
  members: { id: string; name: string; role: string }[];
  versions: { revision: number; document: PlanDocument; created_at: string }[];
  checks: { errors: { message: string }[]; warnings: { message: string }[] };
  visits?: Visit[];
  run?: RunState | null;
  offline?: { downloaded_at: string; expires_at: string; notice: string };
};
export type OutcomeState =
  "pending" | "in_progress" | "completed" | "skipped" | "deferred";
export type StopOutcome = {
  stop_id: string;
  member_id: string;
  state: OutcomeState;
  revision?: number;
  shared?: boolean;
  visit_id?: string;
  actual_at?: string;
};
export type RunState = {
  id: string;
  trip_id: string;
  plan_revision: number;
  revision: number;
  member_id: string;
  document: PlanDocument;
  outcomes: StopOutcome[];
  bindings: { revision: number; at: string; reason: string }[];
};
export type OutcomeCommand = {
  operation_id: string;
  run_id: string;
  plan_revision: number;
  stop_id: string;
  base_revision: number;
  state: OutcomeState;
  shared: boolean;
  visit_date?: string;
  reuse_visit_id?: string;
};
export type Capture = {
  id: string;
  text: string;
  source_url?: string;
  reason: string;
  status: string;
  place_id?: string;
  created_at: string;
};
export type Memory = {
  id: string;
  kind: "memory" | "journey" | "trail";
  trip_id?: string;
  title: string;
  occurred_on: string;
  document: {
    text?: string;
    visit_ids?: string[];
    photo_ids?: string[];
    memory_ids?: string[];
    point_count?: number;
    distance_meters?: number;
    segments?: {
      longitude: number;
      latitude: number;
      elevation: number | null;
      time: string | null;
    }[][];
  };
  visibility: "private";
};

export function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  return request<T>(`api/browser/v1/${path}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export function download(
  content: string,
  name: string,
  type = "application/json",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function tripList(): Promise<Trip[]> {
  if (!navigator.onLine || isLocalReadMode())
    return (await localEntries<PlanState>("pack"))
      .filter((row) => new Date(row.value.offline!.expires_at) > new Date())
      .map((row) => row.value.trip);
  return (await api<{ trips: Trip[] }>("journeys/trips")).trips;
}
export async function readPlan(id: string): Promise<PlanState> {
  if (navigator.onLine && !isLocalReadMode())
    return api<PlanState>(`trips/${id}/plan`);
  const cached = (await localEntries<PlanState>("pack")).find(
    (row) => row.id === id,
  )?.value;
  if (!cached || new Date(cached.offline!.expires_at) < new Date())
    throw new Error("此旅程未下载或离线授权已过期，请联网重新下载");
  return cached;
}
export async function downloadPack(id: string) {
  const owner = currentOfflineUser();
  const response = await fetch(`${basePath}api/browser/v1/trips/${id}/pack`, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-Travel-Owner": owner },
  });
  if (!response.ok)
    throw new Error(`下载旅行副本失败：HTTP ${response.status}`);
  const content = await response.text();
  const pack = JSON.parse(content) as PlanState;
  if (pack.manifest) {
    if (
      pack.manifest.owner !== owner ||
      owner !== currentOfflineUser() ||
      pack.manifest.instance !== location.origin
    )
      throw new Error("旅行副本账号或实例不匹配，未保存");
    const hash = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(content),
    );
    const actual = [...new Uint8Array(hash)]
      .map((n) => n.toString(16).padStart(2, "0"))
      .join("");
    if (actual !== response.headers.get("X-Travel-Pack-SHA256"))
      throw new Error("旅行副本完整性校验失败，未保存；请重新下载");
  }
  await localWrite("pack", id, pack);
  await navigator.storage?.persist?.();
  return pack;
}
export const tripCalendarUrl = (id: string) =>
  `${basePath}api/browser/v1/trips/${id}/calendar.ics`;
