import { test, expect, type Page } from "@playwright/test";

const place = {
  id: "place1",
  name: "测试·博物馆",
  shortName: "博物馆",
  address: "测试路 1 号",
  city: "北京",
  district: "东城",
  category: "地点",
  tags: [],
  note: "",
  coordinate: {
    x: 50,
    y: 50,
    longitude: 116.4,
    latitude: 39.9,
    reference: "GCJ02",
  },
  mapIds: [],
  mapPoints: [],
  preference: "none",
  visitedBy: [],
  photos: [],
  provider: "manual",
};
const trip = {
  id: "trip1",
  title: "秋日北京 · 三天慢游",
  clientRecordId: "test-trip",
  version: 1,
  startDate: "2026-10-01",
  endDate: "2026-10-03",
  timezone: "Asia/Shanghai",
  status: "planned",
  updatedAt: "2026-09-04",
};
const document = {
  schema_version: 1,
  candidates: [place.id],
  stops: [
    {
      id: "s1",
      place_id: place.id,
      day: "2026-10-01",
      start: "09:00",
      duration_minutes: 90,
      travel_minutes: null,
      mode: "walking",
      anchor: true,
      note: "提前预约，入口以现场信息为准",
    },
  ],
  reservations: [],
  tasks: [],
  budget: null,
  currency: "CNY",
  constraints: "",
};

async function fixtures(page: Page) {
  let revision = 1;
  let draft = structuredClone(document);
  let runtime: {
    id: string;
    trip_id: string;
    plan_revision: number;
    revision: number;
    member_id: string;
    document: typeof document;
    outcomes: {
      stop_id: string;
      member_id: string;
      state: string;
      revision: number;
      shared: boolean;
      visit_id?: string;
    }[];
    bindings: unknown[];
  } | null = null;
  await page.route("**/api/browser/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split(
      "/api/browser/v1/",
    )[1];
    const plan = () => ({
      trip,
      role: "owner",
      revision,
      approved_revision: 1,
      document: draft,
      places: [place],
      members: [{ id: "test-user", name: "测试用户", role: "owner" }],
      versions: [{ revision: 1, created_at: "2026-09-04", document }],
      checks: { errors: [], warnings: [] },
    });
    let data: unknown;
    if (path === "me")
      data = {
        shadow_user_id: "test-user",
        username: "test-user",
        display_name: "测试用户",
        email: "test@example.com",
      };
    else if (path === "workspace")
      data = {
        trips: [trip],
        maps: [],
        places: [place],
        visits: [],
        routes: [],
        members: [],
      };
    else if (path === "capabilities")
      data = {
        media: false,
        llm: false,
        international_maps: false,
        location_history: false,
        continuous_tracking_default: false,
        location_history_mode: "disabled",
      };
    else if (path === "journeys/trips") data = { trips: [trip] };
    else if (path === "trips/trip1/run") data = { run: runtime };
    else if (path === "trips/trip1/run/start") {
      runtime = {
        id: "run1",
        trip_id: "trip1",
        plan_revision: 1,
        revision: 1,
        member_id: "test-user",
        document: {
          ...document,
          stops: [
            ...document.stops,
            { ...document.stops[0], id: "s2", start: "15:00" },
          ],
        },
        outcomes: [],
        bindings: [],
      };
      data = { run: runtime };
    } else if (path === "trips/trip1/run/commands" && runtime) {
      const command = route.request().postDataJSON();
      runtime.outcomes = [
        ...runtime.outcomes.filter((o) => o.stop_id !== command.stop_id),
        {
          stop_id: command.stop_id,
          member_id: "test-user",
          state: command.state,
          revision: command.base_revision + 1,
          shared: command.shared,
          visit_id: command.visit_date ? "visit1" : undefined,
        },
      ];
      runtime.revision++;
      data = { run: runtime };
    } else if (path === "trips/trip1/plan") {
      if (route.request().method() === "PUT") {
        draft = route.request().postDataJSON().document;
        revision++;
      }
      data = plan();
    } else if (path === "captures")
      data = {
        captures: [
          {
            id: "capture1",
            text: "朋友推荐的一家小店",
            reason: "下次路过去看看",
            status: "pending",
            created_at: "2026-09-04T00:00:00Z",
          },
        ],
      };
    else if (path === "trips/trip1/pack")
      data = {
        ...plan(),
        run: runtime,
        visits: [],
        offline: {
          owner: "test-user",
          downloaded_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
          notice: "不含底图与原始票据",
        },
      };
    else if (path === "memory-photo-options") data = { photos: [] };
    else if (path === "memories")
      data = {
        memories: [
          {
            id: "m1",
            kind: "memory",
            title: "路上的光",
            occurred_on: "2026-10-01",
            document: {
              text: "旅行不必填满每一分钟。",
              visit_ids: [],
              memory_ids: [],
            },
            visibility: "private",
          },
        ],
      };
    else
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "test_endpoint_not_mocked" } }),
      });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}

