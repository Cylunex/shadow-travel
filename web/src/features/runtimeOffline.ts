import { basePath } from "../api";
import {
  currentOfflineUser,
  isLocalReadMode,
  offlineOwner,
  localEntries,
  localWrite,
  localDelete,
} from "../offline";
import type { OutcomeCommand, PlanState, RunState } from "./lifecycle";

export type PendingCommand = {
  tripId: string;
  command: OutcomeCommand;
  state: "pending" | "conflict";
  queuedAt: string;
  error?: string;
};
export const pendingCommands = () =>
  localEntries<PendingCommand>("runtime-outbox");
async function send(tripId: string, command: OutcomeCommand, owner: string) {
  const response = await fetch(
    `${basePath}api/browser/v1/trips/${tripId}/run/commands`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Travel-Owner": owner },
      body: JSON.stringify(command),
    },
  );
  const payload = await response.json();
  if (!response.ok)
    throw Object.assign(
      new Error(payload.detail?.code || `HTTP ${response.status}`),
      { status: response.status, detail: payload.detail },
    );
  return payload as { run: RunState };
}
export async function submitCommand(tripId: string, command: OutcomeCommand) {
  // One pending operation per member/stop; explicit conflict resolution, never last-write-wins.
  const pending = await pendingCommands();
  if (
    pending.some(
      (e) =>
        e.value.command.run_id === command.run_id &&
        e.value.command.stop_id === command.stop_id,
    )
  )
    throw new Error("此站已有待同步操作，请先同步或在离线管理中处理");
  const scope = offlineOwner(),
    owner = currentOfflineUser();
  const online = navigator.onLine && !isLocalReadMode();
  if (!online) {
    const pack = (await localEntries<PlanState>("pack", scope)).find(
      (p) => p.id === tripId,
    )?.value;
    if (
      !pack?.run ||
      pack.run.id !== command.run_id ||
      !pack.offline ||
      new Date(pack.offline.expires_at) < new Date()
    )
      throw new Error("请先联网开始旅途中模式并重新下载旅行副本，再离线执行");
  }
  // Write-ahead receipt survives a lost HTTP response, even without a downloaded Pack.
  await localWrite(
    "runtime-outbox",
    command.operation_id,
    {
      tripId,
      command,
      state: "pending",
      queuedAt: new Date().toISOString(),
    } satisfies PendingCommand,
    scope,
  );
  if (online) {
    try {
      const result = await send(tripId, command, owner);
      await localDelete("runtime-outbox", command.operation_id, scope);
      return result;
    } catch (error) {
      const status = (error as { status?: number }).status;
      if (status && status < 500) {
        await localDelete("runtime-outbox", command.operation_id, scope);
        throw error; // Transaction rejected: caller can explicitly resolve/reuse.
      }
    }
  }
  window.dispatchEvent(new Event("runtime-queue-changed"));
  return null;
}
let replaying: Promise<void> | undefined;
export async function replayRuntimeCommands() {
  if (!navigator.onLine) return;
  if (replaying) return replaying;
  const scope = offlineOwner(),
    owner = currentOfflineUser();
  const work = async () => {
    const rows = await localEntries<PendingCommand>("runtime-outbox", scope);
    for (const entry of rows.sort((a, b) =>
      a.value.queuedAt.localeCompare(b.value.queuedAt),
    )) {
      if (entry.value.state === "conflict") continue;
      const session = await fetch(`${basePath}api/browser/v1/me`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (
        !session.ok ||
        (await session.json()).shadow_user_id !== owner ||
        offlineOwner() !== scope
      )
        throw new Error("账号变化，停止同步");
      try {
        await send(entry.value.tripId, entry.value.command, owner);
        await localDelete("runtime-outbox", entry.id, scope);
      } catch (error) {
        const status = (error as { status?: number }).status;
        if (
          status === 409 ||
          status === 403 ||
          status === 404 ||
          status === 422
        ) {
          await localWrite(
            "runtime-outbox",
            entry.id,
            {
              ...entry.value,
              state: "conflict",
              error: (error as Error).message,
            },
            scope,
          );
        } else throw error;
      }
    }
    window.dispatchEvent(new Event("runtime-queue-changed"));
  };
  replaying = (
    navigator.locks
      ? navigator.locks.request(`runtime-replay:${scope}`, work)
      : work()
  ).finally(() => {
    replaying = undefined;
  });
  return replaying;
}
