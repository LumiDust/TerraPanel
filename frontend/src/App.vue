<script setup lang="ts">
import {
  ArchiveRestore,
  ArrowDownToLine,
  Boxes,
  CalendarClock,
  Check,
  ChevronRight,
  CircleStop,
  Download,
  File as FileIcon,
  FileArchive,
  FileCog,
  FileText,
  Files,
  Folder,
  FolderPlus,
  FolderOpen,
  Gauge,
  HardDrive,
  PackageOpen,
  Pencil,
  Play,
  RefreshCw,
  Rocket,
  Save,
  Search,
  Send,
  Server,
  SquareTerminal,
  Trash2,
  Upload,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import {
  api,
  type ArchivePreview,
  type BackupInfo,
  type ConsoleEntry,
  type DirectoryListing,
  type FileEntry as ManagedFileEntry,
  type InstanceState,
  type ModInfo,
  type ProvisionRequest,
  type ProvisionSnapshot,
  type WorldCreateRequest,
  type WorldInfo,
} from "./api";
import TaskManager from "./components/TaskManager.vue";

type Tab = "overview" | "console" | "tasks" | "config" | "worlds" | "files" | "mods" | "backups" | "logs";
type ModFilter = "all" | "enabled" | "disabled" | "local" | "workshop";

interface PendingConfirmation {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => Promise<void>;
}

const activeTab = ref<Tab>("overview");
const instance = ref<InstanceState | null>(null);
const worlds = ref<WorldInfo[]>([]);
const mods = ref<ModInfo[]>([]);
const backups = ref<BackupInfo[]>([]);
const consoleEntries = ref<ConsoleEntry[]>([]);
const logLines = ref<string[]>([]);
const provisioning = ref<ProvisionSnapshot | null>(null);
const provisionLogs = ref<ConsoleEntry[]>([]);
const logSource = ref("server");
const busy = ref(false);
const processActionPending = ref(false);
const error = ref("");
const command = ref("");
const instanceName = ref("Primary Server");
const instanceRoot = ref("primary");
const backupLabel = ref("");
const backupQuery = ref("");
const worldFiles = ref<File[]>([]);
const replaceWorld = ref(false);
const newWorldForm = ref<WorldCreateRequest>({
  name: "",
  world_size: 1,
  difficulty: 0,
  seed: null,
});
const worldFileInput = ref<HTMLInputElement | null>(null);
const fileListing = ref<DirectoryListing | null>(null);
const managedFiles = ref<File[]>([]);
const managedFileInput = ref<HTMLInputElement | null>(null);
const replaceManagedFiles = ref(false);
const uploadProgress = ref<number | null>(null);
const newDirectoryName = ref("");
const movingEntry = ref<ManagedFileEntry | null>(null);
const moveDestination = ref("");
const replaceMoveDestination = ref(false);
const archivePreview = ref<ArchivePreview | null>(null);
const archiveDestination = ref("");
const replaceArchiveFiles = ref(false);
const modFile = ref<File | null>(null);
const replaceMod = ref(false);
const modFileInput = ref<HTMLInputElement | null>(null);
const modQuery = ref("");
const modFilter = ref<ModFilter>("all");
const selectedModKey = ref("");
const logQuery = ref("");
const pendingConfirmation = ref<PendingConfirmation | null>(null);
const configForm = ref({ maxplayers: 8, port: 7777, password: "", motd: "" });
const setupForm = ref<ProvisionRequest>({
  name: "Primary Server",
  root_dir: "primary",
  version: null,
  world_name: "TerraPanel",
  world_size: 1,
  difficulty: 1,
  max_players: 8,
  port: 7777,
  password: "",
  motd: "",
  secure: true,
  upnp: false,
  start_after_install: true,
});
const consoleView = ref<HTMLElement | null>(null);
const provisioningView = ref<HTMLElement | null>(null);
const taskManager = ref<InstanceType<typeof TaskManager> | null>(null);
const consoleFollowing = ref(true);
const provisioningFollowing = ref(true);
let timer: number | undefined;
let pollInFlight = false;

const scrollEndThreshold = 48;
const maxConsoleEntries = 500;

const configured = computed(() => instance.value?.configured === true);
const running = computed(() => instance.value?.process.state === "running");
const serverContentLocked = computed(() => {
  const state = instance.value?.process.state;
  return processActionPending.value || (state !== undefined && !["stopped", "failed"].includes(state));
});
const provisioningRunning = computed(() => provisioning.value?.state === "running");
const provisionStages: Array<{ id: string; label: string }> = [
  { id: "preparing", label: "准备" },
  { id: "installing", label: "安装" },
  { id: "associating", label: "关联" },
  { id: "configuring", label: "配置" },
  { id: "starting", label: "启动" },
];
const provisionStageIndex = computed(() =>
  provisionStages.findIndex((stage) => stage.id === provisioning.value?.stage),
);
const statusLabel = computed(() => {
  const state = instance.value?.process.state ?? "stopped";
  return { running: "运行中", starting: "启动中", stopping: "停止中", failed: "异常", stopped: "已停止" }[state];
});
const activeWorld = computed(() => worlds.value.find((world) => world.selected) ?? null);
const enabledMods = computed(() => mods.value.filter((mod) => mod.enabled));
const filteredMods = computed(() => {
  const query = modQuery.value.trim().toLowerCase();
  return mods.value.filter((mod) => {
    const matchesQuery = !query || `${mod.name} ${mod.file}`.toLowerCase().includes(query);
    const matchesFilter = modFilter.value === "all"
      || (modFilter.value === "enabled" && mod.enabled)
      || (modFilter.value === "disabled" && !mod.enabled)
      || mod.source === modFilter.value;
    return matchesQuery && matchesFilter;
  });
});
const selectedMod = computed(() => {
  const selected = mods.value.find((mod) => `${mod.source}:${mod.file}` === selectedModKey.value);
  return selected ?? filteredMods.value[0] ?? null;
});
const filteredBackups = computed(() => {
  const query = backupQuery.value.trim().toLowerCase();
  return query
    ? backups.value.filter((backup) => backup.id.toLowerCase().includes(query))
    : backups.value;
});
const filteredLogLines = computed(() => {
  const query = logQuery.value.trim().toLowerCase();
  return query
    ? logLines.value.filter((line) => line.toLowerCase().includes(query))
    : logLines.value;
});
const recentConsole = computed(() => consoleEntries.value.slice(-6).reverse());
const totalBackupSize = computed(() => backups.value.reduce((total, backup) => total + backup.size, 0));
const fileBreadcrumbs = computed(() => {
  const breadcrumbs: Array<{ label: string; path: string }> = [{ label: "根目录", path: "" }];
  let path = "";
  for (const segment of fileListing.value?.path.split("/").filter(Boolean) ?? []) {
    path = path ? `${path}/${segment}` : segment;
    breadcrumbs.push({ label: segment, path });
  }
  return breadcrumbs;
});

const tabs: Array<{ id: Tab; label: string; icon: typeof Gauge }> = [
  { id: "overview", label: "概览", icon: Gauge },
  { id: "console", label: "控制台", icon: SquareTerminal },
  { id: "tasks", label: "任务", icon: CalendarClock },
  { id: "config", label: "服务器", icon: FileCog },
  { id: "worlds", label: "存档", icon: FolderOpen },
  { id: "files", label: "文件", icon: Files },
  { id: "mods", label: "模组", icon: Boxes },
  { id: "backups", label: "备份", icon: HardDrive },
  { id: "logs", label: "日志", icon: FileText },
];
const activeTabMeta = computed(() => tabs.find((tab) => tab.id === activeTab.value) ?? tabs[0]);

async function perform(action: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason);
  } finally {
    busy.value = false;
  }
}

