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
    if (route.request().method() === "DELETE") {
      await route.fulfill({ status: 204 });
      return;
    }
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
          selected: true,
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
    } else if (path === "/api/v1/files" && route.request().method() === "GET") {
      const directory = url.searchParams.get("path") ?? "";
      body = directory === "Mods"
        ? {
            path: "Mods",
            parent: "",
            entries: [
              { name: "enabled.json", path: "Mods/enabled.json", kind: "file", size: 128, modified_at: "2026-07-12T03:15:00Z", archive: false },
              { name: "ExampleMod.tmod", path: "Mods/ExampleMod.tmod", kind: "file", size: 880000, modified_at: "2026-07-12T03:15:00Z", archive: false },
            ],
          }
        : {
            path: "",
            parent: null,
            entries: [
              { name: "ModConfigs", path: "ModConfigs", kind: "directory", size: null, modified_at: "2026-07-12T03:15:00Z", archive: false },
              { name: "Mods", path: "Mods", kind: "directory", size: null, modified_at: "2026-07-12T03:15:00Z", archive: false },
              { name: "SaveData.zip", path: "SaveData.zip", kind: "file", size: 714222878, modified_at: "2026-07-12T03:15:00Z", archive: true },
            ],
          };
    } else if (path === "/api/v1/files/upload") {
      body = { name: "Pack.zip", path: "Pack.zip", kind: "file", size: 128, modified_at: "2026-07-12T03:15:00Z", archive: true };
    } else if (path === "/api/v1/files/archive") {
      body = {
        path: "SaveData.zip",
        files: 32,
        directories: 2,
        expanded_size: 732785449,
        compressed_size: 714217434,
        top_level: ["ModConfigs", "Mods"],
        conflicts: ["Mods/enabled.json"],
      };
    } else if (path === "/api/v1/files/archive/extract") {
      body = { destination: "", files: 32, directories: 2, bytes_written: 732785449 };
    } else if (path === "/api/v1/files" && route.request().method() === "PATCH") {
      body = { name: "renamed.zip", path: "renamed.zip", kind: "file", size: 128, modified_at: "2026-07-12T03:15:00Z", archive: true };
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
  await page.getByLabel("主导航").getByRole("button", { name: "控制台" }).click();
  await expect(page.getByRole("heading", { name: "控制台尚未就绪" })).toBeVisible();
  await expect(page.getByText("服务器正在安装，任务会继续在后台运行。")).toBeVisible();
  await page.getByRole("button", { name: "查看安装进度" }).click();
  await expect(page.getByText("Downloading version v2026.07.1.0")).toBeVisible();
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
  await page.getByLabel("主导航").getByRole("button", { name: "控制台" }).click();
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

test("mod workspace supports filtering and confirmed deletion", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "模组" }).click();
  await expect(page.getByPlaceholder("搜索模组")).toBeVisible();
  await expect(page.getByRole("heading", { name: "RecipeBrowser" })).toBeVisible();
  await page.getByPlaceholder("搜索模组").fill("Recipe");
  await expect(page.getByText("BossChecklist")).toBeHidden();
  await page.getByRole("button", { name: "删除" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "删除模组 RecipeBrowser" })).toBeVisible();
  const deletion = page.waitForRequest(
    (request) => request.url().includes("/api/v1/mods/local/RecipeBrowser") && request.method() === "DELETE",
  );
  await dialog.getByRole("button", { name: "删除模组" }).click();
  await deletion;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/mod-management-desktop.png", fullPage: true });
});

test("backup workspace exposes download and confirmed deletion", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "备份" }).click();
  await expect(page.getByPlaceholder("搜索备份")).toBeVisible();
  await expect(page.getByTitle("下载备份")).toHaveAttribute("href", /\/api\/v1\/backups\/.+\/download/);
  await page.getByTitle("删除备份").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "删除备份" })).toBeVisible();
  const deletion = page.waitForRequest(
    (request) => request.url().includes("/api/v1/backups/") && request.method() === "DELETE",
  );
  await dialog.getByRole("button", { name: "删除备份" }).click();
  await deletion;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/backups-desktop.png", fullPage: true });
});

test("world saves can be imported and managed", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "存档" }).click();
  await expect(page.getByText("当前")).toBeVisible();
  await expect(page.getByTitle("删除存档")).toBeDisabled();
  await page.locator('input[accept=".wld,.twld"]').setInputFiles([
    {
      name: "Imported.wld",
      mimeType: "application/octet-stream",
      buffer: Buffer.from([23, 1, 0, 0, 1]),
    },
    {
      name: "Imported.twld",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("mod data"),
    },
  ]);
  await expect(page.getByText("Imported.wld, Imported.twld")).toBeVisible();
  const uploadRequest = page.waitForRequest(
    (request) => request.url().includes("/api/v1/worlds/upload") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "导入" }).click();
  await uploadRequest;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/worlds-desktop.png", fullPage: true });
});

test("world save management fits mobile", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "存档" }).click();
  await expect(page.getByText("选择 .wld / .twld")).toBeVisible();
  await expect(page.getByRole("button", { name: "导入" })).toBeDisabled();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/worlds-mobile.png", fullPage: true });
});

test("file manager handles save data archives", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "文件" }).click();
  await expect(page.getByText("SaveData.zip")).toBeVisible();
  await expect(page.getByText("681.1 MB")).toBeVisible();

  await page.getByRole("button", { name: "Mods" }).click();
  await expect(page.getByText("enabled.json")).toBeVisible();
  await page.getByLabel("文件路径").getByRole("button", { name: "根目录" }).click();

  const uploadRequest = page.waitForRequest(
    (request) => request.url().includes("/api/v1/files/upload") && request.method() === "POST",
  );
  await page.locator('.file-upload-form input[type="file"]').setInputFiles({
    name: "Pack.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("ZIP"),
  });
  await page.getByRole("button", { name: "上传" }).click();
  await uploadRequest;

  await page.getByTitle("查看并解压").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "解压 SaveData.zip" })).toBeVisible();
  await expect(dialog.getByText("ModConfigs, Mods")).toBeVisible();
  await dialog.getByRole("checkbox", { name: "覆盖已有文件" }).check();
  const extraction = page.waitForRequest(
    (request) => request.url().includes("/api/v1/files/archive/extract") && request.method() === "POST",
  );
  await dialog.getByRole("button", { name: "解压" }).click();
  await extraction;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/files-desktop.png", fullPage: true });
});

test("file manager is readable and locked on mobile while running", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "running");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "文件" }).click();
  await expect(page.getByText("运行中只读")).toBeVisible();
  await expect(page.getByRole("button", { name: "上传" })).toBeDisabled();
  await expect(page.getByTitle("查看并解压")).toBeDisabled();
  await expect(page.getByTitle("下载")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/files-mobile.png", fullPage: true });
});
