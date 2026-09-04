import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { CurrentUser, currentUser } from "./api";
import { AppShell } from "./components/AppShell";
import { GlobalMapPage } from "./pages/GlobalMapPage";
import { LoginPage } from "./pages/LoginPage";
import { MapsPage } from "./pages/MapsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlacePage } from "./pages/PlacePage";
import { RoutePage } from "./pages/RoutePage";
import { SettingsPage } from "./pages/SettingsPage";
import { ThemeMapPage } from "./pages/ThemeMapPage";
import { VisitsPage } from "./pages/VisitsPage";
import { TravelProvider } from "./state/TravelContext";
import { TripsPage } from "./features/TripsPage";
import { TripPage } from "./features/TripPage";
import { CapturePage } from "./features/CapturePage";
import { MemoriesPage } from "./features/MemoriesPage";
import { AgentPage } from "./features/AgentPage";
import { setLocalReadMode } from "./offline";

type SessionState =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "authenticated"; user: CurrentUser; demo: boolean }
  | { kind: "offline"; user: CurrentUser }
  | { kind: "error" };

export function App() {
  const [session, setSession] = useState<SessionState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    currentUser(controller.signal).then((user) => {
      if (user) { setLocalReadMode(false); localStorage.setItem("shadow-travel-last-user", JSON.stringify(user)); setSession({ kind: "authenticated", user, demo: false }); }
      else if (import.meta.env.DEV) setSession({ kind: "authenticated", user: demoUser, demo: true });
      else setSession({ kind: "anonymous" });
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (import.meta.env.DEV) setSession({ kind: "authenticated", user: demoUser, demo: true });
      else {
        const saved = localStorage.getItem("shadow-travel-last-user");
        if ((!navigator.onLine || error instanceof TypeError) && saved && localStorage.getItem("shadow-travel-offline-enabled") === "yes") {
          try { setSession({ kind: "offline", user: JSON.parse(saved) as CurrentUser }); } catch { setSession({ kind: "error" }); }
        } else setSession({ kind: "error" });
      }
    });
    return () => controller.abort();
  }, []);

  if (session.kind === "loading") return <main className="loading-screen"><span className="brand-mark"><span>ST</span></span><LoaderCircle className="spin" size={22} /><p>正在展开旅行地图…</p></main>;
  if (session.kind === "anonymous") return <LoginPage />;
  if (session.kind === "error") return <LoginPage unavailable />;
  if (session.kind === "offline") return <main className="loading-screen"><h1>本地旅行副本</h1><p>此操作仅打开 {session.user.display_name} 在本设备下载的副本，不代表服务端登录。共享数据可能过期，联网后重新验证权限。</p><button className="primary-button" onClick={() => { setLocalReadMode(true); setSession({ kind: "authenticated", user: session.user, demo: false }); }}>在已解锁的个人设备上读取</button><button className="secondary-button" onClick={() => setSession({ kind: "anonymous" })}>返回登录</button></main>;

  return <TravelProvider userId={session.user.shadow_user_id} demo={session.demo}><AppShell user={session.user} demo={session.demo}><Routes>
    <Route path="/" element={<GlobalMapPage />} />
    <Route path="/maps" element={<MapsPage />} />
    <Route path="/trips" element={<TripsPage />} />
    <Route path="/agent" element={<AgentPage demo={session.demo} />} />
    <Route path="/trips/:tripId" element={<TripPage />} />
    <Route path="/capture" element={<CapturePage />} />
    <Route path="/memories" element={<MemoriesPage />} />
    <Route path="/maps/:mapId" element={<ThemeMapPage />} />
    <Route path="/maps/:mapId/places/:placeId" element={<PlacePage />} />
    <Route path="/places/:placeId" element={<PlacePage />} />
    <Route path="/visits" element={<VisitsPage />} />
    <Route path="/routes/:routeId" element={<RoutePage />} />
    <Route path="/settings" element={<SettingsPage user={session.user} demo={session.demo} />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></AppShell></TravelProvider>;
}

const demoUser: CurrentUser = { shadow_user_id: "demo-user", username: "demo", display_name: "小影", email: "demo@example.com" };