async function performProcessAction(action: () => Promise<unknown>) {
  processActionPending.value = true;
  error.value = "";
  try {
    await action();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason);
  } finally {
    processActionPending.value = false;
  }
}

function requestConfirmation(value: PendingConfirmation) {
  pendingConfirmation.value = value;
}

async function confirmPendingAction() {
  const pending = pendingConfirmation.value;
  pendingConfirmation.value = null;
  if (pending) await pending.action();
}

async function refreshInstance() {
  instance.value = await api.instance();
}

function applyConfig(values: Record<string, string>) {
  configForm.value = {
    maxplayers: Number(values.maxplayers ?? 8),
    port: Number(values.port ?? 7777),
    password: values.password ?? "",
    motd: values.motd ?? "",
  };
}

async function refreshAll() {
  await refreshInstance();
  if (!configured.value) return;
  const [config, worldList, modList, backupList] = await Promise.all([
    api.config(),
    api.worlds(),
    api.mods(),
    api.backups(),
  ]);
  worlds.value = worldList;
  mods.value = modList;
  backups.value = backupList;
  applyConfig(config.values);
  await refreshConsole();
}

async function refreshProvisioning() {
  provisioning.value = await api.provisioning();
  const last = provisionLogs.value.at(-1)?.sequence ?? 0;
  const entries = await api.provisionLogs(last);
  if (entries.length) {
    const shouldFollow = provisioningFollowing.value;
    provisionLogs.value.push(...entries);
    if (shouldFollow) await scrollProvisioningToEnd();
  }
}

async function refreshConsole() {
  const last = consoleEntries.value.at(-1)?.sequence ?? 0;
  const entries = await api.console(last);
  if (entries.length) {
    const shouldFollow = consoleFollowing.value;
    consoleEntries.value.push(...entries);
    if (consoleEntries.value.length > maxConsoleEntries) {
      consoleEntries.value.splice(0, consoleEntries.value.length - maxConsoleEntries);
    }
    if (shouldFollow) await scrollConsoleToEnd();
  }
}

function isNearScrollEnd(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= scrollEndThreshold;
}

function handleConsoleScroll() {
  if (consoleView.value) consoleFollowing.value = isNearScrollEnd(consoleView.value);
}

function handleProvisioningScroll() {
  if (provisioningView.value) provisioningFollowing.value = isNearScrollEnd(provisioningView.value);
}

async function scrollConsoleToEnd() {
  consoleFollowing.value = true;
  await nextTick();
  const element = consoleView.value;
  if (element) element.scrollTop = element.scrollHeight;
}

async function scrollProvisioningToEnd() {
  provisioningFollowing.value = true;
  await nextTick();
  const element = provisioningView.value;
  if (element) element.scrollTop = element.scrollHeight;
}

async function refreshFiles(path = fileListing.value?.path ?? "") {
  fileListing.value = await api.files(path);
}

async function selectTab(tab: Tab) {
  activeTab.value = tab;
  if (tab === "files" && configured.value) await perform(() => refreshFiles());
  if (tab === "console") await scrollConsoleToEnd();
  if (tab === "overview" && provisioning.value?.state !== "idle") await scrollProvisioningToEnd();
}

function refreshCurrent() {
  if (activeTab.value === "tasks") {
    void perform(async () => taskManager.value?.refresh());
    return;
  }
  void perform(() => activeTab.value === "files" ? refreshFiles() : refreshAll());
}

async function associate() {
  await perform(async () => {
    await api.associate(instanceName.value, instanceRoot.value);
    await refreshAll();
  });
}

async function provisionServer() {
  await perform(async () => {
    provisionLogs.value = [];
    provisioningFollowing.value = true;
    provisioning.value = await api.provision({
      ...setupForm.value,
      version: setupForm.value.version || null,
    });
    await refreshProvisioning();
  });
}

async function cancelProvisioning() {
  await perform(async () => {
    provisioning.value = await api.cancelProvisioning();
    await refreshProvisioning();
  });
}

function updateServer() {
  requestConfirmation({
    title: "更新 tModLoader",
    message: "服务器将更新运行文件和依赖，并在完成后启动。",
    confirmLabel: "开始更新",
    action: () => perform(async () => {
      provisionLogs.value = [];
      provisioningFollowing.value = true;
      provisioning.value = await api.updateServer();
      await selectTab("overview");
    }),
  });
}

