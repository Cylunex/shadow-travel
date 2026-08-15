import { Check, ChevronRight, MapPin } from "lucide-react";

import { Place } from "../types";

export function PlaceListItem({
  place,
  active,
  onClick,
  index
}: {
  place: Place;
  active?: boolean;
  onClick: () => void;
  index?: number;
}) {
  const visited = place.visitedBy.includes("me");
  return (
    <button
      type="button"
      className={`place-row${active ? " active" : ""}`}
      onClick={onClick}
    >
      <span className={`place-status${visited ? " visited" : ""}`}>
        {index !== undefined ? index + 1 : visited ? <Check size={15} /> : <MapPin size={15} />}
      </span>
      <span className="place-row-main">
        <span className="place-row-heading">
          <strong>{place.name}</strong>
          {place.preference === "planned" && <small>计划去</small>}
          {place.preference === "want" && <small>想去</small>}
        </span>
        <span>{place.district} · {place.category} · {place.tags.slice(0, 2).join(" / ")}</span>
      </span>
      <ChevronRight className="row-chevron" size={18} />
    </button>
  );
}
