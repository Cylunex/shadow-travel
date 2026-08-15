import { Clock3, Compass, MapPinned, Menu, Settings, X } from "lucide-react";
import { ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { CurrentUser } from "../api";

const navigation = [
  { to: "/", label: "全局地图", icon: Compass, exact: true },
  { to: "/maps", label: "主题地图", icon: MapPinned },
  { to: "/visits", label: "到访记录", icon: Clock3 }
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const current = navigation.find((item) =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to)
  );

  return (
    <div className="app-frame">
      <aside className="side-rail" aria-label="主导航">
        <NavLink className="brand-mark" to="/" aria-label="Shadow Travel 首页">
          <span>ST</span>
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
        <NavLink className="side-link rail-settings" to="/settings" aria-label="设置">
          <Settings size={21} strokeWidth={1.8} />
          <span>设置</span>
        </NavLink>
        <NavLink className="account-dot" to="/settings" title={user.display_name}>
          {user.display_name.slice(0, 1)}
        </NavLink>
      </aside>

      <header className="mobile-bar">
        <button
          className="icon-button"
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="打开导航"
        >
          <Menu size={22} />
        </button>
        <strong>{current?.label ?? "Shadow Travel"}</strong>
        <NavLink className="mobile-avatar" to="/settings" aria-label="账户设置">
          {user.display_name.slice(0, 1)}
        </NavLink>
      </header>

      {drawerOpen && (
        <div className="nav-drawer-backdrop" role="presentation" onClick={() => setDrawerOpen(false)}>
          <aside
            className="nav-drawer"
            aria-label="移动端导航"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="drawer-heading">
              <div>
                <span className="eyebrow">SHADOW TRAVEL</span>
                <strong>去过的地方，都是地图的一部分</strong>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="关闭导航"
              >
                <X size={21} />
              </button>
            </div>
            <nav>
              {[...navigation, { to: "/settings", label: "设置", icon: Settings }].map(
                ({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} onClick={() => setDrawerOpen(false)}>
                    <Icon size={20} />
                    {label}
                  </NavLink>
                )
              )}
            </nav>
          </aside>
        </div>
      )}

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
                <span>{label.replace("记录", "")}</span>
              </>
            )}
          </NavLink>
        ))}
        <NavLink to="/settings">
          {({ isActive }) => (
            <>
              <Settings size={21} strokeWidth={isActive ? 2.2 : 1.7} />
              <span>设置</span>
            </>
          )}
        </NavLink>
      </nav>
    </div>
  );
}
