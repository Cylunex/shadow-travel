import {
  Bell,
  ChevronRight,
  Database,
  Download,
  ExternalLink,
  Globe2,
  Image,
  KeyRound,
  LogOut,
  Map,
  ShieldCheck,
  Smartphone,
  Upload
} from "lucide-react";
import { useState } from "react";

import { CurrentUser, basePath } from "../api";
import { Toast } from "../components/Shared";

export function SettingsPage({ user, demo }: { user: CurrentUser; demo: boolean }) {
  const [stripExif, setStripExif] = useState(true);
  const [reminders, setReminders] = useState(false);
  const [toast, setToast] = useState<string>();

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(undefined), 2200);
  }

  return (
    <div className="content-page settings-page">
      <header className="content-header">
        <div><span className="eyebrow">PREFERENCES</span><h1>设置</h1><p>账户来自 Shadow Identity，地图和媒体权限由 Travel 独立管理。</p></div>
      </header>

      <div className="settings-layout">
        <main className="settings-main">
          <section className="settings-section account-section">
            <div className="settings-profile"><span>{user.display_name.slice(0, 1)}</span><div><strong>{user.display_name}</strong><small>{user.email || user.username}</small></div>{demo && <em>演示会话</em>}</div>
            {!demo && <a className="secondary-button" href={`${basePath}auth/logout`}><LogOut size={16} /> 退出登录</a>}
          </section>

          <section className="settings-section">
            <header><div><span className="eyebrow">MAPS</span><h2>地图服务</h2></div><Map size={21} /></header>
            <div className="setting-row"><div><strong>国内地图</strong><span>高德地图 · GCJ-02</span></div><em className="status-good">当前默认</em></div>
            <div className="setting-row"><div><strong>国际地图</strong><span>Google Maps · WGS-84</span></div><em>架构预留</em></div>
            <p className="setting-note"><Globe2 size={16} /> 地图供应商由区域策略选择，业务页面不会直接依赖 SDK。</p>
          </section>

          <section className="settings-section">
            <header><div><span className="eyebrow">MEDIA PRIVACY</span><h2>照片与位置</h2></div><Image size={21} /></header>
            <label className="toggle-row"><div><strong>上传时清理敏感 EXIF</strong><span>默认移除设备信息；GPS 仅在你确认后用于地点匹配。</span></div><input type="checkbox" checked={stripExif} onChange={(event) => setStripExif(event.target.checked)} /><span className="toggle" /></label>
            <div className="setting-row"><div><strong>照片默认可见范围</strong><span>仅相关地图成员</span></div><button type="button">调整 <ChevronRight size={15} /></button></div>
            <p className="setting-note"><ShieldCheck size={16} /> 浏览器不会持有 Media 服务凭据，页面只接收短时访问地址。</p>
          </section>

          <section className="settings-section">
            <header><div><span className="eyebrow">NOTIFICATIONS</span><h2>提醒</h2></div><Bell size={21} /></header>
            <label className="toggle-row"><div><strong>同行协作提醒</strong><span>有人邀请、评论或调整共享路线时提醒我。</span></div><input type="checkbox" checked={reminders} onChange={(event) => setReminders(event.target.checked)} /><span className="toggle" /></label>
          </section>
        </main>

        <aside className="settings-side">
          <section className="settings-section">
            <header><div><span className="eyebrow">DATA</span><h2>数据管理</h2></div><Database size={21} /></header>
            <button className="settings-action" type="button" onClick={() => notify("导出任务已进入设计队列")}><Download size={18} /><span><strong>导出旅行数据</strong><small>地图、地点、到访与备注</small></span><ChevronRight size={16} /></button>
            <button className="settings-action" type="button" onClick={() => notify("导入会先预览差异，不会直接覆盖")}><Upload size={18} /><span><strong>导入地点清单</strong><small>支持预览与去重</small></span><ChevronRight size={16} /></button>
          </section>
          <section className="settings-section integration-card">
            <Smartphone size={22} /><h2>ShadowApp 接入位已保留</h2><p>WebView 返回键、登录跳转、文件选择和后台同步将在 App 壳阶段接通。</p><span>当前优先完成 Web</span>
          </section>
          <section className="settings-section">
            <header><div><span className="eyebrow">SECURITY</span><h2>安全与授权</h2></div><KeyRound size={21} /></header>
            <a className="settings-action" href="https://example.com" target="_blank" rel="noreferrer"><ExternalLink size={18} /><span><strong>查看已授权应用</strong><small>由 Shadow Identity 管理</small></span><ChevronRight size={16} /></a>
          </section>
        </aside>
      </div>
      {toast && <Toast>{toast}</Toast>}
    </div>
  );
}
