<script setup lang="ts">
import {
  ArchiveRestore,
  Boxes,
  CircleStop,
  Download,
  FileCog,
  FileText,
  FolderOpen,
  Gauge,
  HardDrive,
  Play,
  RefreshCw,
  Rocket,
  Save,
  Send,
  Server,
  SquareTerminal,
  Upload,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import {
  api,
  type BackupInfo,
  type ConsoleEntry,
  type InstanceState,
  type ModInfo,
  type ProvisionRequest,
  type ProvisionSnapshot,
  type WorldInfo,
} from "./api";

type Tab = "overview" | "console" | "config" | "mods" | "backups" | "logs";

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
const error = ref("");
const command = ref("");
const instanceName = ref("Primary Server");
const instanceRoot = ref("primary");
const backupLabel = ref("");
const modFile = ref<File | null>(null);
const replaceMod = ref(false);
const modFileInput = ref<HTMLInputElement | null>(null);
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
let timer: number | undefined;

const configured = computed(() => instance.value?.configured === true);
const running = computed(() => instance.value?.process.state === "running");
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

const tabs: Array<{ id: Tab; label: string; icon: typeof Gauge }> = [
  { id: "overview", label: "概览", icon: Gauge },
  { id: "console", label: "控制台", icon: SquareTerminal },
  { id: "config", label: "服务器", icon: FileCog },
  { id: "mods", label: "模组", icon: Boxes },
  { id: "backups", label: "备份", icon: HardDrive },
  { id: "logs", label: "日志", icon: FileText },
];

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

async function refreshInstance() {
  instance.value = await api.instance();
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
  configForm.value = {
    maxplayers: Number(config.values.maxplayers ?? 8),
    port: Number(config.values.port ?? 7777),
    password: config.values.password ?? "",
    motd: config.values.motd ?? "",
  };
  await refreshConsole();
}

async function refreshProvisioning() {
  provisioning.value = await api.provisioning();
  const last = provisionLogs.value.at(-1)?.sequence ?? 0;
  const entries = await api.provisionLogs(last);
  if (entries.length) provisionLogs.value.push(...entries);
}

async function refreshConsole() {
  const last = consoleEntries.value.at(-1)?.sequence ?? 0;
  const entries = await api.console(last);
  if (entries.length) {
    consoleEntries.value.push(...entries);
    await nextTick();
    consoleView.value?.scrollTo({ top: consoleView.value.scrollHeight });
  }
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

async function updateServer() {
  if (!window.confirm("更新 tModLoader 和运行依赖，完成后启动服务器？")) return;
  await perform(async () => {
    provisionLogs.value = [];
    provisioning.value = await api.updateServer();
    activeTab.value = "overview";
  });
}

async function startServer() {
  await perform(async () => {
    await api.start();
    await refreshInstance();
    activeTab.value = "console";
  });
}

async function stopServer() {
  await perform(async () => {
    await api.stop();
    await refreshInstance();
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

async function selectWorld(path: string) {
  await perform(() => api.selectWorld(path));
}

async function toggleMod(mod: ModInfo) {
  await perform(async () => {
    await api.toggleMod(mod.name, !mod.enabled);
    mods.value = await api.mods();
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

async function restoreBackup(backup: BackupInfo) {
  if (!window.confirm(`恢复备份 ${backup.id}？`)) return;
  await perform(async () => {
    await api.restoreBackup(backup.id);
    await refreshAll();
  });
}

async function refreshLog() {
  await perform(async () => {
    const log = await api.log(logSource.value);
    logLines.value = log.lines;
  });
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

onMounted(async () => {
  await perform(async () => {
    await Promise.all([refreshAll(), refreshProvisioning()]);
  });
  timer = window.setInterval(async () => {
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
    }
  }, 1500);
});

onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><Server :size="21" /><span>TerraPanel</span></div>
      <nav class="tabs" aria-label="主导航">
        <button v-for="tab in tabs" :key="tab.id" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
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
        <div><h1>{{ tabs.find((tab) => tab.id === activeTab)?.label }}</h1><p>{{ instance?.instance?.root_dir ?? "单实例管理" }}</p></div>
        <div class="actions">
          <button class="icon-button" title="刷新" :disabled="busy" @click="perform(refreshAll)"><RefreshCw :size="18" /></button>
          <button v-if="configured && !running" class="icon-button" title="更新 tModLoader" :disabled="busy || provisioningRunning" @click="updateServer"><Download :size="18" /></button>
          <button v-if="configured && !running" class="primary" :disabled="busy" @click="startServer"><Play :size="17" />启动</button>
          <button v-if="configured && running" class="danger" :disabled="busy" @click="stopServer"><CircleStop :size="17" />停止</button>
        </div>
      </header>

      <div v-if="error" class="error-banner">{{ error }}<button title="关闭" @click="error = ''">×</button></div>

      <section v-if="!configured" class="setup-panel">
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
          <div class="setup-terminal" aria-live="polite">
            <div v-if="!provisionLogs.length" class="terminal-empty">等待安装输出</div>
            <div v-for="entry in provisionLogs" :key="entry.sequence" class="terminal-line"><time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span></div>
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

      <template v-else>
        <section v-if="activeTab === 'overview'" class="overview-grid">
          <article class="metric"><span>进程状态</span><strong>{{ statusLabel }}</strong><small>PID {{ instance?.process.pid ?? "—" }}</small></article>
          <article class="metric"><span>世界存档</span><strong>{{ worlds.length }}</strong><small>{{ worlds.filter((world) => world.has_mod_data).length }} 个含模组数据</small></article>
          <article class="metric"><span>启用模组</span><strong>{{ mods.filter((mod) => mod.enabled).length }}</strong><small>共发现 {{ mods.length }} 个</small></article>
          <article class="metric"><span>备份</span><strong>{{ backups.length }}</strong><small>{{ backups[0] ? new Date(backups[0].created_at).toLocaleString() : "暂无备份" }}</small></article>
          <div v-if="provisioning?.operation === 'update' && provisioning.state !== 'idle'" class="panel wide">
            <div class="section-heading"><Download :size="20" /><div><h2>tModLoader 更新</h2><p>{{ provisioning.state === 'running' ? '进行中' : provisioning.state === 'succeeded' ? '已完成' : '未完成' }}</p></div></div>
            <div class="progress-strip" :data-state="provisioning.state">
              <div v-for="(stage, index) in provisionStages" :key="stage.id" :class="{ active: index <= provisionStageIndex, current: stage.id === provisioning.stage }"><span>{{ index + 1 }}</span><small>{{ stage.label }}</small></div>
            </div>
            <div v-if="provisioning.error" class="provision-error">{{ provisioning.error }}</div>
            <div class="setup-terminal" aria-live="polite">
              <div v-if="!provisionLogs.length" class="terminal-empty">等待更新输出</div>
              <div v-for="entry in provisionLogs" :key="entry.sequence" class="terminal-line"><time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span></div>
            </div>
            <button v-if="provisioningRunning" class="secondary cancel-task" :disabled="busy" @click="cancelProvisioning"><X :size="17" />取消任务</button>
          </div>
          <div class="panel wide">
            <div class="section-heading"><Server :size="20" /><div><h2>{{ instance?.instance?.name }}</h2><p>{{ instance?.instance?.install_dir }}</p></div></div>
            <dl><dt>配置文件</dt><dd>{{ instance?.instance?.config_file }}</dd><dt>退出码</dt><dd>{{ instance?.process.exit_code ?? "—" }}</dd></dl>
          </div>
        </section>

        <section v-if="activeTab === 'console'" class="console-panel">
          <div ref="consoleView" class="terminal" aria-live="polite">
            <div v-if="!consoleEntries.length" class="terminal-empty">等待服务端输出</div>
            <div v-for="entry in consoleEntries" :key="entry.sequence" :class="['terminal-line', entry.stream]">
              <time>{{ new Date(entry.timestamp).toLocaleTimeString() }}</time><span>{{ entry.text }}</span>
            </div>
          </div>
          <form class="command-bar" @submit.prevent="sendCommand">
            <span>›</span><input v-model="command" :disabled="!running" autocomplete="off" placeholder="输入服务端命令" />
            <button class="icon-button" title="发送" :disabled="!running || busy"><Send :size="18" /></button>
          </form>
        </section>

        <section v-if="activeTab === 'config'" class="content-grid">
          <div class="panel">
            <div class="section-heading"><FileCog :size="20" /><h2>服务器配置</h2></div>
            <form class="form-grid" @submit.prevent="saveConfig">
              <label>最大玩家数<input v-model.number="configForm.maxplayers" type="number" min="1" max="255" /></label>
              <label>端口<input v-model.number="configForm.port" type="number" min="1" max="65535" /></label>
              <label class="full">密码<input v-model="configForm.password" type="password" /></label>
              <label class="full">欢迎消息<input v-model="configForm.motd" /></label>
              <button class="primary"><Save :size="17" />保存配置</button>
            </form>
          </div>
          <div class="panel">
            <div class="section-heading"><FolderOpen :size="20" /><h2>世界</h2></div>
            <div class="list">
              <button v-for="world in worlds" :key="world.path" class="list-row" @click="selectWorld(world.path)">
                <span><strong>{{ world.name }}</strong><small>{{ formatBytes(world.size) }}</small></span><span class="tag">{{ world.has_mod_data ? "Mod" : "Vanilla" }}</span>
              </button>
              <div v-if="!worlds.length" class="empty">未发现世界存档</div>
            </div>
          </div>
        </section>

        <section v-if="activeTab === 'mods'" class="panel">
          <div class="section-heading"><Boxes :size="20" /><div><h2>模组</h2><p>{{ mods.filter((mod) => mod.enabled).length }} / {{ mods.length }} 已启用</p></div></div>
          <form class="mod-upload" @submit.prevent="uploadMod">
            <label class="file-picker">
              <input ref="modFileInput" type="file" accept=".tmod" :disabled="running || busy" @change="selectModFile" />
              <span>{{ modFile?.name ?? "选择 .tmod" }}</span>
            </label>
            <label class="check-row"><input v-model="replaceMod" type="checkbox" :disabled="running || busy" />覆盖同名</label>
            <button class="primary" :disabled="!modFile || running || busy"><Upload :size="17" />上传</button>
          </form>
          <div class="table-list">
            <div v-for="mod in mods" :key="`${mod.source}-${mod.file}`" class="table-row">
              <span><strong>{{ mod.name }}</strong><small>{{ mod.source }} · {{ formatBytes(mod.size) }}</small></span>
              <label class="switch"><input type="checkbox" :checked="mod.enabled" :disabled="busy" @change="toggleMod(mod)" /><span></span></label>
            </div>
            <div v-if="!mods.length" class="empty">未发现 .tmod 文件</div>
          </div>
        </section>

        <section v-if="activeTab === 'backups'" class="panel">
          <div class="section-heading"><HardDrive :size="20" /><h2>存档备份</h2></div>
          <form class="inline-form" @submit.prevent="createBackup"><input v-model="backupLabel" pattern="[A-Za-z0-9_.-]+" placeholder="标签（可选）" /><button class="primary" :disabled="running"><Save :size="17" />创建备份</button></form>
          <div class="table-list">
            <div v-for="backup in backups" :key="backup.id" class="table-row"><span><strong>{{ backup.id }}</strong><small>{{ new Date(backup.created_at).toLocaleString() }} · {{ formatBytes(backup.size) }} · {{ backup.world_files }} 个世界</small></span><button class="icon-button" title="恢复" :disabled="running" @click="restoreBackup(backup)"><ArchiveRestore :size="18" /></button></div>
            <div v-if="!backups.length" class="empty">暂无备份</div>
          </div>
        </section>

        <section v-if="activeTab === 'logs'" class="logs-panel">
          <div class="log-toolbar"><div class="segmented"><button v-for="source in ['server', 'console', 'launch', 'native']" :key="source" :class="{ active: logSource === source }" @click="logSource = source; refreshLog()">{{ source }}</button></div><button class="icon-button" title="刷新日志" @click="refreshLog"><RefreshCw :size="18" /></button></div>
          <pre>{{ logLines.join('\n') || '暂无日志' }}</pre>
        </section>
      </template>
    </main>
  </div>
</template>
