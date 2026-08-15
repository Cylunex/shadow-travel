import { Globe2, Image, LogOut, Map, ShieldCheck, Smartphone } from "lucide-react";

import { CurrentUser, logout } from "../api";
import { useTravel } from "../state/TravelContext";

export function SettingsPage({ user, demo }: { user: CurrentUser; demo: boolean }) {
  const { capabilities } = useTravel();
  return (
    <div className="content-page settings-page">
      <header className="content-header">
        <div><span className="eyebrow">MY SHADOW TRAVEL</span><h1>我的旅行</h1><p>账户来自 Shadow Identity，个人意愿、到访和照片权限由 Travel 独立管理。</p></div>
      </header>

      <div className="settings-layout">
        <main className="settings-main">
          <section className="settings-section account-section">
            <div className="settings-profile"><span>{user.display_name.slice(0, 1)}</span><div><strong>{user.display_name}</strong><small>{user.email || user.username}</small></div>{demo && <em>本地演示会话</em>}</div>
            {!demo && <button className="secondary-button" type="button" onClick={() => { void logout(); }}><LogOut size={16} /> 退出登录</button>}
          </section>

          <section className="settings-section">
            <header><div><span className="eyebrow">MAPS</span><h2>地图服务</h2></div><Map size={21} /></header>
            <div className="setting-row"><div><strong>国内地图</strong><span>高德地图 · GCJ-02 · 地点搜索、选点与路线</span></div><em className="status-good">已启用</em></div>
            <div className="setting-row"><div><strong>国际地图</strong><span>Google Maps · WGS-84</span></div><em className={capabilities.international_maps ? "status-good" : undefined}>{capabilities.international_maps ? "已配置" : "架构预留"}</em></div>
            <p className="setting-note"><Globe2 size={16} /> 页面通过 MapProvider 使用地图能力，旅行数据不会绑定某一个 SDK。</p>
          </section>

          <section className="settings-section">
            <header><div><span className="eyebrow">MEDIA</span><h2>照片能力</h2></div><Image size={21} /></header>
            <div className="setting-row"><div><strong>Shadow Media</strong><span>照片保持私密，业务库只保存 media_id</span></div><em className={capabilities.media ? "status-good" : undefined}>{capabilities.media ? "已配置" : "等待配置"}</em></div>
            <p className="setting-note"><ShieldCheck size={16} /> 上传时由后端申请一次性目标；原始 EXIF 与 GPS 默认清理，不生成永久公开地址。</p>
          </section>
        </main>

        <aside className="settings-side">
          <section className="settings-section integration-card">
            <Smartphone size={22} /><h2>ShadowApp 接入位已保留</h2><p>WebView 返回键、登录跳转、文件选择和后台同步将在 App 壳阶段接通。</p><span>当前使用响应式 Web / PWA 布局</span>
          </section>
          <section className="settings-section">
            <header><div><span className="eyebrow">SECURITY</span><h2>当前安全边界</h2></div><ShieldCheck size={21} /></header>
            <p className="setting-note">OIDC 服务端会话、最小准入组、同源写保护与资源成员权限均已启用。</p>
          </section>
        </aside>
      </div>
    </div>
  );
}
