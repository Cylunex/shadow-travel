import { useState } from "react";
import { googleDetails, type GooglePlace } from "../map/googleRuntime";
export function GooglePlaceDetails({ sourceId }: { sourceId: string }) {
  const [value, setValue] = useState<GooglePlace>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <section className="detail-section">
      <h2>Google Maps · 实时地点资料</h2>
      <p>
        以下是实时来源内容，不包含在导出和离线副本中；上方名称是你自己保存的别名。
      </p>
      <button
        className="secondary-button"
        disabled={busy || !navigator.onLine}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            setValue(await googleDetails(sourceId));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "读取中…" : value ? "重新读取" : "联网读取详情"}
      </button>
      {error && <p role="alert">{error}</p>}
      {value && (
        <>
          <h3>{value.name}</h3>
          <p>{value.address}</p>
          <p>
            {value.category} · {value.district}
          </p>
          <small>
            Google Maps
            {value.attributions.map((a, i) => (
              <span key={i}> · {a.provider}</span>
            ))}
          </small>
        </>
      )}
    </section>
  );
}
