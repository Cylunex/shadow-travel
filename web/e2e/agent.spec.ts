import { test, expect, type Page } from "@playwright/test";

async function setup(page: Page, conflict = false) {
  const proposal = {
    grant_id: "grant1",
    trip_id: null,
    expected_trip_version: 0,
    expected_plan_revision: 0,
    summary: "京都五日待审核",
    operations: [
      {
        op: "CREATE_TRIP",
        trip: {
          title: "京都五日",
          start_date: "2026-10-03",
          end_date: "2026-10-07",
          timezone: "Asia/Tokyo",
          status: "planned",
        },
      },
    ],
    inferred: ["标题"],
    uncertainties: ["住宿待确认"],
  };
  let review = {
    review_id: "review1",
    agent_id: "travel-helper",
    trip_id: null,
    summary: proposal.summary,
    state: "pending",
    revision: 1,
    changeset_hash: "a".repeat(64),
    expires_at: "2099-10-01T00:00:00Z",
    proposal,
    preview: {
      changes: [
        { op: "CREATE_TRIP", before: null, after: proposal.operations[0] },
      ],
      checks: { errors: [], warnings: [] },
      inferred: ["标题"],
      uncertainties: ["住宿待确认"],
      notice: "保存可编辑计划，不创建到访或预订成功。",
    },
    result: null as null | { trip_id: string; plan_revision: number },
  };
  let commits = 0;
  await page.route("**/api/browser/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split(
      "/api/browser/v1/",
    )[1];
    let data: unknown = {};
    if (path === "me")
      data = {
        shadow_user_id: "test-user",
        username: "tester",
        display_name: "测试用户",
        email: "test@example.com",
      };
    else if (path === "workspace")
      data = {
        trips: [],
        maps: [],
        places: [],
        visits: [],
        routes: [],
        members: [],
      };
    else if (path === "capabilities")
      data = { media: false, international_maps: false };
    else if (path === "trips") data = { trips: [] };
    else if (path === "agent/grants") data = { grants: [] };
    else if (path === "agent/reviews") data = { reviews: [review] };
    else if (path === "agent/reviews/review1/commit") {
      commits++;
      expect(route.request().postDataJSON()).toEqual({
        expected_revision: review.revision,
        changeset_hash: review.changeset_hash,
      });
      if (conflict) {
        review.state = "conflicted";
        return route.fulfill({
          status: 409,
          json: { detail: { code: "agent_base_version_conflict" } },
        });
      }
      review = {
        ...review,
        state: "committed",
        result: { trip_id: "saved-trip", plan_revision: 1 },
      };
      data = review;
    } else if (
      path === "agent/reviews/review1" &&
      route.request().method() === "PUT"
    ) {
      expect(route.request().postDataJSON().expected_revision).toBe(1);
      review = { ...review, revision: 2, changeset_hash: "b".repeat(64) };
      data = review;
    }
    await route.fulfill({ json: data });
  });
  return () => commits;
}

for (const width of [390, 430, 768, 1280, 1440]) {
  test(`Agent 审核差异在 ${width}px 不溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await setup(page);
    await page.goto("agent?review=review1");
    await expect(
      page.getByRole("heading", { name: "Agent 审核与授权" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "确认保存变更" }),
    ).toBeEnabled();
    await expect(page.getByText("修改前", { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("修改审核修订后只按最新哈希确认，成功提供回读入口", async ({ page }) => {
  const count = await setup(page);
  await page.goto("agent?review=review1");
  await page.getByRole("button", { name: "编辑提案" }).click();
  await expect(
    page.getByRole("button", { name: "确认保存变更" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "校验并保存新修订" }).click();
  await page.getByRole("button", { name: "确认保存变更" }).click();
  await expect(
    page.getByRole("link", { name: /查看已保存旅程/ }),
  ).toHaveAttribute("href", "/travel/trips/saved-trip");
  expect(count()).toBe(1);
  await expect(page.getByRole("button", { name: "确认保存变更" })).toHaveCount(
    0,
  );
});

test("版本冲突明确显示，不伪造成功", async ({ page }) => {
  await setup(page, true);
  await page.goto("agent?review=review1");
  await page.getByRole("button", { name: "确认保存变更" }).click();
  await expect(page.getByRole("alert")).toContainText("未覆盖原数据");
  await expect(
    page.getByRole("button", { name: "确认保存变更" }),
  ).toBeDisabled();
  await expect(page.getByRole("link", { name: /查看已保存旅程/ })).toHaveCount(
    0,
  );
});
