# 本地开发

本文只描述本地开发与验证。生产配置、密钥和运维步骤不保存在本仓库。

## 前置条件

- Windows 上使用 Git Bash 执行命令。
- Python 3.12 或更高版本。
- Node.js 24 或当前受支持的 LTS 版本。
- `shadow-platform` 与本仓库位于同一父目录，或已经从内部包源安装兼容的 `shadow-platform`。

## 后端

在仓库根目录执行：

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ../shadow-platform -e '.[dev]'
cp .env.example .env
set -a
source .env
set +a
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn shadow_travel.main:app --reload --host 127.0.0.1 --port 8000
```

示例配置不会包含可用的 OIDC、地图或平台凭据。未配置这些能力时，服务仍可启动并通过 `/healthz`；登录和相应外部能力会明确返回未配置状态。本地真实密钥只通过仓库外文件引用。

常用检查：

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pytest
```

## 前端

```bash
cd web
npm install
npm run dev
```

Vite 在根路径启动，并把 `/api`、`/auth` 和健康检查代理到本地后端。浏览器登录使用顶层页面跳转，不依赖弹窗。

本地后端未配置 OIDC 或不可用时，前端会进入带有“演示数据”标识的内存会话，用于完整查看页面和交互；刷新后演示操作会复原。该降级仅在 Vite development 模式启用，production build 不会绕过登录。

外部地点和路线跳转也经过前端 `ClientMapProvider` 边界，由具体 Provider 生成 URI，业务页面不拼接供应商地址。

### 高德地图本地联调

国内地图使用高德 JS API 2.0。前端不读取仓库内的 Key，而是在构建时通过 `AMAP_PROPERTIES_FILE` 指向仓库外的 properties 文件：

```properties
key=REPLACE_WITH_AMAP_JS_KEY
jscode=REPLACE_WITH_AMAP_SECURITY_JS_CODE
```

`web/.env.local` 只保存这个外部文件路径并已被 Git 忽略。Vite 在内存中读取配置并交给官方 `@amap/amap-jsapi-loader`；Key 和安全码不会写入源码、示例文件或提交记录。JS API 本身要求在线加载，地图无法离线工作。

JS API Key 和 Web 服务 API Key 是不同类型，不能混用：

- JS API Key：底图、浏览器端 POI 搜索、选点逆地理编码和路线预览。
- Web 服务 Key：Travel 后端的地点搜索、编码与路线接口，通过 `TRAVEL_AMAP_SERVER_KEY_FILE` 单独配置。

Web 服务 Key 文件既可以只包含原始 Key，也可以使用 properties 格式；启用数字签名时使用 `key` 与 `private_key` 字段。不要把 JS API 的 `jscode` 当作 Web 服务签名私钥。

验证生产子路径构建，但不执行部署：

```bash
cd web
VITE_BASE_PATH=travel npm run build
```

构建结果中的 HTML、JS、CSS 和 manifest 必须以 `/travel/` 为基址。后端对应使用 `TRAVEL_ROOT_PATH=/travel` 和仅包含 scheme/authority 的 `TRAVEL_PUBLIC_ORIGIN=https://example.com`。本地根路径运行时 `TRAVEL_ROOT_PATH` 留空。

## 数据库迁移

本地默认使用 SQLite 以缩短首次启动时间；生产目标是 PostgreSQL。迁移命令始终通过 Alembic：

```bash
.venv/Scripts/python.exe -m alembic current
.venv/Scripts/python.exe -m alembic upgrade head
```

应用启动不会自动建表或自动迁移，避免多个实例并发修改数据库。

## 配置规则

- 所有应用配置使用 `TRAVEL_` 前缀。
- `*_FILE` 变量指向仓库外的密钥文件；配置中不直接放 Token 或 Key。
- production 模式会拒绝非 `/travel` 根路径、HTTP 公共 origin、非 Secure Cookie、非 PostgreSQL 数据库和缺失的 OIDC client secret。
- `TRAVEL_OIDC_CLIENT_ID` 固定为 `shadow-travel`，准入组固定为 `travel-users`。
- Agent audience 固定为 `travel`；浏览器会话不能访问 machine API。

## 当前可验证端点

- `GET /healthz`：不访问数据库。
- `GET /readyz`：检查数据库与必要配置。
- `GET /auth/login`、`GET /auth/callback`：OIDC Code + PKCE。
- `POST /auth/logout`、`POST /auth/logout/global`：本地与全局退出。
- `GET /api/browser/v1/me`：只接受 Travel 应用会话。
- `GET /api/browser/v1/maps/places`：Provider 无关的地点搜索。
- `GET /api/browser/v1/maps/reverse-geocode`：Provider 无关的地图选点解析。
- `POST /api/browser/v1/maps/routes`：Provider 无关的路线计算。
- `GET /api/machine/v1/agent/capabilities`：只接受 Shadow Agent Bearer。
- `GET /api/machine/v1/sync/ping`：只接受独立后台同步 Bearer。

外部能力的生产地址、凭据文件位置、反向代理和发布命令不属于本地开发文档。
