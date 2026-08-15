export type Preference = "none" | "want" | "planned" | "skip";
export type VisitState = "visited" | "unvisited";

export type Member = {
  id: string;
  name: string;
  initials: string;
  color: string;
};

export type TravelMap = {
  id: string;
  title: string;
  subtitle: string;
  city: string;
  accent: string;
  accentSoft: string;
  emoji: string;
  pointIds: string[];
  members: Member[];
  completed: number;
  period?: string;
  routeEnabled?: boolean;
  updatedAt: string;
  archived?: boolean;
};

export type Place = {
  id: string;
  name: string;
  shortName: string;
  address: string;
  district: string;
  city: string;
  category: string;
  tags: string[];
  note: string;
  coordinate: { x: number; y: number; longitude: number; latitude: number };
  provider: "amap" | "manual";
  providerPlaceId?: string;
  mapIds: string[];
  visitedBy: string[];
  preference: Preference;
  rating?: number;
  recommended?: string;
  price?: string;
  photos: string[];
};

export type Visit = {
  id: string;
  placeId: string;
  date: string;
  displayDate: string;
  note: string;
  rating?: number;
  photoCount: number;
  mapId?: string;
};

export type TravelRoute = {
  id: string;
  mapId: string;
  title: string;
  mode: "walking" | "driving" | "transit" | "bicycling";
  stopIds: string[];
  distance: string;
  duration: string;
  note: string;
};
