import { ReactNode, createContext, useContext, useMemo, useState } from "react";

import { initialMaps, initialPlaces, initialRoutes, initialVisits, members } from "../data/demo";
import { Place, Preference, TravelMap, TravelRoute, Visit } from "../types";

type NewMapInput = {
  title: string;
  city: string;
  subtitle: string;
};

export type NewPlaceInput = {
  name: string;
  address: string;
  city: string;
  district: string;
  category?: string;
  providerPlaceId?: string;
  longitude: number;
  latitude: number;
  note?: string;
};

type TravelState = {
  maps: TravelMap[];
  places: Place[];
  visits: Visit[];
  routes: TravelRoute[];
  members: typeof members;
  mapById: (id?: string) => TravelMap | undefined;
  placeById: (id?: string) => Place | undefined;
  placesForMap: (mapId: string) => Place[];
  setPreference: (placeId: string, preference: Preference) => void;
  markVisited: (placeId: string, mapId?: string) => void;
  addMap: (input: NewMapInput) => TravelMap;
  addPlace: (mapId: string, input: NewPlaceInput) => Place;
  reorderRouteStop: (routeId: string, index: number, direction: -1 | 1) => void;
};

const TravelContext = createContext<TravelState | null>(null);

export function TravelProvider({ children }: { children: ReactNode }) {
  const [maps, setMaps] = useState(initialMaps);
  const [places, setPlaces] = useState(initialPlaces);
  const [visits, setVisits] = useState(initialVisits);
  const [routes, setRoutes] = useState(initialRoutes);

  const value = useMemo<TravelState>(
    () => ({
      maps,
      places,
      visits,
      routes,
      members,
      mapById: (id) => maps.find((map) => map.id === id),
      placeById: (id) => places.find((place) => place.id === id),
      placesForMap: (mapId) => places.filter((place) => place.mapIds.includes(mapId)),
      setPreference: (placeId, preference) =>
        setPlaces((current) =>
          current.map((place) => (place.id === placeId ? { ...place, preference } : place))
        ),
      markVisited: (placeId, mapId) => {
        setPlaces((current) =>
          current.map((place) =>
            place.id === placeId && !place.visitedBy.includes("me")
              ? { ...place, visitedBy: [...place.visitedBy, "me"] }
              : place
          )
        );
        setVisits((current) => {
          if (current.some((visit) => visit.placeId === placeId && visit.date === "2026-08-15")) {
            return current;
          }
          return [
            {
              id: `visit-${placeId}-${Date.now()}`,
              placeId,
              date: "2026-08-15",
              displayDate: "今天",
              note: "刚刚标记为去过，可继续补充照片和感受。",
              photoCount: 0,
              mapId
            },
            ...current
          ];
        });
      },
      addMap: (input) => {
        const created: TravelMap = {
          id: `map-${Date.now()}`,
          title: input.title,
          subtitle: input.subtitle || "一张新的主题地图",
          city: input.city,
          accent: "#7c684a",
          accentSoft: "#ece3d5",
          emoji: "行",
          pointIds: [],
          members: members.slice(0, 1),
          completed: 0,
          updatedAt: "刚刚"
        };
        setMaps((current) => [created, ...current]);
        return created;
      },
      addPlace: (mapId, input) => {
        const id = `place-${Date.now()}`;
        const created: Place = {
          id,
          name: input.name,
          shortName: input.name.length > 8 ? `${input.name.slice(0, 7)}…` : input.name,
          address: input.address,
          district: input.district || input.city,
          city: input.city,
          category: input.category?.split(";")[0]?.split("|")[0] || "地点",
          tags: [],
          note: input.note || "同行备注尚未填写。",
          coordinate: {
            x: 25 + Math.abs(input.longitude * 17) % 55,
            y: 20 + Math.abs(input.latitude * 19) % 60,
            longitude: input.longitude,
            latitude: input.latitude
          },
          provider: "amap",
          providerPlaceId: input.providerPlaceId,
          mapIds: [mapId],
          visitedBy: [],
          preference: "none",
          photos: []
        };
        setPlaces((current) => [...current, created]);
        setMaps((current) => current.map((map) => map.id === mapId ? { ...map, pointIds: [...map.pointIds, id], updatedAt: "刚刚" } : map));
        return created;
      },
      reorderRouteStop: (routeId, index, direction) =>
        setRoutes((current) =>
          current.map((route) => {
            if (route.id !== routeId) return route;
            const target = index + direction;
            if (target < 0 || target >= route.stopIds.length) return route;
            const stopIds = [...route.stopIds];
            [stopIds[index], stopIds[target]] = [stopIds[target], stopIds[index]];
            return { ...route, stopIds };
          })
        )
    }),
    [maps, places, routes, visits]
  );

  return <TravelContext.Provider value={value}>{children}</TravelContext.Provider>;
}

export function useTravel(): TravelState {
  const value = useContext(TravelContext);
  if (!value) throw new Error("useTravel must be used inside TravelProvider");
  return value;
}