test("same place has independent runtime stops and explicit visit confirmation", async ({
  page,
}) => {
  await fixtures(page);
  await page.goto("trips/trip1");
  await page.getByRole("button", { name: "旅途中", exact: true }).click();
  await page.getByRole("button", { name: "开始旅途中模式" }).click();
  await expect(page.locator(".trip-runtime .plan-stop")).toHaveCount(2);
  let payload: Record<string, unknown> | undefined;
  page.on("request", (req) => {
    if (req.url().endsWith("/run/commands")) payload = req.postDataJSON();
  });
  await page.getByRole("button", { name: "完成 / 记录到访" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(payload).toBeUndefined();
  await page.getByRole("button", { name: "确认去过并完成此站" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(payload?.stop_id).toBe("s1");
  expect(payload?.visit_date).toBeTruthy();
  await expect(page.locator(".trip-runtime .plan-stop").nth(1)).toContainText(
    "未开始",
  );
  await expect(page.locator(".trip-runtime .plan-stop").first()).toContainText(
    "已关联到访",
  );
});

test("Google unavailable state never draws an imitation map", async ({
  page,
}) => {
  await fixtures(page);
  await page.goto("./");
  await page.getByLabel("地图区域").selectOption("google");
  await expect(
    page.getByRole("status").filter({ hasText: "Google 浏览器地图密钥未配置" }),
  ).toBeVisible();
  await expect(page.locator(".google-attributions")).toHaveCount(0);
  await page.goto("capture");
  await page
    .getByText("海外地点 · Google Maps 搜索与收藏", { exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "搜索 Google Maps" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
});

test("offline runtime command stays queued without marking completed", async ({
  page,
  context,
}) => {
  await fixtures(page);
  await page.goto("trips/trip1");
  await page.getByRole("button", { name: "旅途中", exact: true }).click();
  await page.getByRole("button", { name: "开始旅途中模式" }).click();
  await page.getByRole("button", { name: "资料与准备" }).click();
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "下载旅行副本" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "离线包已写入设备" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "旅途中", exact: true }).click();
  await context.setOffline(true);
  await page.getByRole("button", { name: "完成 / 记录到访" }).first().click();
  await page.getByRole("button", { name: "确认去过并完成此站" }).click();
  await expect(page.locator(".trip-runtime .plan-stop").first()).toContainText(
    "待同步",
  );
  await expect(page.locator(".trip-runtime .plan-stop").nth(1)).toContainText(
    "未开始",
  );
  await context.setOffline(false);
});

test("lost runtime response replays the exact operation rather than creating another", async ({
  page,
}) => {
  await fixtures(page);
  await page.goto("trips/trip1");
  await page.getByRole("button", { name: "旅途中", exact: true }).click();
  await page.getByRole("button", { name: "开始旅途中模式" }).click();
  const requests: unknown[] = [];
  await page.route("**/run/commands", async (route) => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) await route.abort("failed");
    else await route.fallback();
  });
  await page.getByRole("button", { name: "完成 / 记录到访" }).first().click();
  await page.getByRole("button", { name: "确认去过并完成此站" }).click();
  await expect(page.locator(".trip-runtime .plan-stop").first()).toContainText(
    "待同步",
  );
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.locator(".trip-runtime .plan-stop").first()).toContainText(
    "已关联到访",
  );
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
});

test("Google confirmation stores only source reference and user alias", async ({
  page,
}) => {
  await fixtures(page);
  let body: Record<string, unknown> | undefined;
  await page.route("**/maps/places?**", (route) =>
    route.fulfill({
      json: {
        places: [
          {
            provider_place_id: "google-id",
            name: "Google 原始名称",
            address: "实时地址",
            longitude: 139.7,
            latitude: 35.6,
            attributions: [],
            category: "museum",
            country_code: "JP",
          },
        ],
      },
    }),
  );
  await page.route("**/maps/google/references", (route) => {
    body = route.request().postDataJSON();
    return route.fulfill({
      json: {
        ...place,
        id: "foreign1",
        name: body?.alias,
        coordinate: null,
        provider: "google",
        providerPlaceId: "google-id",
        countryCode: "JP",
      },
    });
  });
  await page.goto("capture");
  await page
    .getByText("海外地点 · Google Maps 搜索与收藏", { exact: true })
    .click();
  await page.getByLabel("查找地点", { exact: true }).fill("museum");
  await page.getByRole("button", { name: "搜索 Google Maps" }).click();
  await page.getByRole("button", { name: /Google 原始名称/ }).click();
  await page.getByLabel("我的地点别名").fill("我的东京第一站");
  await page.getByRole("button", { name: "确认保存引用" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "已收藏" }),
  ).toBeVisible();
  expect(body).toEqual({
    provider_place_id: "google-id",
    alias: "我的东京第一站",
    country_code: "JP",
    city: "",
  });
});

