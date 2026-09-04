import type { Place } from "./types";
export function localDate(timeZone?: string, value = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  return ["year", "month", "day"]
    .map((type) => parts.find((part) => part.type === type)!.value)
    .join("-");
}
export function placeInMap(place: Place, mapId?: string): Place {
  const point = place.mapPoints?.find((item) => item.mapId === mapId);
  if (!point)
    return place.mapPoints
      ? {
          ...place,
          category: "地点",
          tags: [],
          note: "",
          preference: "none",
          recommended: undefined,
          price: undefined,
        }
      : place;
  return {
    ...place,
    name: point.displayName || place.name,
    category: point.category,
    tags: point.tags,
    note: point.note,
    preference: point.preference,
    recommended: String(point.customValues.recommended ?? ""),
    price: String(point.customValues.price ?? ""),
  };
}
