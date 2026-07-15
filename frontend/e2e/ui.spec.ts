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
  const consoleOutput = [
    { sequence: 1, timestamp: "2026-07-12T03:15:00Z", stream: "system", text: "Starting tModLoader server" },
    { sequence: 2, timestamp: "2026-07-12T03:15:01Z", stream: "stdout", text: "Listening on port 7777" },
    { sequence: 3, timestamp: "2026-07-12T03:15:02Z", stream: "stdout", text: "Server started" },
  ];
  const modsOutput = [
    { name: "RecipeBrowser", source: "local", file: "Mods/RecipeBrowser.tmod", size: 880000, enabled: true },
    { name: "BossChecklist", source: "workshop", file: "steamapps/workshop/content/1281930/1/BossChecklist.tmod", size: 1200000, enabled: false },
    { name: "森罗万象", source: "workshop", file: "steamapps/workshop/content/1281930/2/PublishedPackage.tmod", size: 77630932, enabled: true },
  ];
  const worldsOutput = [
    {
      name: "TerraPrime",
      path: "Worlds/TerraPrime.wld",
      has_mod_data: true,
      size: 5242880,
      modified_at: "2026-07-12T00:00:00Z",
      selected: true,
      exists: true,
    },
  ];
  const taskOutput = [
    {
      id: "task-schedule-1",
      name: "每小时状态广播",
      enabled: true,
      trigger: { type: "interval", interval_seconds: 3600, start_at: "2026-07-12T03:00:00Z" },
      actions: [{ type: "command", command: "say Server is healthy" }],
      created_at: "2026-07-12T03:00:00Z",
      updated_at: "2026-07-12T03:00:00Z",
      next_run_at: "2026-07-12T04:00:00Z",
      running: false,
      last_run: null,
    },
    {
      id: "task-event-1",
      name: "异常退出自动恢复",
      enabled: true,
      trigger: { type: "event", event: "server_failed", cooldown_seconds: 30 },
      actions: [{ type: "wait", delay_seconds: 10 }, { type: "start" }],
      created_at: "2026-07-12T03:00:00Z",
      updated_at: "2026-07-12T03:00:00Z",
      next_run_at: null,
      running: false,
      last_run: null,
    },
  ];
  const taskRuns = [
    {
      id: "run-1",
      task_id: "task-schedule-1",
      task_name: "每小时状态广播",
      source: "schedule",
      event: null,
      status: "success",
      started_at: "2026-07-12T03:00:00Z",
      finished_at: "2026-07-12T03:00:01Z",
      message: "Completed 1 action(s)",
    },
  ];
  const controls = { stopDelayMs: 0 };
  const configValues: Record<string, string> = {
    maxplayers: "12",
    port: "7777",
    motd: "Welcome",
    secure: "1",
    upnp: "0",
    priority: "1",
  };
  let textRevision = 1;
  const textFiles = new Map<string, string>([
    ["WorldConfigs/TerraPrime.txt", "maxplayers=12\nport=7777\nmotd=Welcome\nsecure=1\nupnp=0\npriority=1\n"],
    ["serverconfig.txt", "maxplayers=12\nport=7777\nsecure=1\n"],
    ["server/start-tModLoaderServer.sh", "#!/usr/bin/env bash\nlaunch_args=\"-server\"\n"],
  ]);
  const activeConfigPath = () => {
    const world = worldsOutput.find((entry) => entry.selected);
    return world ? `WorldConfigs/${world.name}.txt` : null;
  };
  const currentRevision = () => textRevision.toString(16).padStart(64, "0");
  const serializeConfig = () => `${Object.entries(configValues).map(([key, value]) => `${key}=${value}`).join("\n")}\n`;
  const syncActiveConfigText = () => {
    const path = activeConfigPath();
    if (path) textFiles.set(path, serializeConfig());
  };
  const setSecure = (value: string) => {
    configValues.secure = value;
    syncActiveConfigText();
    textRevision += 1;
  };
  const spamStatus = () => {
    const script = textFiles.get("server/start-tModLoaderServer.sh") ?? "";
    const secureLaunchArgument = script
      .split("\n")
      .some((line) => !line.trimStart().startsWith("#") && /(?:^|\s)-secure(?:\s|$|\")/.test(line));
    const secureValue = configValues.secure ?? null;
    const enabled = secureValue === "1" ? true : secureValue === "0" ? false : null;
    return {
      config_path: activeConfigPath(),
      secure_value: activeConfigPath() ? secureValue : null,
      secure_configured: activeConfigPath() !== null && secureValue !== null,
      secure_enabled: activeConfigPath() ? enabled : null,
      launch_script_path: "server/start-tModLoaderServer.sh",
      launch_script_inspected: true,
      secure_launch_argument: secureLaunchArgument,
      projectile_spam_matches: 2,
      projectile_spam_sources: ["server"],
      protection_disabled: activeConfigPath() !== null && enabled === false && !secureLaunchArgument,
    };
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (route.request().method() === "DELETE") {
      if (path.startsWith("/api/v1/worlds/")) {
        const name = decodeURIComponent(path.slice("/api/v1/worlds/".length));
        const worldIndex = worldsOutput.findIndex((world) => world.name === name);
        const deleted = worldIndex >= 0 ? worldsOutput[worldIndex] : null;
        if (worldIndex >= 0) worldsOutput.splice(worldIndex, 1);
        if (deleted) textFiles.delete(`WorldConfigs/${deleted.name}.txt`);
        await route.fulfill({ json: deleted?.exists ? [`${name}.wld`, `${name}.twld`] : [] });
      } else if (path.startsWith("/api/v1/tasks/")) {
        const id = decodeURIComponent(path.slice("/api/v1/tasks/".length));
        const index = taskOutput.findIndex((task) => task.id === id);
        if (index >= 0) taskOutput.splice(index, 1);
        await route.fulfill({ status: 204 });
      } else {
        await route.fulfill({ status: 204 });
      }
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
    else if (path === "/api/v1/server-config/spam-check/disable") {
      setSecure("0");
      body = spamStatus();
    } else if (path === "/api/v1/server-config/spam-check") {
      body = spamStatus();
    } else if (path === "/api/v1/server-config") {
      if (route.request().method() === "PATCH") {
        const payload = route.request().postDataJSON() as Record<string, unknown>;
        for (const [key, value] of Object.entries(payload)) {
          if (value === null) delete configValues[key];
          else if (typeof value === "boolean") configValues[key] = value ? "1" : "0";
          else configValues[key] = String(value);
        }
        syncActiveConfigText();
        textRevision += 1;
      }
      body = { values: { ...configValues } };
    } else if (path === "/api/v1/worlds" && route.request().method() === "POST") {
      const payload = route.request().postDataJSON() as { name: string };
      for (const world of worldsOutput) world.selected = false;
      const created = {
        name: payload.name,
        path: `Worlds/${payload.name}.wld`,
        has_mod_data: false,
        size: 0,
        modified_at: "2026-07-13T00:00:00Z",
        selected: true,
        exists: false,
      };
      worldsOutput.push(created);
      textFiles.set(`WorldConfigs/${payload.name}.txt`, serializeConfig());
      body = created;
    } else if (path === "/api/v1/worlds") {
      body = worldsOutput;
    } else if (path === "/api/v1/worlds/select") {
      const payload = route.request().postDataJSON() as { path: string };
      for (const world of worldsOutput) world.selected = world.path === payload.path;
      body = { values: { ...configValues } };
    } else if (path === "/api/v1/mods") {
      body = modsOutput;
    } else if (path === "/api/v1/mods/enable" || path === "/api/v1/mods/disable") {
      const payload = route.request().postDataJSON() as { name: string };
      const mod = modsOutput.find((entry) => entry.name === payload.name);
      if (mod) mod.enabled = path.endsWith("/enable");
      body = modsOutput.filter((entry) => entry.enabled).map((entry) => entry.name);
    } else if (path === "/api/v1/backups") {
      body = [
        { id: "20260712T031500000000Z-manual", created_at: "2026-07-12T03:15:00Z", size: 7340032, world_files: 1 },
      ];
    } else if (path === "/api/v1/tasks/runs") {
      body = taskRuns;
    } else if (path === "/api/v1/tasks" && route.request().method() === "POST") {
      const payload = route.request().postDataJSON() as typeof taskOutput[number];
      const created = {
        ...payload,
        id: `task-${taskOutput.length + 1}`,
        created_at: "2026-07-12T03:20:00Z",
        updated_at: "2026-07-12T03:20:00Z",
        next_run_at: payload.trigger.type === "event" ? null : "2026-07-12T05:00:00Z",
        running: false,
        last_run: null,
      };
      taskOutput.push(created);
      body = created;
    } else if (path === "/api/v1/tasks") {
      body = taskOutput;
    } else if (path.endsWith("/enabled") && path.startsWith("/api/v1/tasks/")) {
      const id = path.split("/").at(-2);
      const payload = route.request().postDataJSON() as { enabled: boolean };
      const task = taskOutput.find((entry) => entry.id === id);
      if (task) {
        task.enabled = payload.enabled;
        task.next_run_at = payload.enabled && task.trigger.type !== "event"
          ? "2026-07-12T05:00:00Z"
          : null;
      }
      body = task;
    } else if (path.endsWith("/run") && path.startsWith("/api/v1/tasks/")) {
      const id = path.split("/").at(-2);
      const task = taskOutput.find((entry) => entry.id === id)!;
      const run = {
        id: `run-${taskRuns.length + 1}`,
        task_id: task.id,
        task_name: task.name,
        source: "manual",
        event: null,
        status: "success",
        started_at: "2026-07-12T03:21:00Z",
        finished_at: "2026-07-12T03:21:01Z",
        message: `Completed ${task.actions.length} action(s)`,
      };
      taskRuns.unshift(run);
      task.last_run = run;
      body = run;
    } else if (path.startsWith("/api/v1/tasks/") && route.request().method() === "PUT") {
      const id = decodeURIComponent(path.slice("/api/v1/tasks/".length));
      const task = taskOutput.find((entry) => entry.id === id)!;
      const payload = route.request().postDataJSON() as typeof task;
      Object.assign(task, payload, { updated_at: "2026-07-12T03:22:00Z" });
      body = task;
    } else if (path === "/api/v1/files/text" && route.request().method() === "GET") {
      const filePath = url.searchParams.get("path") ?? "";
      const content = textFiles.get(filePath) ?? "";
      body = { path: filePath, content, revision: currentRevision(), size: Buffer.byteLength(content) };
    } else if (path === "/api/v1/files/text" && route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as { path: string; content: string };
      textFiles.set(payload.path, payload.content);
      textRevision += 1;
      if (payload.path === activeConfigPath()) {
        for (const key of Object.keys(configValues)) delete configValues[key];
        for (const line of payload.content.split(/\r?\n/)) {
          const normalized = line.trim();
          if (!normalized || normalized.startsWith("#")) continue;
          const separator = normalized.indexOf("=");
          if (separator < 1) continue;
          configValues[normalized.slice(0, separator).trim().toLowerCase()] = normalized.slice(separator + 1).trim();
        }
      }
      body = { path: payload.path, content: payload.content, revision: currentRevision(), size: Buffer.byteLength(payload.content) };
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
              { name: "serverconfig.txt", path: "serverconfig.txt", kind: "file", size: 43, modified_at: "2026-07-12T03:15:00Z", archive: false },
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
      const afterSequence = Number(url.searchParams.get("after_sequence") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 500);
      body = consoleOutput.filter((entry) => entry.sequence > afterSequence).slice(-limit);
    } else if (path.startsWith("/api/v1/logs/")) {
      body = { source: "server", path: "server/tModLoader-Logs/server.log", lines: ["Server started", "World loaded: TerraPrime"] };
    } else if (path.endsWith("/stop")) {
      if (controls.stopDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, controls.stopDelayMs));
      }
      body = { ...instance.process, state: "stopped", pid: null };
    } else if (path.endsWith("/start")) body = instance.process;
    else if (path.endsWith("/console")) body = { status: "accepted" };
    await route.fulfill({ json: body });
  });
  return { consoleOutput, configValues, controls, modsOutput, taskOutput, taskRuns };
}

