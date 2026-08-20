import { CalendarClock, Check, ChevronRight, Heart, MapPin, Route } from "lucide-react";

import { Place } from "../types";

export function PlaceListItem({
  place,
  active,
  onClick,
  index,
  routeIndex
}: {
  place: Place;
  active?: boolean;
  onClick: () => void;
  index?: number;
  routeIndex?: number;
}) {
  const visited = place.visitedBy.includes("me");
  const preference = place.preference === "planned" ? "计划去" : place.preference === "want" ? "想去" : place.preference === "skip" ? "暂不考虑" : "未标记";
  return (
    <button
      type="button"
      className={`place-row${active ? " active" : ""}`}
      onClick={onClick}
    >
      <span className={`place-status preference-${place.preference}${visited ? " visited" : ""}`}>
        {index !== undefined ? index + 1 : visited ? <Check size={14} /> : <MapPin size={14} />}
      </span>
      <span className="place-row-main">
        <span className="place-row-heading">
          <strong>{place.name}</strong>
          {visited && <small className="visited-label"><Check size={11} /> 已去</small>}
        </span>
        <span className="place-row-location">{place.district || place.city} · {place.category}</span>
        <span className="place-row-meta">
          <small className={`preference-label preference-${place.preference}`}>
            {place.preference === "want" ? <Heart size={11} /> : place.preference === "planned" ? <CalendarClock size={11} /> : null}{preference}
          </small>
          {place.price && <small>{place.price}</small>}
          {routeIndex !== undefined && <small><Route size={11} /> 路线 {routeIndex + 1}</small>}
        </span>
      </span>
      <ChevronRight className="row-chevron" size={18} />
    </button>
  );
}
