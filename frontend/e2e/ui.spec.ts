import { expect, type Page, test } from "@playwright/test";

const instance = {
  configured: true,
  instance: {
    id: "primary",
    name: "Primary Server",
    root_dir: "/srv/terrapanel/primary",
    install_dir: "/srv/terrapanel/primary/server",
    launch_script: "/srv/terrapanel/primary/server/start-tModLoaderServer.sh",
    config_file: "/srv/terrapanel/primary/serverconfig.txt",
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:00:00Z",
  },
  process: {
    state: "running",
    pid: 4217,
    started_at: "2026-07-12T00:00:00Z",
    exit_code: null,
  },
};

async function mockConfiguredApi(page: Page, state: "running" | "stopped" = "running") {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown = {};
    if (path === "/api/v1/instance") {
      body = {
        ...instance,
        process: {
          ...instance.process,
          state,
          pid: state === "running" ? instance.process.pid : null,
        },
      };
    }
    else if (path === "/api/v1/provisioning") {
      body = { state: "idle", stage: "idle", operation: null, name: null, root_dir: null, version: null, started_at: null, finished_at: null, error: null, instance: null, process: null };
    } else if (path === "/api/v1/provisioning/logs") body = [];
    else if (path === "/api/v1/server-config") {
      body = { values: { maxplayers: "12", port: "7777", motd: "Welcome" } };
    } else if (path === "/api/v1/worlds") {
      body = [
        {
          name: "TerraPrime",
          path: "Worlds/TerraPrime.wld",
          has_mod_data: true,
          size: 5242880,
          modified_at: "2026-07-12T00:00:00Z",
        },
      ];
    } else if (path === "/api/v1/mods") {
      body = [
        { name: "RecipeBrowser", source: "local", file: "Mods/RecipeBrowser.tmod", size: 880000, enabled: true },
        { name: "BossChecklist", source: "workshop", file: "steamapps/workshop/content/1281930/1/BossChecklist.tmod", size: 1200000, enabled: false },
      ];
    } else if (path === "/api/v1/backups") {
      body = [
        { id: "20260712T031500000000Z-manual", created_at: "2026-07-12T03:15:00Z", size: 7340032, world_files: 1 },
      ];
    } else if (path === "/api/v1/instance/console") {
      body = [
        { sequence: 1, timestamp: "2026-07-12T03:15:00Z", stream: "system", text: "Starting tModLoader server" },
        { sequence: 2, timestamp: "2026-07-12T03:15:01Z", stream: "stdout", text: "Listening on port 7777" },
        { sequence: 3, timestamp: "2026-07-12T03:15:02Z", stream: "stdout", text: "Server started" },
      ];
    } else if (path.startsWith("/api/v1/logs/")) {
      body = { source: "server", path: "server/tModLoader-Logs/server.log", lines: ["Server started", "World loaded: TerraPrime"] };
    } else if (path.endsWith("/start") || path.endsWith("/stop")) body = instance.process;
    else if (path.endsWith("/console")) body = { status: "accepted" };
    await route.fulfill({ json: body });
  });
}

async function mockInstallingApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/v1/instance") {
      body = { configured: false, instance: null, process: { state: "stopped", pid: null, started_at: null, exit_code: null } };
    } else if (path === "/api/v1/provisioning") {
      body = {
        state: "running",
        stage: "installing",
        operation: "install",
        name: "Primary Server",
        root_dir: "/srv/terrapanel/primary",
        version: null,
        started_at: "2026-07-12T00:00:00Z",
        finished_at: null,
        error: null,
        instance: null,
        process: null,
      };
    } else if (path === "/api/v1/provisioning/logs") {
      body = [
        { sequence: 1, timestamp: "2026-07-12T00:00:00Z", stream: "system", text: "Downloading the verified tModLoader management script" },
        { sequence: 2, timestamp: "2026-07-12T00:00:01Z", stream: "stdout", text: "Downloading version v2026.07.1.0" },
      ];
    }
    await route.fulfill({ json: body });
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("unconfigured desktop is usable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "新建服务器" })).toBeVisible();
  await expect(page.getByRole("button", { name: "安装并开服" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/unconfigured-desktop.png", fullPage: true });
});

test("installation progress is diagnosable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockInstallingApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect(page.getByText("Downloading version v2026.07.1.0")).toBeVisible();
  await expect(page.getByRole("button", { name: "取消任务" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/installing-desktop.png", fullPage: true });
});

test("unconfigured mobile setup fits", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "新建服务器" })).toBeVisible();
  await expect(page.getByRole("button", { name: "安装并开服" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/setup-mobile.png", fullPage: true });
});

test("configured console is readable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "控制台" }).click();
  await expect(page.getByText("Listening on port 7777")).toBeVisible();
  await expect(page.getByPlaceholder("输入服务端命令")).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/configured-console.png", fullPage: true });
});

test("configured mobile overview fits", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Primary Server" })).toBeVisible();
  await expect(page.getByRole("button", { name: "停止" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/configured-mobile.png", fullPage: true });
});

test("local mod upload is usable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "模组" }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "ExampleMod.tmod",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("TMOD"),
  });
  await expect(page.getByText("ExampleMod.tmod")).toBeVisible();
  const uploadRequest = page.waitForRequest(
    (request) => request.url().includes("/api/v1/mods/upload") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "上传" }).click();
  await uploadRequest;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/mod-upload-desktop.png", fullPage: true });
});

test("local mod upload fits mobile", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "模组" }).click();
  await expect(page.getByText("选择 .tmod")).toBeVisible();
  await expect(page.getByRole("button", { name: "上传" })).toBeDisabled();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/mod-upload-mobile.png", fullPage: true });
});
