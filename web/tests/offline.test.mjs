import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import "fake-indexeddb/auto";
import {
  configureOffline,
  localEntries,
  localWrite,
  pendingVisits,
  queueVisit,
  replayPendingVisits,
} from "../src/offline.ts";
import { localDate, placeInMap } from "../src/domain.ts";

Object.defineProperty(globalThis, "location", {
  value: { origin: "https://example.test" },
  configurable: true,
});
Object.defineProperty(globalThis, "navigator", {
  value: { onLine: true },
  configurable: true,
});
let uid;
beforeEach(() => {
  uid = crypto.randomUUID();
  configureOffline(uid, "/travel/");
});
const payload = (id) => ({
  client_record_id: id,
  visited_on: "2026-10-01",
  note: "私密草稿",
});
const session = () => ({
  ok: true,
  json: async () => ({ shadow_user_id: uid }),
});

test("failure on first item preserves all three entries", async () => {
  for (const id of ["first", "second", "third"])
    await queueVisit("place", payload(id));
  globalThis.fetch = async (url) => {
    if (url.endsWith("/me")) return session();
    throw new TypeError("offline");
  };
  await assert.rejects(replayPendingVisits("/travel/"));
  assert.equal((await pendingVisits()).length, 3);
});
test("conflicts are retained while following entries replay", async () => {
  for (const id of ["one", "two", "three"])
    await queueVisit("place", payload(id));
  let count = 0;
  globalThis.fetch = async (url) =>
    url.endsWith("/me")
      ? session()
      : ++count === 1
        ? {
            status: 409,
            ok: false,
            json: async () => ({
              detail: { code: "existing_visit", current: { id: "server" } },
            }),
          }
        : { ok: true, status: 201, json: async () => ({ id: "ok" }) };
  await replayPendingVisits("/travel/");
  const visits = await pendingVisits();
  assert.equal(visits.length, 1);
  assert.equal(visits[0].syncState, "conflict");
});
test("queue is isolated by account and application path", async () => {
  await queueVisit("place", payload("private"));
  configureOffline("another", "/travel/");
  assert.equal((await pendingVisits()).length, 0);
  configureOffline(uid, "/other/");
  assert.equal((await pendingVisits()).length, 0);
  configureOffline(uid, "/travel/");
  assert.equal((await pendingVisits()).length, 1);
});
test("account switch during asynchronous queue creation cannot move a private draft", async () => {
  const original = uid;
  const saving = queueVisit("place", payload("switch-during-save"));
  configureOffline("new-owner", "/travel/");
  await assert.rejects(saving, /账号变化/);
  assert.equal((await pendingVisits()).length, 0);
  configureOffline(original, "/travel/");
  assert.equal((await pendingVisits()).length, 0);
});
test("401 and changed server account never delete entries or upload", async () => {
  await queueVisit("place", payload("private"));
  let uploads = 0;
  globalThis.fetch = async (url) => {
    if (!url.endsWith("/me")) uploads++;
    return { ok: false, status: 401 };
  };
  await assert.rejects(replayPendingVisits("/travel/"));
  assert.equal(uploads, 0);
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({ shadow_user_id: "different" }),
  });
  await assert.rejects(replayPendingVisits("/travel/"));
  assert.equal((await pendingVisits()).length, 1);
});
test("a newly queued item during replay is not overwritten by old snapshot", async () => {
  await queueVisit("place", payload("first"));
  globalThis.fetch = async (url) => {
    if (url.endsWith("/me")) return session();
    await queueVisit("place", payload("new"));
    return { ok: true, json: async () => ({ id: "ok" }) };
  };
  await replayPendingVisits("/travel/");
  assert.deepEqual(
    (await pendingVisits()).map((v) => v.clientRecordId),
    ["new"],
  );
});
test("concurrent replay calls share one local execution", async () => {
  await queueVisit("place", payload("first"));
  let writes = 0;
  globalThis.fetch = async (url) => {
    if (url.endsWith("/me")) return session();
    writes++;
    return { ok: true, json: async () => ({ id: "ok" }) };
  };
  await Promise.all([
    replayPendingVisits("/travel/"),
    replayPendingVisits("/travel/"),
  ]);
  assert.equal(writes, 1);
});
test("more than 500 operations are retained without truncation", async () => {
  await Promise.all(
    Array.from({ length: 505 }, (_, i) =>
      localWrite("outbox", String(i), {
        placeId: "p",
        input: payload(String(i)),
        state: "pending",
        queuedAt: "2026-10-01",
      }),
    ),
  );
  assert.equal((await localEntries("outbox")).length, 505);
});
test("same ID with a different payload does not overwrite", async () => {
  await queueVisit("place", payload("same"));
  await assert.rejects(
    queueVisit("place", { ...payload("same"), note: "changed" }),
  );
  assert.equal((await pendingVisits())[0].note, "私密草稿");
});
test("local calendar dates and theme projections are explicit", () => {
  const instant = new Date("2026-09-30T18:00:00Z");
  assert.equal(localDate("Asia/Shanghai", instant), "2026-10-01");
  assert.equal(localDate("America/Los_Angeles", instant), "2026-09-30");
  const place = {
    name: "事实",
    mapPoints: [
      {
        mapId: "a",
        note: "A 攻略",
        category: "餐厅",
        tags: [],
        preference: "want",
        customValues: {},
      },
      {
        mapId: "b",
        note: "B 攻略",
        category: "聚会",
        tags: [],
        preference: "skip",
        customValues: {},
      },
    ],
  };
  assert.equal(placeInMap(place, "a").note, "A 攻略");
  assert.equal(placeInMap(place, "b").preference, "skip");
  assert.equal(placeInMap(place).note, "");
});