test("Plan v2 editor preserves candidate metadata and remains usable on a phone", async ({
  page,
}) => {
  await fixtures(page);
  await page.setViewportSize({ width: 390, height: 900 });
  await page.route("**/plan/upgrade-preview", (route) =>
    route.fulfill({
      json: {
        document: {
          ...document,
          schema_version: 2,
          segments: [],
          candidate_metadata: {},
        },
      },
    }),
  );
  await page.goto("trips/trip1");
  await page.getByRole("button", { name: "预览升级到 Plan v2 草稿" }).click();
  await page.getByText("Plan v2 · 时区与独立路段", { exact: true }).click();
  await page.getByText("候选偏好与备选分组", { exact: true }).click();
  await page.getByRole("combobox", { name: "优先级", exact: true }).selectOption("must");
  await page.getByLabel("收藏理由", { exact: true }).fill("希望优先安排");
  await page.getByRole("button", { name: /保存草稿/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "草稿已保存" }),
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "优先级", exact: true })).toHaveValue("must");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
});

for (const width of [390, 430, 768, 1280, 1440]) {
  test(`responsive lifecycle at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fixtures(page);
    for (const path of [
      "trips",
      "trips/trip1",
      "capture",
      "memories",
      "settings",
    ]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      );
      expect(overflow, `${path} at ${width}`).toBeFalsy();
      if (path === "trips/trip1")
        await page.screenshot({
          path: `test-results/trip-${width}.png`,
          fullPage: true,
        });
    }
  });
}
test("adding a stop only saves a draft, not a visit", async ({ page }) => {
  await fixtures(page);
  await page.goto("trips/trip1");
  let visitsCreated = 0;
  page.on("request", (req) => {
    if (req.url().endsWith("/visits") && req.method() === "POST")
      visitsCreated++;
  });
  await page.getByRole("button", { name: "安排", exact: true }).click();
  await page.getByLabel("开始", { exact: true }).fill("12:00");
  await page.getByRole("button", { name: "加入草稿", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "确认计划", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: /保存草稿/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "草稿已保存" }),
  ).toBeVisible();
  expect(visitsCreated).toBe(0);
});

test.describe("offline cold start", () => {
  test.use({ serviceWorkers: "allow" });
  test("downloaded trip opens without server login and keeps private visit locally", async ({
    page,
    context,
  }) => {
    await fixtures(page);
    await page.goto("trips/trip1");
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
    });
    await expect
      .poll(() =>
        page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
      )
      .toBe(true);
    page.on("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "资料与准备", exact: true }).click();
    await page
      .getByRole("button", { name: "下载旅行副本", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "离线包已写入" }),
    ).toBeVisible();
    await page.unrouteAll({ behavior: "wait" });
    await context.setOffline(true);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "本地旅行副本" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "在已解锁的个人设备上读取" })
      .click();
    await expect(page.getByRole("heading", { name: trip.title })).toBeVisible();
    await page.getByRole("button", { name: "记录到访", exact: true }).click();
    await page.getByRole("button", { name: "确认去过", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "已保存在本机" }),
    ).toBeVisible();
    const entries = await page.evaluate(
      () =>
        new Promise<any[]>((resolve, reject) => {
          const opening = indexedDB.open("shadow-travel-local-v2");
          opening.onsuccess = () => {
            const req = opening.result
              .transaction("entries")
              .objectStore("entries")
              .getAll();
            req.onsuccess = () => {
              resolve(req.result.filter((row: any) => row.kind === "outbox"));
              opening.result.close();
            };
            req.onerror = () => reject(req.error);
          };
        }),
    );
    expect(entries).toHaveLength(1);
    expect(entries[0].value.input.trip_id).toBe("trip1");
    expect(entries[0].owner).toContain("test-user");
    await fixtures(page);
    let uploads = 0;
    await page.route("**/places/place1/visits", async (route) => {
      uploads++;
      expect(route.request().headers()["x-travel-owner"]).toBe("test-user");
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: "confirmed-local",
          placeId: "place1",
          date: "2026-10-01",
          displayDate: "2026-10-01",
          note: "",
          photoCount: 0,
          tripId: "trip1",
        }),
      });
    });
    await context.setOffline(false);
    await page.goto("settings");
    await page.getByRole("button", { name: /同步 \d+ 条/ }).click();
    await expect.poll(() => uploads).toBe(1);
    await expect(
      page.getByRole("button", { name: "同步 0 条", exact: true }),
    ).toBeVisible();
  });
});

test("mobile sheets have three reachable sizes and dark mode keeps navigation usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await fixtures(page);
  await page.goto("trips/trip1");
  const panel = page.locator(".trip-map-layout");
  await page.getByRole("button", { name: "收起", exact: true }).click();
  await expect(panel).toHaveAttribute("data-snap", "collapsed");
  await page.getByRole("button", { name: "展开", exact: true }).click();
  await expect(panel).toHaveAttribute("data-snap", "full");
  await page.getByRole("button", { name: "半屏", exact: true }).click();
  await expect(panel).toHaveAttribute("data-snap", "half");
  await expect
    .poll(async () => {
      const sheet = await page.locator(".trip-plan-panel").boundingBox();
      const map = await panel.boundingBox();
      return Math.abs(sheet!.height / map!.height - 0.5);
    })
    .toBeLessThan(0.02);
  const sheet = await page.locator(".trip-plan-panel").boundingBox();
  const nav = await page.locator(".bottom-nav").boundingBox();
  expect(sheet!.y + sheet!.height).toBeLessThanOrEqual(nav!.y + 1);
  await page.screenshot({
    path: "test-results/trip-mobile-dark.png",
    fullPage: true,
  });
});
