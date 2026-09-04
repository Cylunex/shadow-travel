import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { loadEnv } from "vite";

function basePath(mode: string): string {
  const value = process.env.VITE_BASE_PATH?.trim() || (mode === "production" ? "travel" : "/");
  const normalized = value.replace(/^\/+|\/+$/g, "");
  if (normalized && !/^[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*$/.test(normalized)) {
    throw new Error("VITE_BASE_PATH must be a URL path such as travel, not a filesystem path");
  }
  return normalized ? `/${normalized}/` : "/";
}

type AMapBuildConfig = { key: string; securityJsCode: string } | null;

function amapConfig(propertiesFile: string | undefined): AMapBuildConfig {
  if (!propertiesFile?.trim()) return null;
  let content: string;
  try {
    content = readFileSync(resolve(propertiesFile), "utf8");
  } catch {
    throw new Error("AMAP_PROPERTIES_FILE cannot be read");
  }
  const properties = new Map<string, string>();
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || line.startsWith("!")) continue;
    const separator = line.search(/[:=]/);
    if (separator < 1) continue;
    properties.set(line.slice(0, separator).trim().toLowerCase(), line.slice(separator + 1).trim());
  }
  const key = properties.get("key") ?? "";
  const securityJsCode = properties.get("jscode") ?? properties.get("securityjscode") ?? "";
  if (!key || !securityJsCode) throw new Error("AMap properties must contain key and jscode");
  return { key, securityJsCode };
}

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "");
  return {
    base: basePath(mode),
    define: {
      __SHADOW_AMAP_CONFIG__: JSON.stringify(amapConfig(environment.AMAP_PROPERTIES_FILE))
    },
    plugins: [react(), {
      name: "travel-offline-manifest",
      generateBundle(_options, bundle) {
        const assets = Object.keys(bundle).filter(name => !name.endsWith(".map") && name !== "index.html");
        const precache = ["./", "./manifest.webmanifest", ...assets.map(name => `./${name}`)];
        const build = createHash("sha256").update(JSON.stringify(precache))
          .update(readFileSync(resolve("index.html")))
          .update(readFileSync(resolve("public/sw.js")))
          .update(readFileSync(resolve("public/manifest.webmanifest")))
          .digest("hex").slice(0, 16);
        this.emitFile({ type: "asset", fileName: "sw.js", source: `self.__TRAVEL_PRECACHE__=${JSON.stringify(precache)};self.__TRAVEL_BUILD__=${JSON.stringify(build)};\n${readFileSync(resolve("public/sw.js"), "utf8")}` });
      }
    }],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/auth": "http://127.0.0.1:8000",
        "/healthz": "http://127.0.0.1:8000",
        "/readyz": "http://127.0.0.1:8000"
      }
    }
  };
});
