import { useEffect, useState } from "react";
import { localDelete } from "../offline";
import { download } from "./lifecycle";
import {
  pendingCommands,
  replayRuntimeCommands,
  type PendingCommand,
} from "./runtimeOffline";
export function RuntimeQueuePanel() {
  const [rows, setRows] = useState<{ id: string; value: PendingCommand }[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () =>
    pendingCommands()
      .then(setRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
    window.addEventListener("runtime-queue-changed", load);
    return () => window.removeEventListener("runtime-queue-changed", load);
  }, []);
  return (
    <section className="settings-section">
      <h3>旅途中操作 · {rows.length} 条待处理</h3>
      <p>
        到访创建与站次完成作为一个操作同步。冲突不自动覆盖；请先导出，核对最新计划后重新操作。
      </p>
      <div className="compact-actions">
        <button
          disabled={busy || !navigator.onLine || !rows.length}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await replayRuntimeCommands();
              await load();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          同步站次操作
        </button>
        <button
          disabled={!rows.length}
          onClick={() =>
            download(
              JSON.stringify(rows, null, 2),
              "travel-runtime-pending.json",
            )
          }
        >
          导出待处理操作
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {rows.map((row) => (
        <article key={row.id} className="offline-entry">
          <strong>
            {row.value.command.stop_id} ·{" "}
            {row.value.state === "conflict" ? "需人工处理" : "待同步"}
          </strong>
          <p>
            {row.value.command.state} · {row.value.error || row.value.queuedAt}
          </p>
          <button
            disabled={busy}
            onClick={async () => {
              if (
                !window.confirm(
                  "此操作可能已在服务器成功，但回执尚未收到。建议先同步或导出；确定只移除本机待处理副本？",
                )
              )
                return;
              try {
                await localDelete("runtime-outbox", row.id);
                await load();
                window.dispatchEvent(new Event("runtime-queue-changed"));
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            移除本机副本
          </button>
        </article>
      ))}
    </section>
  );
}
