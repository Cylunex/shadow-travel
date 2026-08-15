# ShadowApp 接入状态与缺口

## 已确认的现状

Travel 的 Web 侧已经遵守 ShadowApp 模块规范：

- 页面和 API 支持根路径与 `/travel/` 子路径。
- `/healthz` 无状态、无登录，可作为 `probePath`。
- 登录使用当前顶层页面跳转，不依赖弹窗。
- 文件选择使用标准 `<input type="file" accept="image/*">`，现有壳的 `WebChromeClient.onShowFileChooser` 可以处理。
- 页面导航使用浏览器历史，现有壳会优先执行 `webView.goBack()`，没有历史时回应用中心。
- 后台同步服务端端点只接受独立 Bearer，不读取 WebView Cookie。

但当前 ShadowApp 还不能完成 Travel 的 OIDC 登录。壳的 URL 策略只把已登记模块的同源 URL 留在 WebView，其他 HTTP(S) URL 交给系统浏览器。Shadow Identity 使用独立 issuer origin，因此授权页会离开 WebView；HTTPS callback 随后在系统浏览器的 Cookie 容器建立 Travel 会话，WebView 无法得到该 Cookie。

这与平台接入规范中“WebView 必须允许跳转到 Identity，并保留授权过程中所需 Cookie”的要求不一致，不能通过在 URL 中传 Token、共享浏览器 Cookie或增加第二套登录来规避。

## Travel 侧已准备的契约

建议模块登记内容如下，真实服务器地址仍由 ShadowApp 环境配置提供：

```json
{
  "id": "travel",
  "name": "旅行",
  "description": "主题旅行地图与同行协作",
  "routes": [
    {
      "server": "cloud",
      "startPath": "/travel/",
      "probePath": "/travel/healthz"
    }
  ],
  "icon": "web",
  "color": "#315D4E",
  "enabled": true,
  "capabilities": ["web"]
}
```

Travel OIDC callback 固定由配置生成 `${PUBLIC_ORIGIN}/travel/auth/callback`，Cookie Path 为 `/travel/`。前端用 `location.replace()` 进入登录，减少返回键重新进入旧登录页的机会。

后台同步探测端点为 `GET /travel/api/machine/v1/sync/ping`。它只能验证壳持有的独立同步 Bearer，不能接受 OIDC Token、Travel Cookie 或 URL 参数中的凭据。

## ShadowApp 所需的最小改动

在另行确认修改 ShadowApp 后，应单独实现并审查以下能力：

1. 在模块清单登记 Travel，只声明当前实际使用的 `web` 能力。
2. 增加受配置约束的 OIDC navigation allowlist。仅当前受信任模块发起登录时，允许精确的 Identity HTTPS origin 在同一个 WebView 中加载；不能把任意外站改为 WebView 内打开。
3. Identity 页面期间保留原模块上下文，但禁止调用任何模块原生桥；callback 回到 `/travel/` 后恢复 Travel 上下文并压缩登录历史。
4. 为 Travel 后台同步新增独立 feature 与显式 capability。Bearer 保存在 Android 安全存储中，不注入 WebView；请求只允许配置的 Travel origin 和精确 machine path，并携带幂等键。
5. 增加 OIDC 跨域往返、Cookie 持久化、返回键、文件选择、外链系统打开、错误页和 Bearer 不泄漏的 Android 测试。

在上述壳改动完成前，Travel 可在普通浏览器中完成 OIDC 登录，也可独立测试 machine API，但不能宣称 ShadowApp 内 OIDC 与后台同步已经端到端完成。
