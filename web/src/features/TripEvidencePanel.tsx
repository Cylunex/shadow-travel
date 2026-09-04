import { useState } from "react";
import { request } from "../api";
import type { Place } from "../types";
import { resolveGooglePlaces } from "../map/googleRuntime";
import { routeForPlaces, type VerifiedRoute } from "../map/routeService";
import type { Stop, PlanDocument } from "./lifecycle";
import { orderedStops } from "./planTime";
type Forecast = {
  date: string;
  fetched_at: string;
  timezone?: string;
  description?: string;
  minimum?: { degrees: number };
  maximum?: { degrees: number };
  notice: string;
};
type Matrix = {
  fetched_at: string;
  elements: number;
  cells: {
    origin_index: number;
    destination_index: number;
    status: string;
    duration_seconds: number | null;
  }[];
};
export function TripEvidencePanel({
  stops,
  places,
  day,
  document,
  timezone,
}: {
  stops: Stop[];
  places: Place[];
  day: string;
  document: PlanDocument;
  timezone: string;
}) {
  const all = orderedStops(stops, document.timezone || timezone);
  const ordered = all.filter((s) => s.day === day);
  const [id, setId] = useState("");
  const stop = ordered.find((s) => s.id === id) || ordered[0];
  const place = places.find((p) => p.id === stop?.place_id);
  const nextStop = all[all.findIndex((s) => s.id === stop?.id) + 1];
  const next = places.find((p) => p.id === nextStop?.place_id);
  const mode =
    (document.schema_version === 2
      ? document.segments?.find(
          (s) => s.from_stop_id === stop?.id && s.to_stop_id === nextStop?.id,
        )?.mode
      : undefined) ||
    stop?.mode ||
    "walking";
  const [weather, setWeather] = useState<{ key: string; value: Forecast }>();
  const [route, setRoute] = useState<{ key: string; value: VerifiedRoute }>();
  const [matrix, setMatrix] = useState<{
    key: string;
    value: Matrix;
    names: string[];
  }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = JSON.stringify([
    day,
    stop?.id,
    nextStop?.id,
    mode,
    stops,
    document.segments,
    places.map((p) => [
      p.id,
      p.name,
      p.coordinate,
      p.provider,
      p.providerPlaceId,
      p.countryCode,
    ]),
  ]);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const abroad =
    place?.provider === "google" ||
    (!!place?.countryCode && place.countryCode !== "CN");
  return (
    <details className="trip-evidence">
      <summary>核验交通与天气 · 按需联网</summary>
      <p>
        按次调用真实服务，可能产生配额费用。结果仅临时展示，不写入计划、离线包或
        AI 提示。
      </p>
      <label>
        当前站次
        <select value={stop?.id || ""} onChange={(e) => setId(e.target.value)}>
          {ordered.map((s) => (
            <option key={s.id} value={s.id}>
              {s.start} {places.find((p) => p.id === s.place_id)?.name}
            </option>
          ))}
        </select>
      </label>
      <div className="compact-actions">
        <button
          disabled={busy || !place || !next || !navigator.onLine}
          onClick={() =>
            void perform(async () =>
              setRoute({
                key,
                value: await routeForPlaces([place!, next!], mode, place!.city),
              }),
            )
          }
        >
          核验到下一站
        </button>
        <button
          disabled={busy || !place || !abroad || !navigator.onLine}
          onClick={() =>
            void perform(async () => {
              const [live] = await resolveGooglePlaces([place!]);
              const params = new URLSearchParams({
                day,
                longitude: String(live.coordinate.longitude),
                latitude: String(live.coordinate.latitude),
              });
              setWeather({
                key,
                value: await request<Forecast>(
                  `api/browser/v1/maps/google/weather?${params}`,
                  { cache: "no-store" },
                ),
              });
            })
          }
        >
          查询本站当日预报
        </button>
        <button
          disabled={
            busy ||
            !abroad ||
            ordered.length < 2 ||
            ordered.length > 10 ||
            !navigator.onLine
          }
          onClick={() =>
            void perform(async () => {
              const candidates = ordered
                .map((s) => places.find((p) => p.id === s.place_id))
                .filter((p): p is Place => !!p);
              if (candidates.length !== ordered.length)
                throw new Error("部分站次地点不可用，无法完整比较当天交通");
              if (
                candidates.some(
                  (p) =>
                    p.countryCode === "CN" ||
                    (!p.countryCode && p.provider !== "google"),
                )
              )
                throw new Error("混合区域需逐段核验");
              const live = await resolveGooglePlaces(candidates);
              setMatrix({
                key,
                names: candidates.map((p) => p.name),
                value: await request<Matrix>(
                  "api/browser/v1/maps/google/matrix",
                  {
                    method: "POST",
                    cache: "no-store",
                    body: JSON.stringify({
                      mode,
                      stops: live.map((p) => ({
                        longitude: p.coordinate.longitude,
                        latitude: p.coordinate.latitude,
                        coordinate_reference: "WGS84",
                      })),
                    }),
                  },
                ),
              });
            })
          }
        >
          比较当天交通（最多 10 站）
        </button>
      </div>
      {!abroad && <small>国内天气服务暂未接入；国内路线仍由高德提供。</small>}
      {error && (
        <p role="alert" className="lifecycle-alert">
          {error}
        </p>
      )}
      {route?.key === key && (
        <p>
          当前时刻参考：
          {route.value.distanceMeters == null
            ? "距离未知"
            : `${(route.value.distanceMeters / 1000).toFixed(1)} km`}{" "}
          ·{" "}
          {route.value.durationSeconds == null
            ? "时间未知"
            : `${Math.ceil(route.value.durationSeconds / 60)} 分钟`}
          。不是计划出发时刻的保证。
        </p>
      )}
      {weather?.key === key && (
        <p>
          Google Weather · {weather.value.date} {weather.value.timezone} ·{" "}
          {weather.value.description || "描述未知"} ·{" "}
          {weather.value.minimum?.degrees ?? "?"}–
          {weather.value.maximum?.degrees ?? "?"} °C
          <br />
          读取于 {new Date(weather.value.fetched_at).toLocaleString()} ·{" "}
          {weather.value.notice}
        </p>
      )}
      {matrix?.key === key && (
        <div className="matrix-results">
          <p>
            Google Routes · {matrix.value.elements} 个元素 ·
            当前参考，未验证整天可行
          </p>
          <table>
            <thead>
              <tr>
                <th>起点</th>
                <th>终点</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {matrix.value.cells
                .filter((c) => c.origin_index !== c.destination_index)
                .map((c) => (
                  <tr key={`${c.origin_index}-${c.destination_index}`}>
                    <td>{matrix.names[c.origin_index]}</td>
                    <td>{matrix.names[c.destination_index]}</td>
                    <td>
                      {c.status === "ready" && c.duration_seconds != null
                        ? `${Math.ceil(c.duration_seconds / 60)} 分钟`
                        : c.status === "unavailable"
                          ? "不可用"
                          : "未知"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}