async function startServer() {
  await performProcessAction(async () => {
    await api.start();
    await refreshInstance();
    await selectTab("console");
  });
}

function stopServer() {
  requestConfirmation({
    title: "停止服务器",
    message: "在线玩家会断开连接，tModLoader 将保存世界后退出。",
    confirmLabel: "停止服务器",
    danger: true,
    action: () => performProcessAction(async () => {
      await api.stop();
      await refreshInstance();
    }),
  });
}

async function sendCommand() {
  const value = command.value.trim();
  if (!value) return;
  command.value = "";
  await perform(async () => {
    await api.command(value);
    await refreshConsole();
  });
}

async function saveConfig() {
  await perform(() => api.updateConfig(configForm.value));
}

async function createWorld() {
  const name = newWorldForm.value.name.trim();
  if (!name) return;
  await perform(async () => {
    const seed = newWorldForm.value.seed?.trim() || null;
    await api.createWorld({ ...newWorldForm.value, name, seed });
    worlds.value = await api.worlds();
    applyConfig((await api.config()).values);
    newWorldForm.value = { name: "", world_size: 1, difficulty: 0, seed: null };
  });
}

async function selectWorld(path: string) {
  await perform(async () => {
    const config = await api.selectWorld(path);
    applyConfig(config.values);
    worlds.value = await api.worlds();
  });
}

function selectWorldFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  worldFiles.value = Array.from(input.files ?? []);
}

async function uploadWorld() {
  if (!worldFiles.value.length) return;
  await perform(async () => {
    await api.uploadWorld(worldFiles.value, replaceWorld.value);
    worlds.value = await api.worlds();
    worldFiles.value = [];
    replaceWorld.value = false;
    if (worldFileInput.value) worldFileInput.value.value = "";
  });
}

function deleteWorld(world: WorldInfo) {
  requestConfirmation({
    title: `删除存档 ${world.name}`,
    message: !world.exists
      ? "待创建世界的独立配置将被删除，不会生成存档文件。"
      : world.selected
      ? "主世界、模组世界数据、直接备份文件和独立配置将一并删除。删除后不会自动选择或创建其他存档。"
      : "主世界、模组世界数据、直接备份文件和独立配置将一并删除。",
    confirmLabel: "删除存档",
    danger: true,
    action: () => perform(async () => {
      await api.deleteWorld(world.name);
      worlds.value = await api.worlds();
      applyConfig((await api.config()).values);
    }),
  });
}

function managedPath(directory: string, name: string) {
  return directory ? `${directory}/${name}` : name;
}

function selectManagedFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  managedFiles.value = Array.from(input.files ?? []);
}

async function uploadManagedFiles() {
  if (!managedFiles.value.length || !fileListing.value) return;
  const directory = fileListing.value.path;
  const selected = [...managedFiles.value];
  await perform(async () => {
    for (const [index, file] of selected.entries()) {
      await api.uploadFile(
        directory,
        file,
        replaceManagedFiles.value,
        (loaded, total) => {
          const current = total > 0 ? loaded / total : 0;
          uploadProgress.value = Math.round(((index + current) / selected.length) * 100);
        },
      );
    }
    managedFiles.value = [];
    uploadProgress.value = null;
    if (managedFileInput.value) managedFileInput.value.value = "";
    await refreshFiles(directory);
  });
  uploadProgress.value = null;
}

async function createManagedDirectory() {
  const name = newDirectoryName.value.trim();
  if (!name || !fileListing.value) return;
  await perform(async () => {
    await api.createDirectory(managedPath(fileListing.value?.path ?? "", name));
    newDirectoryName.value = "";
    await refreshFiles();
  });
}

async function openManagedDirectory(path: string) {
  await perform(() => refreshFiles(path));
}

function openMoveDialog(entry: ManagedFileEntry) {
  movingEntry.value = entry;
  moveDestination.value = entry.path;
  replaceMoveDestination.value = false;
}

async function moveManagedEntry() {
  const entry = movingEntry.value;
  const destination = moveDestination.value.trim();
  if (!entry || !destination) return;
  await perform(async () => {
    await api.moveFile(entry.path, destination, replaceMoveDestination.value);
    movingEntry.value = null;
    await refreshFiles();
  });
}

function deleteManagedEntry(entry: ManagedFileEntry) {
  requestConfirmation({
    title: `删除${entry.kind === "directory" ? "目录" : "文件"} ${entry.name}`,
    message: entry.kind === "directory"
      ? "目录及其中的全部文件将被永久删除。"
      : "该文件将被永久删除。",
    confirmLabel: "删除",
    danger: true,
    action: () => perform(async () => {
      await api.deleteFile(entry.path, entry.kind === "directory");
      await refreshFiles();
    }),
  });
}

async function inspectManagedArchive(entry: ManagedFileEntry) {
  const destination = fileListing.value?.path ?? "";
  await perform(async () => {
    archiveDestination.value = destination;
    replaceArchiveFiles.value = false;
    archivePreview.value = await api.inspectArchive(entry.path, destination);
  });
}

async function refreshArchivePreview() {
  if (!archivePreview.value) return;
  await perform(async () => {
    archivePreview.value = await api.inspectArchive(
      archivePreview.value?.path ?? "",
      archiveDestination.value.trim(),
    );
  });
}

async function extractManagedArchive() {
  if (!archivePreview.value) return;
  await perform(async () => {
    await api.extractArchive(
      archivePreview.value?.path ?? "",
      archiveDestination.value.trim(),
      replaceArchiveFiles.value,
    );
    archivePreview.value = null;
    await Promise.all([
      refreshFiles(),
      api.mods().then((values) => { mods.value = values; }),
      api.worlds().then((values) => { worlds.value = values; }),
    ]);
  });
}

async function toggleMod(mod: ModInfo) {
  await perform(async () => {
    await api.toggleMod(mod.name, !mod.enabled);
    mods.value = await api.mods();
  });
}

