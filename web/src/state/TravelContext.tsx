import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  createTravelMap,
  createTravelPlace,
  createVisit,
  basePath,
  loadCapabilities,
  loadWorkspace,
  loadPendingVisits,
  updatePlacePreference,
  updateTravelPlace,
  updateTravelRoute
} from "../api";
import { configureOffline, localEntries, replayPendingVisits } from "../offline";
import { replayRuntimeCommands } from "../features/runtimeOffline";
import { localDate, placeInMap } from "../domain";
import type { TravelWorkspace } from "../api";
import type { PlanState } from "../features/lifecycle";
import { TravelCapabilities } from "../api";
import { initialMaps, initialPlaces, initialRoutes, initialVisits, members as demoMembers } from "../data/demo";
import { Member, Place, Preference, TravelMap, TravelRoute, Trip, Visit } from "../types";

type NewMapInput = { title: string; city: string; subtitle: string; routeEnabled?: boolean };

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
  trips: Trip[];
  maps: TravelMap[];
  places: Place[];
  visits: Visit[];
  routes: TravelRoute[];
  members: Member[];
  capabilities: TravelCapabilities;
  mapById: (id?: string) => TravelMap | undefined;
  placeById: (id?: string) => Place | undefined;
  placesForMap: (mapId: string) => Place[];
  setPreference: (placeId: string, preference: Preference, mapId?: string) => Promise<void>;
  markVisited: (placeId: string, mapId?: string) => Promise<void>;
  addMap: (input: NewMapInput) => Promise<TravelMap>;
  addPlace: (mapId: string, input: NewPlaceInput) => Promise<Place>;
  updatePlace: (placeId: string, input: { note?: string; mapId?: string; expectedVersion?: number }) => Promise<void>;
  recordVisit: (placeId: string, input: { mapId?: string; tripId?: string; visitedOn?: string; note?: string; rating?: number; clientRecordId?: string }) => Promise<Visit | void>;
  reorderRouteStop: (routeId: string, index: number, direction: -1 | 1) => Promise<void>;
  setRouteOrder: (routeId: string, stopIds: string[]) => Promise<void>;
  setRouteMode: (routeId: string, mode: TravelRoute["mode"]) => Promise<void>;
  refresh: () => Promise<void>;
};

const TravelContext = createContext<TravelState | null>(null);
const unavailableCapabilities: TravelCapabilities = {
  media: false,
  llm: false,
  international_maps: false,
  location_history: false,
  location_history_mode: "disabled",
  continuous_tracking_default: false
};