async function mockUnconfiguredApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/v1/instance") {
      body = {
        configured: false,
        instance: null,
        process: { state: "stopped", pid: null, started_at: null, exit_code: null },
      };
    } else if (path === "/api/v1/provisioning") {
      body = {
        state: "idle",
        stage: "idle",
        operation: null,
        name: null,
        root_dir: null,
        version: null,
        started_at: null,
        finished_at: null,
        error: null,
        instance: null,
        process: null,
      };
    } else if (path === "/api/v1/provisioning/logs") {
      body = [];
    }
    await route.fulfill({ json: body });
  });
}

async function mockInstallingApi(page: Page) {
  const provisionOutput = [
    { sequence: 1, timestamp: "2026-07-12T00:00:00Z", stream: "system", text: "Downloading the verified tModLoader management script" },
    { sequence: 2, timestamp: "2026-07-12T00:00:01Z", stream: "stdout", text: "Downloading version v2026.07.1.0" },
  ];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
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
      const afterSequence = Number(url.searchParams.get("after_sequence") ?? 0);
      body = provisionOutput.filter((entry) => entry.sequence > afterSequence);
    }
    await route.fulfill({ json: body });
  });
  return { provisionOutput };
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("unconfigured desktop is usable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockUnconfiguredApi(page);
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
  const { provisionOutput } = await mockInstallingApi(page);
  for (let sequence = 3; sequence <= 40; sequence += 1) {
    provisionOutput.push({
      sequence,
      timestamp: "2026-07-12T00:00:02Z",
      stream: "stdout",
      text: `Installation output ${sequence}`,
    });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect(page.getByText("Downloading version v2026.07.1.0")).toBeVisible();
  await expect(page.getByRole("button", { name: "取消任务" })).toBeVisible();
  const provisioningTerminal = page.locator("#provisioning-output");
  await expect.poll(() => provisioningTerminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
  await provisioningTerminal.evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect(page.getByRole("button", { name: "跳到最后" })).toBeVisible();
  provisionOutput.push({ sequence: 41, timestamp: "2026-07-12T00:00:41Z", stream: "stdout", text: "Installation output after pause" });
  await expect(page.getByText("Installation output after pause")).toBeAttached();
  expect(await provisioningTerminal.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "跳到最后" }).click();
  await expect.poll(() => provisioningTerminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
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
  await mockUnconfiguredApi(page);
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
  const { consoleOutput } = await mockConfiguredApi(page);
  for (let sequence = 4; sequence <= 80; sequence += 1) {
    consoleOutput.push({
      sequence,
      timestamp: "2026-07-12T03:15:03Z",
      stream: "stdout",
      text: `Console output ${sequence}`,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "控制台" }).click();
  await expect(page.getByText("Listening on port 7777")).toBeVisible();
  await expect(page.getByPlaceholder("输入服务端命令")).toBeEnabled();
  const consoleTerminal = page.locator("#server-console-output");
  await expect.poll(() => consoleTerminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
  await consoleTerminal.evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect(page.getByRole("button", { name: "跳到最后" })).toBeVisible();
  consoleOutput.push({ sequence: 81, timestamp: "2026-07-12T03:16:21Z", stream: "stdout", text: "Console output after pause" });
  await page.getByTitle("刷新").click();
  await expect(page.getByText("Console output after pause")).toBeAttached();
  expect(await consoleTerminal.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "跳到最后" }).click();
  await expect.poll(() => consoleTerminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
  consoleOutput.push({ sequence: 82, timestamp: "2026-07-12T03:16:22Z", stream: "stdout", text: "Console output while following" });
  await page.getByTitle("刷新").click();
  await expect(page.getByText("Console output while following")).toBeAttached();
  await expect.poll(() => consoleTerminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
  for (let sequence = 83; sequence <= 1300; sequence += 1) {
    consoleOutput.push({
      sequence,
      timestamp: "2026-07-12T03:17:00Z",
      stream: "stdout",
      text: `Sustained console output ${sequence}`,
    });
  }
  await page.getByTitle("刷新").click();
  await expect(page.getByText("Sustained console output 1300")).toBeAttached();
  await expect(consoleTerminal.locator(".terminal-line")).toHaveCount(500);
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

test("server configuration saves every supported non-world field", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { configValues } = await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "服务器" }).click();

  await page.getByLabel("最大玩家数").fill("24");
  await page.getByRole("spinbutton", { name: "端口", exact: true }).fill("7788");
  await page.getByLabel("密码").fill("server-secret");
  await page.getByLabel("服务器语言").selectOption("zh-Hans");
  await page.getByLabel("欢迎消息").fill("欢迎来到 TerraPanel");
  await page.getByLabel("NPC 同步频率").fill("120");
  await page.getByLabel("进程优先级").selectOption("3");
  await page.getByRole("checkbox", { name: "启用 UPnP 端口转发" }).check();
  await page.getByLabel("封禁列表路径").fill("config/banlist.txt");
  await page.getByLabel("本地模组目录").fill("Mods/Local");
  await page.getByLabel("Mod Pack 名称").fill("CalamityPack");

  const saveRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/server-config") && request.method() === "PATCH",
  );
  await page.getByRole("button", { name: "保存配置" }).click();
  const request = await saveRequest;
  expect(request.postDataJSON()).toEqual({
    maxplayers: 24,
    port: 7788,
    password: "server-secret",
    motd: "欢迎来到 TerraPanel",
    language: "zh-Hans",
    secure: true,
    upnp: true,
    npcstream: 120,
    priority: 3,
    banlist: "config/banlist.txt",
    modpath: "Mods/Local",
    modpack: "CalamityPack",
  });
  expect(configValues).toMatchObject({
    maxplayers: "24",
    port: "7788",
    password: "server-secret",
    language: "zh-Hans",
    secure: "1",
    upnp: "1",
    npcstream: "120",
    priority: "3",
    banlist: "config/banlist.txt",
    modpath: "Mods/Local",
    modpack: "CalamityPack",
  });
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/server-config-desktop.png", fullPage: true });

  await page.getByLabel("密码").fill("");
  await page.getByLabel("服务器语言").selectOption("");
  await page.getByLabel("欢迎消息").fill("");
  await page.getByLabel("NPC 同步频率").fill("");
  await page.getByLabel("封禁列表路径").fill("   ");
  await page.getByLabel("本地模组目录").fill("");
  await page.getByLabel("Mod Pack 名称").fill("");
  const clearRequest = page.waitForRequest(
    (candidate) => candidate.url().endsWith("/api/v1/server-config") && candidate.method() === "PATCH",
  );
  await page.getByRole("button", { name: "保存配置" }).click();
  expect((await clearRequest).postDataJSON()).toMatchObject({
    password: null,
    motd: null,
    language: null,
    npcstream: null,
    banlist: null,
    modpath: null,
    modpack: null,
  });
  for (const key of ["password", "motd", "language", "npcstream", "banlist", "modpath", "modpack"]) {
    expect(configValues).not.toHaveProperty(key);
  }
});

test("server configuration fits mobile", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "服务器" }).click();
  await page.getByLabel("Mod Pack 名称").scrollIntoViewIfNeeded();
  await expect(page.getByLabel("Mod Pack 名称")).toBeVisible();
  await expect(page.getByRole("button", { name: "保存配置" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/server-config-mobile.png", fullPage: true });
});

test("spam check can be diagnosed, disabled, and edited", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "服务器" }).click();

  await expect(page.getByText("近期日志命中 2 次 Projectile spam")).toBeVisible();
  await expect(page.locator(".security-heading .read-mode")).toHaveText("已启用");
  const disableRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/server-config/spam-check/disable") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "明确关闭 SpamCheck" }).click();
  const confirmation = page.getByRole("dialog", { name: "关闭服务端反作弊" });
  await expect(confirmation.getByText("公开服务器不建议长期关闭")).toBeVisible();
  await confirmation.getByRole("button", { name: "明确关闭 SpamCheck" }).click();
  await disableRequest;
  await expect(page.locator(".security-heading .read-mode")).toHaveText("已明确关闭");
  await expect(page.getByRole("checkbox", { name: "启用服务端反作弊" })).not.toBeChecked();

  await page.getByRole("button", { name: "打开配置文件" }).click();
  const editor = page.getByRole("dialog", { name: "编辑文本文件" });
  await expect(editor.getByLabel("文件内容")).toHaveValue(/secure=0/);
  await editor.getByLabel("文件内容").fill("maxplayers=12\nport=7777\nsecure=1\n");
  const saveRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/files/text") && request.method() === "PUT",
  );
  await editor.getByRole("button", { name: "保存文件" }).click();
  await saveRequest;
  await expect(editor).toBeHidden();
  await expect(page.locator(".security-heading .read-mode")).toHaveText("已启用");
  const secureToggle = page.getByRole("checkbox", { name: "启用服务端反作弊" });
  await expect(secureToggle).toBeChecked();
  await expect(secureToggle.locator("xpath=following-sibling::span")).toHaveCSS(
    "background-color",
    "rgb(35, 122, 91)",
  );
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/spam-check-desktop.png", fullPage: true });
});

