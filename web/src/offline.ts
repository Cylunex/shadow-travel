import type { Visit } from "./types";

const queueKey = "shadow-travel-offline-visits-v1";

export type OfflineVisitInput = {
  map_id?: string;
  trip_id?: string;
  visited_on: string;
  note: string;
  rating?: number;
  client_record_id: string;
};

type QueueItem = {
  idempotencyKey: string;
  placeId: string;
  input: OfflineVisitInput;
  state: "pending" | "conflict";
  conflict?: { code: string; current?: unknown };
  queuedAt: string;
};

function loadQueue(): QueueItem[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(queueKey) ?? "[]") as unknown;
    return Array.isArray(value) ? value.filter(isQueueItem) : [];
  } catch {
    return [];
  }
}

function saveQueue(items: QueueItem[]): void {
  window.localStorage.setItem(queueKey, JSON.stringify(items.slice(-500)));
}

function isQueueItem(value: unknown): value is QueueItem {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<QueueItem>;
  return typeof item.idempotencyKey === "string" && typeof item.placeId === "string"
    && typeof item.input === "object" && item.input !== null;
}

export function stableClientId(prefix = "visit"): string {
  return `${prefix}:${crypto.randomUUID()}`;
}

export function pendingVisits(): Visit[] {
  return loadQueue().map((item) => ({
    id: `local:${item.input.client_record_id}`,
    clientRecordId: item.input.client_record_id,
    version: 1,
    placeId: item.placeId,
    date: item.input.visited_on,
    displayDate: item.input.visited_on,
    note: item.input.note,
    rating: item.input.rating,
    photoCount: 0,
    mapId: item.input.map_id,
    tripId: item.input.trip_id,
    syncState: item.state,
    conflict: item.conflict
  }));
}

export function queueVisit(placeId: string, input: OfflineVisitInput): Visit {
  const items = loadQueue();
  if (!items.some((item) => item.input.client_record_id === input.client_record_id)) {
    items.push({
      idempotencyKey: input.client_record_id,
      placeId,
      input,
      state: "pending",
      queuedAt: new Date().toISOString()
    });
    saveQueue(items);
  }
  return pendingVisits().find((visit) => visit.clientRecordId === input.client_record_id)!;
}

export async function submitQueuedVisit(basePath: string, placeId: string, input: OfflineVisitInput): Promise<Visit> {
  const response = await fetch(`${basePath}api/browser/v1/places/${encodeURIComponent(placeId)}/visits`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": input.client_record_id,
      "X-Correlation-Id": input.client_record_id
    },
    body: JSON.stringify(input)
  });
  if (response.status === 409) {
    const payload = await response.json() as { detail?: { code?: string; current?: unknown } };
    throw Object.assign(new Error(payload.detail?.code ?? "offline_conflict"), {
      conflict: { code: payload.detail?.code ?? "offline_conflict", current: payload.detail?.current }
    });
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { ...(await response.json() as Visit), syncState: "synced" };
}

export async function replayPendingVisits(basePath: string): Promise<void> {
  if (!navigator.onLine) return;
  const items = loadQueue();
  const remaining: QueueItem[] = [];
  for (const item of items) {
    if (item.state === "conflict") {
      remaining.push(item);
      continue;
    }
    try {
      await submitQueuedVisit(basePath, item.placeId, item.input);
    } catch (error) {
      const conflict = (error as { conflict?: QueueItem["conflict"] }).conflict;
      remaining.push(conflict ? { ...item, state: "conflict", conflict } : item);
      if (!conflict) break;
    }
  }
  saveQueue(remaining);
}