function deleteMod(mod: ModInfo) {
  if (mod.source !== "local") return;
  requestConfirmation({
    title: `删除模组 ${mod.name}`,
    message: "本地 .tmod 文件将被删除，并从启用列表移除。",
    confirmLabel: "删除模组",
    danger: true,
    action: () => perform(async () => {
      await api.deleteLocalMod(mod.name);
      mods.value = await api.mods();
      selectedModKey.value = "";
    }),
  });
}

function selectModFile(event: Event) {
  const input = event.target as HTMLInputElement;
  modFile.value = input.files?.[0] ?? null;
}

async function uploadMod() {
  if (!modFile.value) return;
  await perform(async () => {
    await api.uploadMod(modFile.value as File, replaceMod.value);
    mods.value = await api.mods();
    modFile.value = null;
    replaceMod.value = false;
    if (modFileInput.value) modFileInput.value.value = "";
  });
}

async function createBackup() {
  await perform(async () => {
    await api.createBackup(backupLabel.value);
    backupLabel.value = "";
    backups.value = await api.backups();
  });
}

function restoreBackup(backup: BackupInfo) {
  requestConfirmation({
    title: "恢复备份",
    message: `${backup.id} 将替换当前世界和备份中包含的配置。`,
    confirmLabel: "恢复备份",
    danger: true,
    action: () => perform(async () => {
      await api.restoreBackup(backup.id);
      await refreshAll();
    }),
  });
}

function deleteBackup(backup: BackupInfo) {
  requestConfirmation({
    title: "删除备份",
    message: `${backup.id}.zip 将被永久删除。`,
    confirmLabel: "删除备份",
    danger: true,
    action: () => perform(async () => {
      await api.deleteBackup(backup.id);
      backups.value = await api.backups();
    }),
  });
}

async function refreshLog() {
  await perform(async () => {
    const log = await api.log(logSource.value);
    logLines.value = log.lines;
  });
}

