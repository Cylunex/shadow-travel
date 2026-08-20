import { Clock3, Compass, MapPinned, Moon, Settings, Sun } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { CurrentUser } from "../api";

const navigation = [
  { to: "/", label: "地图", icon: Compass, exact: true },
  { to: "/maps", label: "主题", icon: MapPinned },
  { to: "/visits", label: "记录", icon: Clock3 }
];

export function AppShell({
  children,
  user,
  demo
}: {
  children: ReactNode;
  user: CurrentUser;
  demo: boolean;
}) {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = window.localStorage.getItem("shadow-travel-theme");
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });
  const location = useLocation();
  const current = navigation.find((item) =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to)
  );

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("shadow-travel-theme", theme);
  }, [theme]);

  return (
    <div className="app-frame">
      <aside className="side-rail" aria-label="主导航">
        <NavLink className="brand-mark" to="/" aria-label="Shadow Travel 首页">
          <span className="travel-logo">ST</span>
          <small>Shadow<br />Travel</small>
        </NavLink>
        <nav className="side-nav">
          {navigation.map(({ to, label, icon: Icon, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
              aria-label={label}
            >
              <Icon size={21} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <button className="side-link theme-toggle" type="button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`切换到${theme === "dark" ? "日间" : "暗夜"}模式`}>
          {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          <span>{theme === "dark" ? "日间" : "暗夜"}</span>
        </button>
        <NavLink className="side-link rail-settings" to="/settings" aria-label="我的">
          <Settings size={21} strokeWidth={1.8} />
          <span>我的</span>
        </NavLink>
        <NavLink className="account-dot" to="/settings" title={user.display_name}>
          {user.display_name.slice(0, 1)}
        </NavLink>
      </aside>

      <header className="mobile-bar">
        <NavLink className="mobile-brand" to="/"><span className="travel-logo">ST</span><strong>{current?.label ?? "Shadow Travel"}</strong></NavLink>
        <button className="mobile-theme-toggle" type="button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`切换到${theme === "dark" ? "日间" : "暗夜"}模式`}>
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <NavLink className="mobile-avatar" to="/settings" aria-label="账户设置">
          {user.display_name.slice(0, 1)}
        </NavLink>
      </header>

      <div className="app-content">
        {demo && <span className="demo-ribbon">演示数据 · 操作不会保存</span>}
        {children}
      </div>

      <nav className="bottom-nav" aria-label="移动端主导航">
        {navigation.map(({ to, label, icon: Icon, exact }) => (
          <NavLink key={to} to={to} end={exact}>
            {({ isActive }) => (
              <>
                <Icon size={21} strokeWidth={isActive ? 2.2 : 1.7} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
        <NavLink to="/settings">
          {({ isActive }) => (
            <>
              <Settings size={21} strokeWidth={isActive ? 2.2 : 1.7} />
              <span>我的</span>
            </>
          )}
        </NavLink>
      </nav>
    </div>
  );
}
