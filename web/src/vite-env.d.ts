/// <reference types="vite/client" />
/// <reference types="google.maps" />
/// <reference types="@amap/amap-jsapi-types" />

declare const __SHADOW_AMAP_CONFIG__: {
  key: string;
  securityJsCode: string;
} | null;

interface Window {
  _AMapSecurityConfig?: { securityJsCode: string };
}
