import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

test("SW only deletes its own scoped caches and never captures sibling apps or APIs", async () => {
  const handlers = {};
  const deleted = [];
  const pending = [];
  const prefix = "shadow-travel-shell:https://example.test/travel/:";
  const self = {
    registration: { scope: "https://example.test/travel/" },
    location: { origin: "https://example.test" },
    clients: { claim() {} },
    addEventListener(name, handler) {
      handlers[name] = handler;
    },
  };
  const caches = {
    keys: async () => [
      prefix + "old",
      prefix + "dev",
      "shadow-garden-shell",
      "shadow-travel-shell:https://example.test/another/:old",
    ],
    delete: async (key) => {
      deleted.push(key);
    },
  };
  runInNewContext(
    readFileSync(new URL("../public/sw.js", import.meta.url), "utf8"),
    { self, caches, URL, Response },
  );
  handlers.activate({
    waitUntil(p) {
      pending.push(p);
    },
  });
  await Promise.all(pending);
  assert.deepEqual(deleted, [prefix + "old"]);
  for (const url of [
    "https://example.test/garden/",
    "https://example.test/travel/api/browser/v1/me",
    "https://example.test/travel/auth/login",
    "https://example.test/travel/private.pdf",
  ]) {
    let intercepted = false;
    handlers.fetch({
      request: { url, method: "GET", mode: "cors" },
      respondWith() {
        intercepted = true;
      },
    });
    assert.equal(intercepted, false, url);
  }
});