function downloadLog() {
  if (!logLines.value.length) return;
  const blob = new Blob([`${logLines.value.join("\n")}\n`], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${logSource.value}.log`;
  link.click();
  URL.revokeObjectURL(url);
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

async function pollServer() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const previousState = provisioning.value?.state;
    const wasConfigured = configured.value;
    await refreshProvisioning();
    await refreshInstance();
    if (configured.value) {
      if (!wasConfigured || (previousState === "running" && provisioning.value?.state === "succeeded")) {
        await refreshAll();
      } else {
        await refreshConsole();
      }
    }
  } catch {
    // The next explicit action will surface connection failures.
  } finally {
    pollInFlight = false;
  }
}

onMounted(async () => {
  await perform(async () => {
    await Promise.all([refreshAll(), refreshProvisioning()]);
  });
  timer = window.setInterval(() => void pollServer(), 1500);
});

onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><Server :size="21" /><span>TerraPanel</span></div>
      <nav class="tabs" aria-label="主导航">
        <button v-for="tab in tabs" :key="tab.id" :class="{ active: activeTab === tab.id }" @click="selectTab(tab.id)">
          <component :is="tab.icon" :size="18" /><span>{{ tab.label }}</span>
        </button>
      </nav>
      <div class="sidebar-status">
        <span class="status-dot" :class="instance?.process.state"></span>
        <div><strong>{{ statusLabel }}</strong><small>{{ instance?.instance?.name ?? "未关联" }}</small></div>
      </div>
    </aside>

    <main>
      <header class="topbar">
        <div><h1>{{ activeTabMeta.label }}</h1><p>{{ instance?.instance?.root_dir ?? "单实例管理" }}</p></div>
        <div class="actions">
          <button class="icon-button" title="刷新" :disabled="busy" @click="refreshCurrent"><RefreshCw :size="18" /></button>
          <button v-if="configured && !running" class="icon-button" title="更新 tModLoader" :disabled="busy || provisioningRunning || processActionPending" @click="updateServer"><Download :size="18" /></button>
          <button v-if="configured && !running" class="primary" :disabled="!activeWorld || busy || processActionPending" @click="startServer"><Play :size="17" />启动</button>
          <button v-if="configured && running" class="danger" :disabled="busy || processActionPending" @click="stopServer"><CircleStop :size="17" />停止</button>
        </div>
      </header>

      <div v-if="error" class="error-banner">{{ error }}<button title="关闭" @click="error = ''">×</button></div>

      <section v-if="!configured && activeTab === 'overview'" class="setup-panel">
        <div class="section-heading"><Rocket :size="20" /><div><h2>新建服务器</h2><p>tModLoader Dedicated Server</p></div></div>

        <form class="setup-form" @submit.prevent="provisionServer">
          <fieldset :disabled="busy || provisioningRunning">
            <div class="setup-grid">
              <label>名称<input v-model="setupForm.name" required maxlength="80" /></label>
              <label>实例目录<input v-model="setupForm.root_dir" required maxlength="240" /></label>
              <label>tModLoader 版本<input v-model="setupForm.version" pattern="v[0-9]+(\.[0-9]+){2,3}" placeholder="最新稳定版" /></label>
              <label>世界名称<input v-model="setupForm.world_name" required maxlength="120" /></label>
              <label>世界大小<select v-model.number="setupForm.world_size"><option :value="1">小</option><option :value="2">中</option><option :value="3">大</option></select></label>
              <label>难度<select v-model.number="setupForm.difficulty"><option :value="0">经典</option><option :value="1">专家</option><option :value="2">大师</option><option :value="3">旅行</option></select></label>
              <label>最大玩家数<input v-model.number="setupForm.max_players" type="number" min="1" max="255" /></label>
              <label>端口<input v-model.number="setupForm.port" type="number" min="1" max="65535" /></label>
              <label>密码<input v-model="setupForm.password" type="password" maxlength="128" /></label>
              <label>欢迎消息<input v-model="setupForm.motd" maxlength="500" /></label>
            </div>
            <label class="check-row"><input v-model="setupForm.start_after_install" type="checkbox" />安装完成后启动</label>
            <button class="primary setup-submit"><Rocket :size="17" />安装并开服</button>
          </fieldset>
        </form>

        <div v-if="provisioning && provisioning.state !== 'idle'" class="provision-status">
          <div class="progress-strip" :data-state="provisioning.state">
            <div v-for="(stage, index) in provisionStages" :key="stage.id" :class="{ active: index <= provisionStageIndex, current: stage.id === provisioning.stage }"><span>{{ index + 1 }}</span><small>{{ stage.label }}</small></div>
          </div>
          <div v-if="provisioning.error" class="provision-error">{{ provisioning.error }}</div>
          <div class="terminal-shell">
            <div id="provisioning-output" ref="provisioningView" class="setup-terminal" aria-live="polite" @scroll="handleProvisioningScroll">
              <div v-if="!provisionLogs.length" class="terminal-empty">等待安装输出</div>
              <div v-for="entry in provisionLogs" :key="entry.sequence" class="terminal-line"><time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span></div>
            </div>
            <button v-if="!provisioningFollowing && provisionLogs.length" type="button" class="icon-button terminal-jump" title="跳到最后" aria-label="跳到最后" aria-controls="provisioning-output" @click="scrollProvisioningToEnd"><ArrowDownToLine :size="18" /></button>
          </div>
          <button v-if="provisioningRunning" class="secondary cancel-task" :disabled="busy" @click="cancelProvisioning"><X :size="17" />取消任务</button>
        </div>

        <details class="advanced-association">
          <summary>关联已有安装</summary>
          <form @submit.prevent="associate">
            <label>名称<input v-model="instanceName" required maxlength="80" /></label>
            <label>实例目录<input v-model="instanceRoot" required /></label>
            <button class="secondary" :disabled="busy || provisioningRunning"><FolderOpen :size="17" />关联</button>
          </form>
        </details>
      </section>

      <section v-else-if="!configured" class="panel unavailable-panel">
        <component :is="activeTabMeta.icon" :size="26" />
        <div>
          <h2>{{ activeTabMeta.label }}尚未就绪</h2>
          <p>{{ provisioningRunning ? "服务器正在安装，任务会继续在后台运行。" : "请先完成服务器安装或关联已有安装。" }}</p>
        </div>
        <button class="secondary" @click="selectTab('overview')"><Rocket :size="17" />查看安装进度</button>
      </section>

      <template v-else>
        <section v-if="activeTab === 'overview'" class="overview-grid">
          <article class="metric"><span>进程状态</span><strong>{{ statusLabel }}</strong><small>PID {{ instance?.process.pid ?? "—" }}</small></article>
          <article class="metric"><span>世界存档</span><strong>{{ worlds.length }}</strong><small>{{ worlds.filter((world) => world.has_mod_data).length }} 个含模组数据</small></article>
          <article class="metric"><span>启用模组</span><strong>{{ enabledMods.length }}</strong><small>共发现 {{ mods.length }} 个</small></article>
          <article class="metric"><span>备份</span><strong>{{ backups.length }}</strong><small>{{ backups[0] ? new Date(backups[0].created_at).toLocaleString() : "暂无备份" }}</small></article>
          <div v-if="provisioning?.operation === 'update' && provisioning.state !== 'idle'" class="panel wide">
            <div class="section-heading"><Download :size="20" /><div><h2>tModLoader 更新</h2><p>{{ provisioning.state === 'running' ? '进行中' : provisioning.state === 'succeeded' ? '已完成' : '未完成' }}</p></div></div>
            <div class="progress-strip" :data-state="provisioning.state">
              <div v-for="(stage, index) in provisionStages" :key="stage.id" :class="{ active: index <= provisionStageIndex, current: stage.id === provisioning.stage }"><span>{{ index + 1 }}</span><small>{{ stage.label }}</small></div>
            </div>
            <div v-if="provisioning.error" class="provision-error">{{ provisioning.error }}</div>
            <div class="terminal-shell">
              <div id="provisioning-output" ref="provisioningView" class="setup-terminal" aria-live="polite" @scroll="handleProvisioningScroll">
                <div v-if="!provisionLogs.length" class="terminal-empty">等待更新输出</div>
                <div v-for="entry in provisionLogs" :key="entry.sequence" class="terminal-line"><time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span></div>
              </div>
              <button v-if="!provisioningFollowing && provisionLogs.length" type="button" class="icon-button terminal-jump" title="跳到最后" aria-label="跳到最后" aria-controls="provisioning-output" @click="scrollProvisioningToEnd"><ArrowDownToLine :size="18" /></button>
            </div>
            <button v-if="provisioningRunning" class="secondary cancel-task" :disabled="busy" @click="cancelProvisioning"><X :size="17" />取消任务</button>
          </div>
          <div class="operations-grid wide">
            <section class="panel server-summary">
              <div class="section-heading"><Server :size="20" /><div><h2>{{ instance?.instance?.name }}</h2><p>{{ instance?.instance?.install_dir }}</p></div></div>
              <div class="quick-actions">
                <button class="secondary" @click="selectTab('console')"><SquareTerminal :size="16" />控制台</button>
                <button class="secondary" :disabled="serverContentLocked || busy" @click="createBackup"><Save :size="16" />立即备份</button>
                <button class="secondary" @click="activeTab = 'logs'; refreshLog()"><FileText :size="16" />查看日志</button>
              </div>
              <dl>
                <dt>当前世界</dt><dd>{{ activeWorld?.name ?? "未选择" }}</dd>
                <dt>模组</dt><dd>{{ enabledMods.length }} 启用 / {{ mods.length }} 已安装</dd>
                <dt>配置文件</dt><dd>{{ activeWorld ? `WorldConfigs/${activeWorld.name}.txt` : "未选择" }}</dd>
                <dt>退出码</dt><dd>{{ instance?.process.exit_code ?? "—" }}</dd>
              </dl>
            </section>
            <section class="panel activity-panel">
              <div class="section-heading"><SquareTerminal :size="20" /><div><h2>近期活动</h2><p>服务端控制台</p></div></div>
              <div class="activity-list">
                <button v-for="entry in recentConsole" :key="entry.sequence" @click="selectTab('console')">
                  <time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span>
                </button>
                <div v-if="!recentConsole.length" class="empty">暂无控制台活动</div>
              </div>
            </section>
          </div>
        </section>

        <section v-if="activeTab === 'console'" class="console-panel">
          <div class="terminal-shell">
            <div id="server-console-output" ref="consoleView" class="terminal" aria-live="polite" @scroll="handleConsoleScroll">
              <div v-if="!consoleEntries.length" class="terminal-empty">等待服务端输出</div>
              <div v-for="entry in consoleEntries" :key="entry.sequence" :class="['terminal-line', entry.stream]">
                <time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span>
              </div>
            </div>
            <button v-if="!consoleFollowing && consoleEntries.length" type="button" class="icon-button terminal-jump" title="跳到最后" aria-label="跳到最后" aria-controls="server-console-output" @click="scrollConsoleToEnd"><ArrowDownToLine :size="18" /></button>
          </div>
          <form class="command-bar" @submit.prevent="sendCommand">
            <span>›</span><input v-model="command" :disabled="!running" autocomplete="off" placeholder="输入服务端命令" />
            <button class="icon-button" title="发送" :disabled="!running || busy"><Send :size="18" /></button>
          </form>
        </section>

        <TaskManager v-if="activeTab === 'tasks'" ref="taskManager" @error="error = $event" />

        <section v-if="activeTab === 'config'" class="panel">
            <div class="section-heading"><FileCog :size="20" /><div><h2>服务器配置</h2><p>{{ activeWorld ? `${activeWorld.name} · 独立配置` : "未选择存档" }}</p></div></div>
            <form class="form-grid" @submit.prevent="saveConfig">
              <label>最大玩家数<input v-model.number="configForm.maxplayers" type="number" min="1" max="255" :disabled="!activeWorld || serverContentLocked || busy" /></label>
              <label>端口<input v-model.number="configForm.port" type="number" min="1" max="65535" :disabled="!activeWorld || serverContentLocked || busy" /></label>
              <label class="full">密码<input v-model="configForm.password" type="password" :disabled="!activeWorld || serverContentLocked || busy" /></label>
              <label class="full">欢迎消息<input v-model="configForm.motd" :disabled="!activeWorld || serverContentLocked || busy" /></label>
              <button class="primary" :disabled="!activeWorld || serverContentLocked || busy"><Save :size="17" />保存配置</button>
            </form>
        </section>

        <section v-if="activeTab === 'worlds'" class="panel">
          <div class="section-heading"><FolderOpen :size="20" /><div><h2>服务器存档</h2><p>{{ worlds.length }} 个世界</p></div></div>
          <form class="world-create-form" @submit.prevent="createWorld">
            <label>世界名称<input v-model="newWorldForm.name" required maxlength="120" :disabled="serverContentLocked || busy" /></label>
            <label>大小<select v-model.number="newWorldForm.world_size" :disabled="serverContentLocked || busy"><option :value="1">小</option><option :value="2">中</option><option :value="3">大</option></select></label>
            <label>难度<select v-model.number="newWorldForm.difficulty" :disabled="serverContentLocked || busy"><option :value="0">经典</option><option :value="1">专家</option><option :value="2">大师</option><option :value="3">旅行</option></select></label>
            <label>种子<input v-model="newWorldForm.seed" maxlength="200" placeholder="随机" :disabled="serverContentLocked || busy" /></label>
            <button class="primary" :disabled="!newWorldForm.name.trim() || serverContentLocked || busy"><FolderPlus :size="17" />新建世界</button>
          </form>
          <form class="asset-upload" @submit.prevent="uploadWorld">
            <label class="file-picker">
              <input ref="worldFileInput" type="file" accept=".wld,.twld" multiple :disabled="serverContentLocked || busy" @change="selectWorldFiles" />
              <span>{{ worldFiles.length ? worldFiles.map((file) => file.name).join(', ') : "选择 .wld / .twld" }}</span>
            </label>
            <label class="check-row"><input v-model="replaceWorld" type="checkbox" :disabled="serverContentLocked || busy" />覆盖同名</label>
            <button class="primary" :disabled="!worldFiles.some((file) => file.name.toLowerCase().endsWith('.wld')) || serverContentLocked || busy"><Upload :size="17" />导入</button>
          </form>
          <div class="table-list">
            <div v-for="world in worlds" :key="world.path" class="table-row">
              <span><strong>{{ world.name }}</strong><small>{{ world.exists ? `${formatBytes(world.size)} · ${world.has_mod_data ? "Mod" : "Vanilla"}` : "等待首次启动创建" }}</small></span>
              <div class="row-actions">
                <span v-if="!world.exists" class="tag pending">待创建</span>
                <span v-if="world.selected" class="tag">当前</span>
                <button class="icon-button" title="设为当前" :disabled="world.selected || serverContentLocked || busy" @click="selectWorld(world.path)"><Check :size="17" /></button>
                <button class="icon-button danger-icon" title="删除存档" :disabled="serverContentLocked || busy" @click="deleteWorld(world)"><Trash2 :size="17" /></button>
              </div>
            </div>
            <div v-if="!worlds.length" class="empty">未发现世界存档</div>
          </div>
        </section>

        <section v-if="activeTab === 'files'" class="panel file-manager">
          <div class="file-manager-header">
            <nav class="breadcrumbs" aria-label="文件路径">
              <template v-for="(crumb, index) in fileBreadcrumbs" :key="crumb.path">
                <ChevronRight v-if="index" :size="14" />
                <button :class="{ current: index === fileBreadcrumbs.length - 1 }" @click="openManagedDirectory(crumb.path)">{{ crumb.label }}</button>
              </template>
            </nav>
            <span class="read-mode" :class="{ locked: serverContentLocked }">{{ serverContentLocked ? "运行中只读" : "可修改" }}</span>
          </div>

          <div class="file-actions-bar">
            <form class="directory-form" @submit.prevent="createManagedDirectory">
              <input v-model="newDirectoryName" :disabled="serverContentLocked || busy" maxlength="255" placeholder="新目录名称" />
              <button class="secondary" :disabled="!newDirectoryName.trim() || serverContentLocked || busy"><FolderPlus :size="17" />新建</button>
            </form>
            <form class="file-upload-form" @submit.prevent="uploadManagedFiles">
              <label class="file-picker">
                <input ref="managedFileInput" type="file" multiple :disabled="serverContentLocked || busy" @change="selectManagedFiles" />
                <span>{{ managedFiles.length ? managedFiles.map((file) => file.name).join(', ') : "选择文件或 ZIP 整合包" }}</span>
              </label>
              <label class="check-row"><input v-model="replaceManagedFiles" type="checkbox" :disabled="serverContentLocked || busy" />覆盖同名</label>
              <button class="primary" :disabled="!managedFiles.length || serverContentLocked || busy"><Upload :size="17" />上传</button>
            </form>
          </div>

          <div v-if="uploadProgress !== null" class="upload-progress" aria-live="polite">
            <span :style="{ width: `${uploadProgress}%` }"></span><strong>{{ uploadProgress }}%</strong>
          </div>

          <div class="file-list" role="table" aria-label="服务器文件">
            <div class="file-row file-heading" role="row"><span>名称</span><span>大小</span><span>修改时间</span><span>操作</span></div>
            <div v-if="fileListing?.parent !== null" class="file-row" role="row">
              <button class="file-name" @click="openManagedDirectory(fileListing?.parent ?? '')"><Folder :size="19" /><span><strong>..</strong><small>上级目录</small></span></button>
              <span>—</span><span>—</span><span></span>
            </div>
            <div v-for="entry in fileListing?.entries ?? []" :key="entry.path" class="file-row" role="row">
              <button v-if="entry.kind === 'directory'" class="file-name" @click="openManagedDirectory(entry.path)"><Folder :size="19" /><span><strong>{{ entry.name }}</strong><small>目录</small></span></button>
              <span v-else class="file-name"><FileArchive v-if="entry.archive" :size="19" /><FileIcon v-else :size="19" /><span><strong>{{ entry.name }}</strong><small>{{ entry.kind === 'file' ? '文件' : '不支持的类型' }}</small></span></span>
              <span class="file-size">{{ entry.size === null ? "—" : formatBytes(entry.size) }}</span>
              <time>{{ new Date(entry.modified_at).toLocaleString() }}</time>
              <div class="row-actions">
                <button v-if="entry.archive" class="icon-button" title="查看并解压" :disabled="serverContentLocked || busy" @click="inspectManagedArchive(entry)"><ArchiveRestore :size="17" /></button>
                <a v-if="entry.kind === 'file'" class="icon-button" title="下载" :href="api.fileDownloadUrl(entry.path)" download><Download :size="17" /></a>
                <button class="icon-button" title="移动或重命名" :disabled="entry.kind === 'symlink' || entry.kind === 'other' || serverContentLocked || busy" @click="openMoveDialog(entry)"><Pencil :size="17" /></button>
                <button class="icon-button danger-icon" title="删除" :disabled="serverContentLocked || busy" @click="deleteManagedEntry(entry)"><Trash2 :size="17" /></button>
              </div>
            </div>
            <div v-if="fileListing && !fileListing.entries.length" class="empty">此目录为空</div>
            <div v-if="!fileListing" class="empty">正在读取目录</div>
          </div>
        </section>

        <section v-if="activeTab === 'mods'" class="panel management-panel">
          <div class="section-heading"><Boxes :size="20" /><div><h2>模组管理</h2><p>{{ enabledMods.length }} 启用 · {{ mods.filter((mod) => mod.source === 'local').length }} 本地 · {{ mods.filter((mod) => mod.source === 'workshop').length }} Workshop</p></div><span v-if="serverContentLocked" class="read-mode locked">更改将在重启后生效</span></div>
          <form class="asset-upload" @submit.prevent="uploadMod">
            <label class="file-picker">
              <input ref="modFileInput" type="file" accept=".tmod" :disabled="serverContentLocked || busy" @change="selectModFile" />
              <span>{{ modFile?.name ?? "选择 .tmod" }}</span>
            </label>
            <label class="check-row"><input v-model="replaceMod" type="checkbox" :disabled="serverContentLocked || busy" />覆盖同名</label>
            <button class="primary" :disabled="!modFile || serverContentLocked || busy"><Upload :size="17" />上传</button>
          </form>
          <div class="management-toolbar">
            <label class="search-field"><Search :size="16" /><input v-model="modQuery" placeholder="搜索模组" /></label>
            <div class="segmented compact" aria-label="模组筛选">
              <button v-for="filter in [{ id: 'all', label: '全部' }, { id: 'enabled', label: '启用' }, { id: 'disabled', label: '停用' }, { id: 'local', label: '本地' }, { id: 'workshop', label: 'Workshop' }]" :key="filter.id" :class="{ active: modFilter === filter.id }" @click="modFilter = filter.id as ModFilter">{{ filter.label }}</button>
            </div>
          </div>
          <div class="mod-workspace">
            <div class="mod-list" aria-label="模组列表">
              <div v-for="mod in filteredMods" :key="`${mod.source}-${mod.file}`" :class="['mod-row', { selected: selectedMod?.file === mod.file && selectedMod?.source === mod.source }]">
                <button class="mod-main" @click="selectedModKey = `${mod.source}:${mod.file}`">
                  <span class="mod-mark"><PackageOpen :size="18" /></span>
                  <span><strong>{{ mod.name }}</strong><small>{{ mod.source === 'local' ? '本地文件' : 'Workshop' }} · {{ formatBytes(mod.size) }}</small></span>
                </button>
                <label class="switch" :title="`${mod.enabled ? '停用模组' : '启用模组'}${serverContentLocked ? '（重启后生效）' : ''}`"><input type="checkbox" :checked="mod.enabled" :disabled="busy" @change="toggleMod(mod)" /><span></span></label>
              </div>
              <div v-if="!filteredMods.length" class="empty">没有匹配的模组</div>
            </div>
            <aside v-if="selectedMod" class="mod-detail">
              <div class="detail-title"><span class="mod-mark large"><PackageOpen :size="24" /></span><div><h3>{{ selectedMod.name }}</h3><span class="tag">{{ selectedMod.enabled ? "已启用" : "已停用" }}</span></div></div>
              <dl><dt>来源</dt><dd>{{ selectedMod.source === "local" ? "本地上传" : "Steam Workshop" }}</dd><dt>大小</dt><dd>{{ formatBytes(selectedMod.size) }}</dd><dt>文件</dt><dd>{{ selectedMod.file }}</dd></dl>
              <div class="detail-actions">
                <button class="secondary" :disabled="busy" @click="toggleMod(selectedMod)">{{ selectedMod.enabled ? "停用" : "启用" }}</button>
                <button v-if="selectedMod.source === 'local'" class="danger" :disabled="busy || serverContentLocked" @click="deleteMod(selectedMod)"><Trash2 :size="16" />删除</button>
              </div>
            </aside>
          </div>
        </section>

        <section v-if="activeTab === 'backups'" class="panel management-panel">
          <div class="section-heading"><HardDrive :size="20" /><div><h2>存档备份</h2><p>{{ backups.length }} 个归档 · {{ formatBytes(totalBackupSize) }}</p></div></div>
          <div class="backup-toolbar">
            <label class="search-field"><Search :size="16" /><input v-model="backupQuery" placeholder="搜索备份" /></label>
            <form class="inline-form" @submit.prevent="createBackup"><input v-model="backupLabel" pattern="[A-Za-z0-9_.-]+" placeholder="标签（可选）" /><button class="primary" :disabled="serverContentLocked"><Save :size="17" />创建备份</button></form>
          </div>
          <div class="table-list">
            <div v-for="backup in filteredBackups" :key="backup.id" class="table-row"><span><strong>{{ backup.id }}</strong><small>{{ new Date(backup.created_at).toLocaleString() }} · {{ formatBytes(backup.size) }} · {{ backup.world_files }} 个世界</small></span><div class="row-actions"><a class="icon-button" title="下载备份" :href="api.backupDownloadUrl(backup.id)" download><Download :size="18" /></a><button class="icon-button" title="恢复备份" :disabled="serverContentLocked" @click="restoreBackup(backup)"><ArchiveRestore :size="18" /></button><button class="icon-button danger-icon" title="删除备份" @click="deleteBackup(backup)"><Trash2 :size="18" /></button></div></div>
            <div v-if="!filteredBackups.length" class="empty">没有匹配的备份</div>
          </div>
        </section>

        <section v-if="activeTab === 'logs'" class="logs-panel">
          <div class="log-toolbar"><div class="segmented"><button v-for="source in ['server', 'console', 'launch', 'native']" :key="source" :class="{ active: logSource === source }" @click="logSource = source; refreshLog()">{{ source }}</button></div><div class="log-tools"><label class="search-field dark"><Search :size="16" /><input v-model="logQuery" placeholder="筛选日志" /></label><button class="icon-button" title="下载日志" :disabled="!logLines.length" @click="downloadLog"><Download :size="18" /></button><button class="icon-button" title="刷新日志" @click="refreshLog"><RefreshCw :size="18" /></button></div></div>
          <pre>{{ filteredLogLines.join('\n') || '暂无日志' }}</pre>
        </section>
      </template>
    </main>

    <div v-if="pendingConfirmation" class="modal-backdrop" role="presentation" @click.self="pendingConfirmation = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" :aria-labelledby="'confirm-title'">
        <div><h2 id="confirm-title">{{ pendingConfirmation.title }}</h2><p>{{ pendingConfirmation.message }}</p></div>
        <div class="dialog-actions"><button class="secondary" @click="pendingConfirmation = null">取消</button><button :class="pendingConfirmation.danger ? 'danger' : 'primary'" :disabled="busy" @click="confirmPendingAction">{{ pendingConfirmation.confirmLabel }}</button></div>
      </section>
    </div>

    <div v-if="movingEntry" class="modal-backdrop" role="presentation" @click.self="movingEntry = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="move-title">
        <div><h2 id="move-title">移动或重命名</h2><p>{{ movingEntry.path }}</p></div>
        <label class="dialog-field">目标路径<input v-model="moveDestination" maxlength="1024" /></label>
        <label class="check-row"><input v-model="replaceMoveDestination" type="checkbox" />覆盖同名文件</label>
        <div class="dialog-actions"><button class="secondary" @click="movingEntry = null">取消</button><button class="primary" :disabled="busy || serverContentLocked || !moveDestination.trim()" @click="moveManagedEntry">保存</button></div>
      </section>
    </div>

    <div v-if="archivePreview" class="modal-backdrop" role="presentation" @click.self="archivePreview = null">
      <section class="confirm-dialog archive-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-title">
        <div><h2 id="archive-title">解压 {{ archivePreview.path }}</h2><p>{{ archivePreview.files }} 个文件 · {{ formatBytes(archivePreview.expanded_size) }} 解压后大小</p></div>
        <dl class="archive-summary"><dt>顶层目录</dt><dd>{{ archivePreview.top_level.join(', ') || '无' }}</dd><dt>已有冲突</dt><dd>{{ archivePreview.conflicts.length }}</dd></dl>
        <label class="dialog-field">目标目录（实例根留空）<input v-model="archiveDestination" maxlength="1024" placeholder="根目录" @change="refreshArchivePreview" /></label>
        <label class="check-row"><input v-model="replaceArchiveFiles" type="checkbox" :disabled="!archivePreview.conflicts.length" />覆盖已有文件</label>
        <div class="dialog-actions"><button class="secondary" @click="archivePreview = null">取消</button><button class="primary" :disabled="busy || serverContentLocked || (archivePreview.conflicts.length > 0 && !replaceArchiveFiles)" @click="extractManagedArchive"><ArchiveRestore :size="17" />解压</button></div>
      </section>
    </div>
  </div>
</template>
