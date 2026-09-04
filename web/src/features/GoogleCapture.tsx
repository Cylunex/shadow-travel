import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "./lifecycle";
import type { GooglePlace } from "../map/googleRuntime";
import type { Place } from "../types";
import { useTravel } from "../state/TravelContext";
import { MapSurface } from "../components/MapSurface";
import { mapProviderForCountry } from "../map/provider";

export function GoogleCapture() {
  const { refresh } = useTravel();
  const [country, setCountry] = useState("JP");
  const [query, setQuery] = useState("");
  const [city, setCity] = useState("");
  const [rows, setRows] = useState<GooglePlace[]>([]);
  const [choice, setChoice] = useState<GooglePlace>();
  const [alias, setAlias] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Place>();
  const [showMap, setShowMap] = useState(false);
  async function search(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setRows([]);
    setChoice(undefined);
    setSaved(undefined);
    try {
      const params = new URLSearchParams({
        query,
        region: [city, country].join(" "),
        country_code: country,
        limit: "10",
      });
      setRows(
        (await api<{ places: GooglePlace[] }>(`maps/places?${params}`)).places,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="lifecycle-card google-capture">
      <summary>海外地点 · Google Maps 搜索与收藏</summary>
      <p>
        保存自己的别名与 Google
        地点引用；地址、分类、坐标实时展示，不保存到离线包。
      </p>
      <form onSubmit={search} className="form-grid">
        <label>
          国家 / 地区代码
          <input
            required
            pattern="[A-Z]{2}"
            maxLength={2}
            value={country}
            onChange={(e) => {
              setCountry(e.target.value.toUpperCase());
              setRows([]);
              setChoice(undefined);
            }}
            placeholder="JP / US / FR"
          />
        </label>
        <label>
          城市（自己填写）
          <input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="例如 Tokyo"
            maxLength={120}
          />
        </label>
        <label>
          查找地点
          <input
            required
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={120}
          />
        </label>
        <button
          className="primary-button"
          disabled={busy || country === "CN" || !navigator.onLine}
        >
          搜索 Google Maps
        </button>
      </form>
      {error && (
        <p role="alert">{error} · 请检查 Google 服务凭据、网络与计费配置。</p>
      )}
      <div className="capture-list">
        {rows.map((p) => (
          <button
            className="lifecycle-card"
            key={p.provider_place_id}
            onClick={() => {
              setChoice(p);
              setAlias("");
            }}
          >
            <strong>{p.name}</strong>
            <small>
              {p.address} · {p.category} · {p.district}
            </small>
          </button>
        ))}
      </div>
      {rows.length > 0 && (
        <p className="lifecycle-hint">
          Google Maps · 实时搜索结果
          {rows
            .flatMap((p) => p.attributions || [])
            .map((a, i) => (
              <span key={i}> · {a.provider}</span>
            ))}
        </p>
      )}
      {choice && (
        <form
          className="form-grid"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              const place = await api<Place>("maps/google/references", "POST", {
                provider_place_id: choice.provider_place_id,
                alias,
                city,
                country_code: country,
              });
              setSaved(place);
              setChoice(undefined);
              await refresh();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            确认收藏：{choice.name}
            。请为它起一个自己的名称；不会自动复制搜索结果。
          </p>
          <label>
            我的地点别名
            <input
              required
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              maxLength={120}
              placeholder="例如：周六晚餐 / 东京第一站"
            />
          </label>
          <button className="primary-button" disabled={busy}>
            确认保存引用
          </button>
        </form>
      )}
      <button
        className="secondary-button"
        disabled={country === "CN"}
        onClick={() => setShowMap((value) => !value)}
      >
        {showMap ? "收起 Google 选点地图" : "在 Google 地图选点"}
      </button>
      {showMap && (
        <div style={{ height: 350, marginTop: 12 }}>
          <MapSurface
            places={[]}
            city={city || "海外选点"}
            provider={mapProviderForCountry(country)}
            onGoogleMapClick={async (point) => {
              if (busy) return;
              setBusy(true);
              setError("");
              setChoice(undefined);
              try {
                const params = new URLSearchParams({
                  country_code: country,
                  longitude: String(point.longitude),
                  latitude: String(point.latitude),
                });
                const result = await api<{ place: GooglePlace | null }>(
                  `maps/reverse-geocode?${params}`,
                );
                if (!result.place?.provider_place_id)
                  throw new Error("此位置没有可确认的地点引用，请改用搜索");
                setChoice(result.place);
                setAlias("");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          />
        </div>
      )}
      {saved && (
        <p role="status">
          已收藏 <Link to={`/places/${saved.id}`}>{saved.name}</Link>
          ，可从主题或旅程的现有地点中添加。
        </p>
      )}
    </details>
  );
}
