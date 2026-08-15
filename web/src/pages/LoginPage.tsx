import { ArrowRight, LockKeyhole, MapPinned, Users } from "lucide-react";

import { login } from "../api";

export function LoginPage({ unavailable = false }: { unavailable?: boolean }) {
  return (
    <main className="login-page">
      <section className="login-art" aria-hidden="true">
        <span className="login-brand">ST</span>
        <div className="login-map-line line-one" /><div className="login-map-line line-two" />
        <span className="login-pin pin-a" /><span className="login-pin pin-b" /><span className="login-pin pin-c" />
        <div className="login-quote"><span>把想去的、去过的，</span><strong>都放回自己的地图。</strong></div>
      </section>
      <section className="login-panel">
        <div className="login-box">
          <span className="eyebrow">SHADOW TRAVEL</span>
          <h1>{unavailable ? "暂时无法连接服务" : "欢迎回来"}</h1>
          <p>{unavailable ? "Travel API 暂时不可用，请稍后刷新重试。" : "使用统一身份进入你的旅行地图。不会在浏览器本地保存登录 Token。"}</p>
          {!unavailable && <button className="login-button" type="button" onClick={login}>使用 Shadow Identity 登录 <ArrowRight size={18} /></button>}
          {unavailable && <button className="login-button" type="button" onClick={() => window.location.reload()}>重新连接 <ArrowRight size={18} /></button>}
          <div className="login-features"><span><MapPinned size={17} /> 个人与同行地图</span><span><Users size={17} /> 精确协作权限</span><span><LockKeyhole size={17} /> OIDC + PKCE</span></div>
        </div>
      </section>
    </main>
  );
}
