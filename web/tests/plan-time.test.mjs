import { test } from "node:test";
import assert from "node:assert/strict";
import {
  stopInstant,
  orderedStops,
  pruneSegments,
} from "../src/features/planTime.ts";

const stop = (id, start, timezone, extra = {}) => ({
  id,
  place_id: "p",
  day: "2026-10-01",
  start,
  timezone,
  duration_minutes: 60,
  travel_minutes: null,
  mode: "walking",
  anchor: false,
  note: "",
  ...extra,
});
test("cross-zone stops and segments follow instants rather than wall clocks", () => {
  const stops = [
    stop("la", "09:00", "America/Los_Angeles"),
    stop("tokyo", "20:00", "Asia/Tokyo"),
  ];
  assert.deepEqual(
    orderedStops(stops).map((s) => s.id),
    ["tokyo", "la"],
  );
  const doc = {
    stops,
    timezone: "UTC",
    segments: [
      { id: "right", from_stop_id: "tokyo", to_stop_id: "la" },
      { id: "wrong", from_stop_id: "la", to_stop_id: "tokyo" },
    ],
  };
  assert.deepEqual(
    pruneSegments(doc).segments.map((s) => s.id),
    ["right"],
  );
});
test("DST missing/repeated times are not silently assigned an offset", () => {
  const repeated = stop("fall", "01:30", "America/New_York", {
    day: "2026-11-01",
  });
  assert.equal(stopInstant(repeated), null);
  assert.equal(
    stopInstant({ ...repeated, fold: 0 }),
    Date.parse("2026-11-01T05:30:00Z"),
  );
  assert.equal(
    stopInstant({ ...repeated, fold: 1 }),
    Date.parse("2026-11-01T06:30:00Z"),
  );
  assert.equal(
    stopInstant(
      stop("gap", "02:30", "America/New_York", { day: "2026-03-08" }),
    ),
    null,
  );
  assert.equal(stopInstant(stop("invalid", "12:00", "Asia/")), null);
  assert.equal(
    stopInstant(stop("kathmandu", "12:00", "Asia/Kathmandu")),
    Date.parse("2026-10-01T06:15:00Z"),
  );
});
test("an incomplete timezone does not erase a user's segment estimates", () => {
  const segments = [{ from_stop_id: "a", to_stop_id: "b", manual_minutes: 45 }];
  assert.deepEqual(
    pruneSegments({
      stops: [stop("a", "09:00", "Asia/"), stop("b", "12:00", "UTC")],
      segments,
    }).segments,
    segments,
  );
});
