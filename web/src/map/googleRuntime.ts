import { request } from "../api";
import { isLocated, type Place, type LocatedPlace } from "../types";

export type GooglePlace = {
  provider_place_id: string;
  name: string;
  address: string;
  country_code?: string;
  city?: string;
  district?: string;
  category?: string;
  longitude: number;
  latitude: number;
  attributions: { provider: string; provider_uri: string }[];
};
let loading: Promise<typeof google> | undefined;
export const isGoogleConfigured = () =>
  !!(
    import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY &&
    import.meta.env.VITE_GOOGLE_MAP_ID
  );
export function loadGoogle(): Promise<typeof google> {
  if (!isGoogleConfigured())
    return Promise.reject(
      new Error(
        "Google 浏览器地图密钥未配置或缺少 Map ID；地点列表和外部导航仍可使用",
      ),
    );
  if (!loading)
    loading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const params = new URLSearchParams({
        key: import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY,
        v: "quarterly",
        loading: "async",
        callback: "__shadowGoogleReady",
        libraries: "marker",
      });
      const target = window as Window & {
        __shadowGoogleReady?: () => void;
        gm_authFailure?: () => void;
      };
      const timeout = window.setTimeout(
        () => fail("Google 地图加载超时，请检查网络"),
        15000,
      );
      const fail = (message: string) => {
        clearTimeout(timeout);
        loading = undefined;
        script.remove();
        reject(new Error(message));
      };
      target.__shadowGoogleReady = () => {
        clearTimeout(timeout);
        delete target.__shadowGoogleReady;
        resolve(google);
      };
      target.gm_authFailure = () => {
        fail("Google 地图授权失败，请检查域名限制与计费配置");
        window.dispatchEvent(new Event("google-map-auth-failure"));
      };
      script.src = "https://maps.googleapis.com/maps/api/js?" + params;
      script.async = true;
      script.onerror = () => fail("Google 地图加载失败，请检查网络");
      document.head.append(script);
    });
  return loading;
}
export function googleDetails(id: string) {
  return request<GooglePlace>(
    `api/browser/v1/maps/google/places/${encodeURIComponent(id)}`,
    { cache: "no-store" },
  );
}
export type LiveGooglePlace = LocatedPlace & {
  attributions?: GooglePlace["attributions"];
};
export async function resolveGooglePlaces(
  places: Place[],
): Promise<LiveGooglePlace[]> {
  if (places.length > 20)
    throw new Error("单次最多核验 20 个地点，请缩小筛选范围");
  const result: LiveGooglePlace[] = [];
  // Bounded batches; content exists only in component memory, never IndexedDB/exports.
  for (let i = 0; i < places.length; i += 4) {
    result.push(
      ...(await Promise.all(
        places.slice(i, i + 4).map(async (p) => {
          if (p.provider === "google" && p.providerPlaceId) {
            const live = await googleDetails(p.providerPlaceId);
            return {
              ...p,
              attributions: live.attributions,
              coordinate: {
                x: 0,
                y: 0,
                longitude: live.longitude,
                latitude: live.latitude,
                reference: "WGS84" as const,
              },
            };
          }
          if (!isLocated(p) || p.coordinate.reference !== "WGS84")
            throw new Error("Google 地图只接收已核验的 WGS-84 坐标");
          return p;
        }),
      )),
    );
  }
  return result;
}
