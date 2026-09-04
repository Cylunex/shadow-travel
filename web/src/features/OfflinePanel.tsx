import { useEffect, useState } from "react";
import { basePath } from "../api";
import {
  legacyQueueKey,
  localEntries,
  localDelete,
  localWrite,
  replayPendingVisits,
  type QueueItem,
} from "../offline";
import { useTravel } from "../state/TravelContext";
import { download, type PlanState } from "./lifecycle";

export function OfflinePanel() {
  const { refresh } = useTravel();
  const [queue, setQueue] = useState<{ id: string; value: QueueItem }[]>([]);
  const [packs, setPacks] = useState<{ id: string; value: PlanState }[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState("");
  const load = async () => {
    setQueue(await localEntries<QueueItem>("outbox"));
    setPacks(await localEntries<PlanState>("pack"));
    const estimate = await navigator.storage?.estimate?.();
    if (estimate)
      setUsage(
        `${((estimate.usage || 0) / 1048576).toFixed(1)} MB / ${((estimate.quota || 0) / 1048576).toFixed(0)} MB（同源总用量）`,
      );
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      try {
        await load();
      } catch (e) {
        setError((e as Error).message);
      }
      setBusy(false);
    }
  };
  return (
    <section className="settings-section">
      <header>
        <div>
          <span className="eyebrow">OFFLINE & SYNC</span>
          <h2>设备副本与待同步记录</h2>
        </div>
      </header>
      <p>
        只同步当前账号的记录。退出不会丢弃草稿；切换账号后隔离保留，恢复原账号才能上传。
      </p>
      <small>{usage}</small>
      <div className="compact-actions">
        <button
          className="secondary-button"
          disabled={busy || !navigator.onLine}
          onClick={() =>
            void run(async () => {
              await replayPendingVisits(basePath);
              await refresh();
            })
          }
        >
          同步 {queue.length} 条
        </button>
        <button
          className="secondary-button"
          disabled={!queue.length}
          onClick={() =>
            download(
              JSON.stringify(queue, null, 2),
              "travel-pending-visits.json",
            )
          }
        >
          导出未同步记录
        </button>
      </div>
      {error && (
        <p className="map-search-error" role="alert">
          {error}
        </p>
      )}
      {queue.map(({ id, value }) => (
        <article className="offline-entry" key={id}>
          <strong>
            {value.input.visited_on} ·{" "}
            {value.state === "conflict" ? "需要处理冲突" : "等待同步"}
          </strong>
          <p>{value.input.note || "无文字记录"}</p>
          {value.conflict && (
            <>
              <p>{value.conflict.code}</p>
              <details>
                <summary>比较服务器记录（仅当前账号）</summary>
                <pre>{JSON.stringify(value.conflict.current, null, 2)}</pre>
              </details>
            </>
          )}
          <div className="compact-actions">
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await localWrite("outbox", id, {
                    ...value,
                    state: "pending",
                    conflict: undefined,
                  });
                })
              }
            >
              保留草稿并重新尝试
            </button>
            <button
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm("先导出后移除此本地草稿？服务器记录不会改变。")
                )
                  void run(async () => {
                    download(JSON.stringify(value, null, 2), `${id}.json`);
                    await localDelete("outbox", id);
                    await refresh();
                  });
              }}
            >
              导出并移除本地草稿
            </button>
          </div>
        </article>
      ))}
      {packs.map(({ id, value }) => (
        <div className="prep-row" key={id}>
          <div>
            <strong>{value.trip.title}</strong>
            <small>
              有效至 {value.offline?.expires_at} · 不含底图和票据原件
            </small>
          </div>
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await localDelete("pack", id);
                await localDelete("workspace", "downloaded-trips");
              })
            }
          >
            清理副本
          </button>
        </div>
      ))}
      <p className="lifecycle-hint">
        清理副本不会删除
        Outbox。设备上保存的数据没有额外加密；请只在受信任的个人设备使用。
      </p>
      {localStorage.getItem(legacyQueueKey) && (
        <div className="lifecycle-alert">
          检测到旧版无账号归属的队列，不会自动上传。
          <button
            onClick={() =>
              download(
                localStorage.getItem(legacyQueueKey)!,
                "travel-legacy-unowned.json",
              )
            }
          >
            导出旧队列供核对
          </button>
        </div>
      )}
    </section>
  );
}
