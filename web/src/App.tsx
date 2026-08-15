import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { CurrentUser, currentUser } from "./api";
import { AppShell } from "./components/AppShell";
import { AssistantPage } from "./pages/AssistantPage";
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

type SessionState =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "authenticated"; user: CurrentUser; demo: boolean }
  | { kind: "error" };

export function App() {
  const [session, setSession] = useState<SessionState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    currentUser(controller.signal).then((user) => {
      if (user) setSession({ kind: "authenticated", user, demo: false });
      else if (import.meta.env.DEV) setSession({ kind: "authenticated", user: demoUser, demo: true });
      else setSession({ kind: "anonymous" });
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (import.meta.env.DEV) setSession({ kind: "authenticated", user: demoUser, demo: true });
      else setSession({ kind: "error" });
    });
    return () => controller.abort();
  }, []);

  if (session.kind === "loading") return <main className="loading-screen"><span className="brand-mark"><span>ST</span></span><LoaderCircle className="spin" size={22} /><p>正在展开旅行地图…</p></main>;
  if (session.kind === "anonymous") return <LoginPage />;
  if (session.kind === "error") return <LoginPage unavailable />;

  return <TravelProvider><AppShell user={session.user} demo={session.demo}><Routes><Route path="/" element={<GlobalMapPage />} /><Route path="/maps" element={<MapsPage />} /><Route path="/maps/:mapId" element={<ThemeMapPage />} /><Route path="/places/:placeId" element={<PlacePage />} /><Route path="/visits" element={<VisitsPage />} /><Route path="/routes/:routeId" element={<RoutePage />} /><Route path="/assistant" element={<AssistantPage />} /><Route path="/settings" element={<SettingsPage user={session.user} demo={session.demo} />} /><Route path="*" element={<NotFoundPage />} /></Routes></AppShell></TravelProvider>;
}

const demoUser: CurrentUser = { shadow_user_id: "demo-user", username: "demo", display_name: "小影", email: "demo@example.com" };
