import type { Visit } from "./types";

// The legacy unowned queue is deliberately NOT replayed. Settings offers an export.
export const legacyQueueKey = "shadow-travel-offline-visits-v1";
let owner = "";
let ownerUserId = "";
let localReadMode = false;
export function setLocalReadMode(value: boolean) {
  localReadMode = value;
}
export function isLocalReadMode() {
  return localReadMode;
}
export function currentOfflineUser() {
  return ownerUserId;
}
export function configureOffline(userId: string, basePath: string) {
  ownerUserId = userId;
  owner = `${location.origin}${basePath}:${userId}`;
}
export function offlineOwner() {
  if (!owner) throw new Error("请先确认当前账号");
  return owner;
}
const database = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const opening = indexedDB.open("shadow-travel-local-v2", 1);
    opening.onupgradeneeded = () =>
      opening.result.createObjectStore("entries", { keyPath: "key" });
    opening.onsuccess = () => resolve(opening.result);
    opening.onerror = () =>
      reject(new Error("无法打开本地存储，请导出数据或检查浏览器存储权限"));
  });
type Entry<T> = {
  key: string;
  owner: string;
  kind: string;
  id: string;
  value: T;
};
export async function localEntries<T>(
  kind: string,
  scope = offlineOwner(),
): Promise<Entry<T>[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("entries").objectStore("entries").getAll();
      request.onsuccess = () =>
        resolve(
          (request.result as Entry<T>[]).filter(
            (item) => item.owner === scope && item.kind === kind,
          ),
        );
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}
export async function localWrite<T>(
  kind: string,
  id: string,
  value: T,
  scope = offlineOwner(),
): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("entries", "readwrite");
      tx.objectStore("entries").put({
        key: `${scope}:${kind}:${id}`,
        owner: scope,
        kind,
        id,
        value,
      });
      tx.oncomplete = () => resolve();
      tx.onerror = () =>
        reject(
          new Error("保存到设备失败（空间不足或存储不可用）；此操作尚未保存"),
        );
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
export async function localDelete(
  kind: string,
  id: string,
  scope = offlineOwner(),
): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("entries", "readwrite");
      tx.objectStore("entries").delete(`${scope}:${kind}:${id}`);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
export type OfflineVisitInput = {
  map_id?: string;
  trip_id?: string;
  visited_on: string;
  note: string;
  rating?: number;
  client_record_id: string;
};
export type QueueItem = {
  placeId: string;
  input: OfflineVisitInput;
  state: "pending" | "conflict";
  conflict?: Visit["conflict"];
  queuedAt: string;
  payloadHash?: string;
};
export function stableClientId(prefix = "visit"): string {
  return `${prefix}:${crypto.randomUUID()}`;
}
function asVisit(item: QueueItem): Visit {
  return {
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
    conflict: item.conflict,
  };
}
export async function pendingVisits(): Promise<Visit[]> {
  return (await localEntries<QueueItem>("outbox")).map((entry) =>
    asVisit(entry.value),
  );
}
export async function queueVisit(
  placeId: string,
  input: OfflineVisitInput,
): Promise<Visit> {
  const existing = (await localEntries<QueueItem>("outbox")).find(
    (entry) => entry.id === input.client_record_id,
  );
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify({ placeId, input })),
  );
  const payloadHash = Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  if (existing) {
    if (existing.value.payloadHash !== payloadHash)
      throw new Error("同一客户端记录 ID 已用于其他内容；原记录仍保留");
    return asVisit(existing.value);
  }
  const item: QueueItem = {
    placeId,
    input,
    state: "pending",
    queuedAt: new Date().toISOString(),
    payloadHash,
  };
  await localWrite("outbox", input.client_record_id, item);
  return asVisit(item);
}
export async function submitQueuedVisit(
  basePath: string,
  placeId: string,
  input: OfflineVisitInput,
  expectedUser = ownerUserId,
): Promise<Visit> {
  const response = await fetch(
    `${basePath}api/browser/v1/places/${encodeURIComponent(placeId)}/visits`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": input.client_record_id,
        "X-Correlation-Id": input.client_record_id,
        "X-Travel-Owner": expectedUser,
      },
      body: JSON.stringify(input),
    },
  );
  if (response.status === 409) {
    const payload = (await response.json()) as {
      detail?: { code?: string; current?: unknown };
    };
    throw Object.assign(new Error(payload.detail?.code ?? "offline_conflict"), {
      conflict: {
        code: payload.detail?.code ?? "offline_conflict",
        current: payload.detail?.current,
      },
    });
  }
  if (!response.ok)
    throw new Error(
      `HTTP ${response.status}：记录仍保留在设备中，请恢复原账号登录或检查权限`,
    );
  return { ...((await response.json()) as Visit), syncState: "synced" };
}
let replaying: Promise<void> | undefined;
export async function replayPendingVisits(basePath: string): Promise<void> {
  if (!navigator.onLine) return;
  if (replaying) return replaying;
  const scope = offlineOwner();
  const userId = ownerUserId;
  const run = async () => {
    const items = await localEntries<QueueItem>("outbox", scope);
    for (const entry of items) {
      if (entry.value.state === "conflict") continue;
      const session = await fetch(`${basePath}api/browser/v1/me`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (
        !session.ok ||
        scope !== owner ||
        `${location.origin}${basePath}:${(await session.json()).shadow_user_id}` !==
          scope
      )
        throw new Error("账号已变化：离线记录只会由原账号同步");
      try {
        setLocalReadMode(false);
        await submitQueuedVisit(
          basePath,
          entry.value.placeId,
          entry.value.input,
          userId,
        );
        await localDelete("outbox", entry.id, scope);
      } catch (error) {
        const conflict = (error as { conflict?: Visit["conflict"] }).conflict;
        if (!conflict) throw error;
        await localWrite(
          "outbox",
          entry.id,
          { ...entry.value, state: "conflict", conflict },
          scope,
        );
      }
    }
  };
  replaying = (
    navigator.locks
      ? navigator.locks.request(`travel-replay:${scope}`, run)
      : run()
  ).finally(() => {
    replaying = undefined;
  });
  return replaying;
}
