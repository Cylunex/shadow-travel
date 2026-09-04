import { request, basePath } from "../api";
import { isLocalReadMode, localEntries, localWrite } from "../offline";
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
};
export type Reservation = {
  id: string;
  title: string;
  day: string;
  time: string;
  kind: "stay" | "transport" | "ticket" | "other";
  note: string;
  source_ref?: string | null;
};
export type PrepTask = {
  id: string;
  title: string;
  done: boolean;
  due?: string | null;
  assignee?: string | null;
};
export type PlanDocument = {
  schema_version: 1;
  timezone?: string | null;
  candidates: string[];
  stops: Stop[];
  reservations: Reservation[];
  tasks: PrepTask[];
  budget: number | null;
  currency: string;
  constraints: string;
};
export type PlanState = {
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
  offline?: { downloaded_at: string; expires_at: string; notice: string };
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
  const pack = await api<PlanState>(`trips/${id}/pack`);
  await localWrite("pack", id, pack);
  await navigator.storage?.persist?.();
  return pack;
}
export const tripCalendarUrl = (id: string) =>
  `${basePath}api/browser/v1/trips/${id}/calendar.ics`;