test("startup file editor is read-only on mobile while running", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "running");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "服务器" }).click();
  await page.getByRole("button", { name: "打开启动脚本" }).click();
  const editor = page.getByRole("dialog", { name: "编辑文本文件" });
  await expect(editor.getByText("运行中只读")).toBeVisible();
  await expect(editor.getByLabel("文件内容")).toBeDisabled();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/startup-editor-mobile.png", fullPage: true });
});

test("scheduled tasks can be created and run", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "任务" }).click();
  await expect(page.locator(".task-row").filter({ hasText: "每小时状态广播" })).toBeVisible();
  await expect(page.getByText("Completed 1 action(s)")).toBeVisible();

  await page.getByRole("button", { name: "新建任务" }).click();
  await page.getByLabel("名称").fill("每两小时备份");
  await page.getByLabel("间隔秒数").fill("7200");
  const createRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/tasks") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "保存任务" }).click();
  await createRequest;
  const createdRow = page.locator(".task-row").filter({ hasText: "每两小时备份" });
  await expect(createdRow).toBeVisible();

  const runRequest = page.waitForRequest(
    (request) => request.url().includes("/api/v1/tasks/") && request.url().endsWith("/run"),
  );
  await createdRow.getByTitle("立即运行").click();
  await runRequest;
  await expect(page.locator(".history-row").filter({ hasText: "每两小时备份" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/tasks-desktop.png", fullPage: true });
});

test("event task editor fits mobile", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockConfiguredApi(page, "stopped");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("主导航").getByRole("button", { name: "任务" }).click();
  await page.getByLabel("任务类型").getByRole("button", { name: "事件任务" }).click();
  await expect(page.getByText("异常退出自动恢复")).toBeVisible();
  await page.getByRole("button", { name: "新建任务" }).click();
  await page.getByLabel("名称").fill("启动后欢迎");
  await page.getByLabel("触发事件").selectOption("server_started");
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/event-task-mobile.png", fullPage: true });
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

test("running server mod switches stay usable while stop is pending", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { controls } = await mockConfiguredApi(page, "running");
  controls.stopDelayMs = 1500;
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/");

  await page.getByRole("button", { name: "停止" }).click();
  const dialog = page.getByRole("dialog");
  const stopResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/instance/stop") && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "停止服务器" }).click();
  await page.getByLabel("主导航").getByRole("button", { name: "模组" }).click();

  await expect(page.getByText("更改将在重启后生效")).toBeVisible();
  const unicodeMod = page.locator(".mod-row").filter({ hasText: "森罗万象" });
  const toggle = unicodeMod.getByRole("checkbox");
  await expect(toggle).toBeEnabled();
  const disableRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/mods/disable") && request.method() === "POST",
  );
  await toggle.uncheck();
  const request = await disableRequest;
  expect(request.postDataJSON()).toEqual({ name: "森罗万象" });
  await expect(toggle).not.toBeChecked();
  await stopResponse;
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/running-mod-switch.png", fullPage: true });
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
  const deleteButton = page.getByTitle("删除存档");
  await expect(deleteButton).toBeEnabled();
  await deleteButton.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "删除存档 TerraPrime" })).toBeVisible();
  await expect(dialog.getByText("删除后不会自动选择或创建其他存档。")).toBeVisible();
  const deletion = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/worlds/TerraPrime") && request.method() === "DELETE",
  );
  await dialog.getByRole("button", { name: "删除存档" }).click();
  await deletion;
  await expect(page.getByText("TerraPrime")).toBeHidden();
  await expect(page.getByRole("button", { name: "启动" })).toBeDisabled();
  await page.getByRole("button", { name: "服务器" }).click();
  await expect(page.getByText("未选择存档")).toBeVisible();
  await expect(page.getByRole("button", { name: "保存配置" })).toBeDisabled();
  await page.getByRole("button", { name: "存档" }).click();
  await page.getByLabel("世界名称").fill("ManualWorld");
  await page.getByLabel("大小").selectOption("2");
  await page.getByLabel("难度").selectOption("1");
  await page.getByLabel("种子").fill("stage53-seed");
  const creation = page.waitForRequest(
    (request) => request.url().endsWith("/api/v1/worlds") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "新建世界" }).click();
  await creation;
  await expect(page.getByText("ManualWorld")).toBeVisible();
  await expect(page.getByText("待创建")).toBeVisible();
  await expect(page.getByRole("button", { name: "启动" })).toBeEnabled();
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
  await expect(page.getByLabel("世界名称")).toBeVisible();
  await expect(page.getByRole("button", { name: "新建世界" })).toBeDisabled();
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
  await expect(page.getByTitle("编辑文本")).toBeVisible();

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
  await expect(page.locator(".file-row").filter({ hasText: "SaveData.zip" }).getByTitle("下载")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/screenshots/files-mobile.png", fullPage: true });
});