export function TravelProvider({ children, userId, demo = false }: { children: ReactNode; userId: string; demo?: boolean }) {
  const developmentDemo = demo;
  configureOffline(userId, basePath);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [maps, setMaps] = useState<TravelMap[]>(developmentDemo ? initialMaps : []);
  const [places, setPlaces] = useState<Place[]>(developmentDemo ? initialPlaces : []);
  const [visits, setVisits] = useState<Visit[]>(developmentDemo ? initialVisits : []);
  const [routes, setRoutes] = useState<TravelRoute[]>(developmentDemo ? initialRoutes : []);
  const [members, setMembers] = useState<Member[]>(developmentDemo ? demoMembers : []);
  const [capabilities, setCapabilities] = useState<TravelCapabilities>(unavailableCapabilities);
  const [loading, setLoading] = useState(!developmentDemo);
  const [error, setError] = useState<string>();

  const refresh = useCallback(async () => {
    if (developmentDemo) return;
    const workspace = await loadWorkspace().catch(async (reason) => {
      if (navigator.onLine && !(reason instanceof TypeError)) throw reason;
      const packs = (await localEntries<PlanState>("pack")).map(row => row.value).filter(pack => pack.offline && new Date(pack.offline.expires_at) > new Date());
      if (!packs.length) throw reason;
      return { trips: packs.map(p => p.trip), maps: [], places: [...new Map(packs.flatMap(p => p.places).map(p => [p.id, p])).values()], visits: packs.flatMap(p => p.visits || []), routes: [], members: [] } as TravelWorkspace;
    });
    setTrips(workspace.trips ?? []);
    setMaps(workspace.maps);
    setPlaces(workspace.places);
    setVisits([...await loadPendingVisits(), ...workspace.visits]);
    setRoutes(workspace.routes);
    setMembers(workspace.members);
  }, [developmentDemo, userId]);

  useEffect(() => {
    if (developmentDemo) return;
    let active = true;
    Promise.all([
      refresh(),
      loadCapabilities().catch(() => unavailableCapabilities)
    ]).then(([, loadedCapabilities]) => {
      if (!active) return;
      setCapabilities(loadedCapabilities);
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : "旅行数据加载失败");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [refresh]);

  useEffect(() => {
    if (developmentDemo) return;
    const replay = () => { void Promise.all([replayPendingVisits(basePath), replayRuntimeCommands()]).then(refresh).catch(() => { /* Outboxes remain visible and recoverable in Settings. */ }); };
    window.addEventListener("online", replay);
    if (navigator.onLine) replay();
    return () => window.removeEventListener("online", replay);
  }, [refresh]);

  const value = useMemo<TravelState>(() => ({
    trips,
    maps,
    places: places.map(place => visits.some(visit => visit.placeId === place.id && visit.syncState !== "pending" && visit.syncState !== "conflict") ? { ...place, visitedBy: [...new Set([...place.visitedBy, "me"])] } : place),
    visits,
    routes,
    members,
    capabilities,
    mapById: (id) => maps.find((map) => map.id === id),
    placeById: (id) => places.find((place) => place.id === id),
    placesForMap: (mapId) => places.filter((place) => place.mapIds.includes(mapId)).map(place => placeInMap(place, mapId)),
    setPreference: async (placeId, preference, mapId) => {
      if (!mapId) throw new Error("请先选择要修改意愿的主题");
      if (!developmentDemo) { await updatePlacePreference(placeId, preference, mapId); await refresh(); }
      else setPlaces((current) => current.map((place) => place.id === placeId ? { ...place, preference } : place));
    },
    markVisited: async (placeId, mapId) => {
      if (developmentDemo) {
        const visit: Visit = {
          id: `visit-${placeId}-${Date.now()}`,
          placeId,
          date: localDate(),
          displayDate: "今天",
          note: "",
          photoCount: 0,
          mapId
        };
        setVisits((current) => [visit, ...current]);
        setPlaces((current) => current.map((place) => place.id === placeId ? { ...place, visitedBy: ["me"] } : place));
        return;
      }
      const created = await createVisit(placeId, { mapId });
      if (created.syncState === "pending") setVisits((current) => [created, ...current]);
      else await refresh();
    },
    addMap: async (input) => {
      if (!developmentDemo) {
        const created = await createTravelMap(input);
        setMaps((current) => [created, ...current]);
        setMembers((current) => current.length ? current : created.members);
        return created;
      }
      const created: TravelMap = {
        id: `map-${Date.now()}`,
        title: input.title,
        subtitle: input.subtitle || "一张新的主题地图",
        city: input.city,
        accent: "#159de5",
        accentSoft: "#dff3fd",
        emoji: "行",
        routeEnabled: input.routeEnabled ?? false,
        pointIds: [],
        members: demoMembers.slice(0, 1),
        completed: 0,
        updatedAt: "刚刚"
      };
      setMaps((current) => [created, ...current]);
      return created;
    },
    addPlace: async (mapId, input) => {
      if (!developmentDemo) {
        const created = await createTravelPlace(mapId, input);
        await refresh();
        return created;
      }
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
        note: input.note || "",
        coordinate: { x: 50, y: 50, longitude: input.longitude, latitude: input.latitude },
        provider: input.providerPlaceId ? "amap" : "manual",
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
    updatePlace: async (placeId, input) => {
      if (!developmentDemo) { await updateTravelPlace(placeId, input); await refresh(); }
      else setPlaces((current) => current.map((place) => place.id === placeId ? { ...place, ...input } : place));
    },
    recordVisit: async (placeId, input) => {
      if (developmentDemo) {
        const visit: Visit = {
          id: `visit-${placeId}-${Date.now()}`,
          placeId,
          date: input.visitedOn || localDate(),
          displayDate: input.visitedOn || "今天",
          note: input.note || "",
          rating: input.rating,
          photoCount: 0,
          mapId: input.mapId
        };
        setVisits((current) => [visit, ...current]);
        setPlaces((current) => current.map((place) => place.id === placeId ? { ...place, visitedBy: ["me"] } : place));
        return;
      }
      const created = await createVisit(placeId, input);
      setVisits((current) => [created, ...current.filter(item => item.id !== created.id)]);
      if (created.syncState !== "pending") await refresh().catch(() => undefined);
      return created;
    },
    reorderRouteStop: async (routeId, index, direction) => {
      const route = routes.find((item) => item.id === routeId);
      if (!route) return;
      const target = index + direction;
      if (target < 0 || target >= route.stopIds.length) return;
      const stopIds = [...route.stopIds];
      [stopIds[index], stopIds[target]] = [stopIds[target], stopIds[index]];
      if (!developmentDemo) await updateTravelRoute(routeId, { stopIds });
      setRoutes((current) => current.map((item) => item.id === routeId ? { ...item, stopIds } : item));
    },
    setRouteOrder: async (routeId, stopIds) => {
      if (!developmentDemo) await updateTravelRoute(routeId, { stopIds });
      setRoutes((current) => current.map((item) => item.id === routeId ? { ...item, stopIds } : item));
    },
    setRouteMode: async (routeId, mode) => {
      if (!developmentDemo) await updateTravelRoute(routeId, { mode });
      setRoutes((current) => current.map((item) => item.id === routeId ? { ...item, mode } : item));
    },
    refresh
  }), [capabilities, maps, members, places, refresh, routes, trips, visits]);

  if (loading) return <div className="app-loading">正在加载你的旅行地图…</div>;
  if (error) return <div className="app-loading"><strong>{error}</strong><button type="button" onClick={() => window.location.reload()}>重新加载</button></div>;
  return <TravelContext.Provider value={value}>{children}</TravelContext.Provider>;
}

export function useTravel(): TravelState {
  const value = useContext(TravelContext);
  if (!value) throw new Error("useTravel must be used inside TravelProvider");
  return value;
}
