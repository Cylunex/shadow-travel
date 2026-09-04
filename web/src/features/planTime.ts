import type { PlanDocument, Stop } from "./lifecycle";

const cache = new Map<string, number | null>();
/** Resolve a wall clock by round-tripping candidate UTC offsets, including DST folds. */
export function stopInstant(stop: Stop, timezone = "UTC"): number | null {
  const zone = stop.timezone || timezone;
  const key = `${stop.day}T${stop.start}|${zone}|${stop.fold ?? ""}`;
  if (cache.has(key)) return cache.get(key)!;
  let result: number | null = null;
  try {
    const wall = Date.parse(`${stop.day}T${stop.start}:00Z`);
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const wallAt = (at: number) => {
      const p = Object.fromEntries(
        formatter.formatToParts(at).map((p) => [p.type, p.value]),
      );
      return Date.parse(
        `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}Z`,
      );
    };
    const offsets = new Set(
      [-36, -12, 0, 12, 36].map((h) => {
        const at = wall + h * 3600000;
        return wallAt(at) - at;
      }),
    );
    const options = [...offsets]
      .map((offset) => wall - offset)
      .filter((at) => wallAt(at) === wall)
      .sort((a, b) => a - b);
    if (options.length === 1) result = options[0];
    else if (options.length > 1 && stop.fold != null)
      result = options[stop.fold];
  } catch {
    /* Incomplete/invalid drafts remain editable; backend validation blocks approval. */
  }
  if (cache.size > 2000) cache.clear();
  cache.set(key, result);
  return result;
}

export function orderedStops(stops: Stop[], timezone = "UTC"): Stop[] {
  return [...stops].sort((a, b) => {
    const x = stopInstant(a, timezone),
      y = stopInstant(b, timezone);
    // Unresolved drafts sort after resolved instants; never invent a DST offset.
    if (x != null && y != null) return x - y || a.id.localeCompare(b.id);
    if (x != null) return -1;
    if (y != null) return 1;
    return (
      (a.day + a.start).localeCompare(b.day + b.start) ||
      a.id.localeCompare(b.id)
    );
  });
}

export function pruneSegments(document: PlanDocument): PlanDocument {
  const stops = orderedStops(document.stops, document.timezone || "UTC");
  const next = new Map(
    stops.slice(0, -1).map((s, i) => [s.id, stops[i + 1].id]),
  );
  // While editing an incomplete timezone keep estimates until chronology can be resolved.
  const validTimes = stops.every(
    (s) => stopInstant(s, document.timezone || "UTC") != null,
  );
  const ids = new Set(stops.map((s) => s.id));
  return {
    ...document,
    segments: (document.segments || []).filter(
      (s) =>
        ids.has(s.from_stop_id) &&
        ids.has(s.to_stop_id) &&
        (!validTimes || next.get(s.from_stop_id) === s.to_stop_id),
    ),
  };
}
