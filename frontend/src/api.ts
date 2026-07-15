export interface ProcessSnapshot {
  state: "stopped" | "starting" | "running" | "stopping" | "failed";
  pid: number | null;
  started_at: string | null;
  exit_code: number | null;
}

export interface InstanceRecord {
  id: "primary";
  name: string;
  root_dir: string;
  install_dir: string;
  config_file: string;
  created_at: string;
  updated_at: string;
}

export interface InstanceState {
  configured: boolean;
  instance: InstanceRecord | null;
  process: ProcessSnapshot;
}

export interface ConsoleEntry {
  sequence: number;
  timestamp: string;
  stream: string;
  text: string;
}

export interface WorldInfo {
  name: string;
  path: string;
  has_mod_data: boolean;
  size: number;
  modified_at: string;
  selected: boolean;
  exists: boolean;
}

export interface WorldCreateRequest {
  name: string;
  world_size: number;
  difficulty: number;
  seed: string | null;
}

export interface FileEntry {
  name: string;
  path: string;
  kind: "file" | "directory" | "symlink" | "other";
  size: number | null;
  modified_at: string;
  archive: boolean;
}

export interface TextFileView {
  path: string;
  content: string;
  revision: string;
  size: number;
}

export interface SpamCheckStatus {
  config_path: string | null;
  secure_value: string | null;
  secure_configured: boolean;
  secure_enabled: boolean | null;
  launch_script_path: string;
  launch_script_inspected: boolean;
  secure_launch_argument: boolean;
  projectile_spam_matches: number;
  projectile_spam_sources: string[];
  protection_disabled: boolean;
}

export interface DirectoryListing {
  path: string;
  parent: string | null;
  entries: FileEntry[];
}

export interface ArchivePreview {
  path: string;
  files: number;
  directories: number;
  expanded_size: number;
  compressed_size: number;
  top_level: string[];
  conflicts: string[];
}

export interface ArchiveExtractResult {
  destination: string;
  files: number;
  directories: number;
  bytes_written: number;
}

export interface ModInfo {
  name: string;
  source: "local" | "workshop";
  file: string;
  size: number;
  enabled: boolean;
}

export interface BackupInfo {
  id: string;
  created_at: string;
  size: number;
  world_files: number;
}

export type TaskActionType = "wait" | "start" | "stop" | "restart" | "command" | "backup";
export type TaskEventType = "panel_started" | "server_started" | "server_stopped" | "server_failed";
export type TaskRunSource = "schedule" | "event" | "manual";
export type TaskRunStatus = "running" | "success" | "failed" | "skipped";

export interface TaskAction {
  type: TaskActionType;
  command?: string | null;
  delay_seconds?: number | null;
  backup_label?: string | null;
}

export interface IntervalTaskTrigger {
  type: "interval";
  interval_seconds: number;
  start_at?: string | null;
}

export interface WeeklyTaskTrigger {
  type: "weekly";
  weekdays: number[];
  at_time: string;
  timezone: string;
}

export interface OnceTaskTrigger {
  type: "once";
  run_at: string;
}

export interface EventTaskTrigger {
  type: "event";
  event: TaskEventType;
  cooldown_seconds: number;
}

export type TaskTrigger =
  | IntervalTaskTrigger
  | WeeklyTaskTrigger
  | OnceTaskTrigger
  | EventTaskTrigger;

export interface TaskRequest {
  name: string;
  enabled: boolean;
  trigger: TaskTrigger;
  actions: TaskAction[];
}

export interface TaskRun {
  id: string;
  task_id: string;
  task_name: string;
  source: TaskRunSource;
  event: TaskEventType | null;
  status: TaskRunStatus;
  started_at: string;
  finished_at: string | null;
  message: string | null;
}

export interface TaskInfo extends TaskRequest {
  id: string;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  running: boolean;
  last_run: TaskRun | null;
}

export interface LogView {
  source: string;
  path: string | null;
  lines: string[];
}

export interface ServerConfigView {
  values: Record<string, string>;
}

export interface ServerConfigUpdate {
  maxplayers: number;
  port: number;
  password: string | null;
  motd: string | null;
  language: string | null;
  secure: boolean;
  upnp: boolean;
  npcstream: number | null;
  priority: number;
  banlist: string | null;
  modpath: string | null;
  modpack: string | null;
}

export type ProvisionState = "idle" | "running" | "succeeded" | "failed" | "cancelled";
export type ProvisionStage =
  | "idle"
  | "preparing"
  | "installing"
  | "associating"
  | "configuring"
  | "starting"
  | "complete";

export interface ProvisionSnapshot {
  state: ProvisionState;
  stage: ProvisionStage;
  operation: "install" | "update" | null;
  name: string | null;
  root_dir: string | null;
  version: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  instance: InstanceRecord | null;
  process: ProcessSnapshot | null;
}

export interface ProvisionRequest {
  name: string;
  root_dir: string;
  version: string | null;
  world_name: string;
  world_size: number;
  difficulty: number;
  max_players: number;
  port: number;
  password: string;
  motd: string;
  secure: boolean;
  upnp: boolean;
  start_after_install: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: init?.body && !isFormData
      ? { "Content-Type": "application/json", ...init.headers }
      : init?.headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  provisioning: () => request<ProvisionSnapshot>("/provisioning"),
  provision: (values: ProvisionRequest) =>
    request<ProvisionSnapshot>("/provisioning", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  provisionLogs: (after = 0) =>
    request<ConsoleEntry[]>(`/provisioning/logs?after_sequence=${after}&limit=1000`),
  cancelProvisioning: () =>
    request<ProvisionSnapshot>("/provisioning/cancel", { method: "POST" }),
  updateServer: (version: string | null = null) =>
    request<ProvisionSnapshot>("/provisioning/update", {
      method: "POST",
      body: JSON.stringify({ version, start_after_update: true }),
    }),
  instance: () => request<InstanceState>("/instance"),
  associate: (name: string, rootDir: string) =>
    request<InstanceRecord>("/instance", {
      method: "PUT",
      body: JSON.stringify({ name, root_dir: rootDir }),
    }),
  start: () => request<ProcessSnapshot>("/instance/start", { method: "POST" }),
  stop: () => request<ProcessSnapshot>("/instance/stop", { method: "POST" }),
  console: (after = 0) =>
    request<ConsoleEntry[]>(`/instance/console?after_sequence=${after}&limit=1000`),
  command: (command: string) =>
    request<{ status: string }>("/instance/console", {
      method: "POST",
      body: JSON.stringify({ command }),
    }),
  config: () => request<ServerConfigView>("/server-config"),
  updateConfig: (values: ServerConfigUpdate) =>
    request<ServerConfigView>("/server-config", {
      method: "PATCH",
      body: JSON.stringify(values),
    }),
  spamCheck: () => request<SpamCheckStatus>("/server-config/spam-check"),
  disableSpamCheck: () => request<SpamCheckStatus>("/server-config/spam-check/disable", {
    method: "POST",
  }),
  worlds: () => request<WorldInfo[]>("/worlds"),
  createWorld: (values: WorldCreateRequest) =>
    request<WorldInfo>("/worlds", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  selectWorld: (path: string) =>
    request<ServerConfigView>("/worlds/select", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  uploadWorld: (files: File[], replace = false) => {
    const body = new FormData();
    for (const file of files) body.append("files", file);
    return request<WorldInfo>(`/worlds/upload?replace=${replace}`, { method: "POST", body });
  },
  deleteWorld: (name: string) =>
    request<string[]>(`/worlds/${encodeURIComponent(name)}`, { method: "DELETE" }),
  files: (path = "") =>
    request<DirectoryListing>(`/files?${new URLSearchParams({ path })}`),
  createDirectory: (path: string) =>
    request<FileEntry>("/files/directories", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  uploadFile: (
    directory: string,
    file: File,
    replace = false,
    onProgress?: (loaded: number, total: number) => void,
  ) => new Promise<FileEntry>((resolve, reject) => {
    const query = new URLSearchParams({
      directory,
      filename: file.name,
      replace: String(replace),
    });
    const upload = new XMLHttpRequest();
    upload.open("POST", `/api/v1/files/upload?${query}`);
    upload.responseType = "json";
    upload.upload.onprogress = (event) => {
      onProgress?.(event.loaded, event.lengthComputable ? event.total : file.size);
    };
    upload.onerror = () => reject(new Error("File upload failed"));
    upload.onload = () => {
      const payload = upload.response as FileEntry | { detail?: string } | null;
      if (upload.status >= 200 && upload.status < 300 && payload) {
        resolve(payload as FileEntry);
      } else {
        reject(new Error(
          (payload as { detail?: string } | null)?.detail
            ?? `Request failed (${upload.status})`,
        ));
      }
    };
    upload.send(file);
  }),
  moveFile: (source: string, destination: string, replace = false) =>
    request<FileEntry>("/files", {
      method: "PATCH",
      body: JSON.stringify({ source, destination, replace }),
    }),
  deleteFile: (path: string, recursive = false) =>
    request<void>(`/files?${new URLSearchParams({ path, recursive: String(recursive) })}`, {
      method: "DELETE",
    }),
  fileDownloadUrl: (path: string) =>
    `/api/v1/files/download?${new URLSearchParams({ path })}`,
  textFile: (path: string) =>
    request<TextFileView>(`/files/text?${new URLSearchParams({ path })}`),
  updateTextFile: (file: TextFileView, content: string) =>
    request<TextFileView>("/files/text", {
      method: "PUT",
      body: JSON.stringify({ path: file.path, content, revision: file.revision }),
    }),
  inspectArchive: (path: string, destination = "") =>
    request<ArchivePreview>(
      `/files/archive?${new URLSearchParams({ path, destination })}`,
    ),
  extractArchive: (path: string, destination = "", replace = false) =>
    request<ArchiveExtractResult>("/files/archive/extract", {
      method: "POST",
      body: JSON.stringify({ path, destination, replace }),
    }),
  mods: () => request<ModInfo[]>("/mods"),
  toggleMod: (name: string, enabled: boolean) =>
    request<string[]>(`/mods/${enabled ? "enable" : "disable"}`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  uploadMod: (file: File, replace = false) => {
    const body = new FormData();
    body.append("file", file);
    return request<ModInfo>(`/mods/upload?replace=${replace}`, { method: "POST", body });
  },
  deleteLocalMod: (name: string) =>
    request<void>(`/mods/local/${encodeURIComponent(name)}`, { method: "DELETE" }),
  backups: () => request<BackupInfo[]>("/backups"),
  createBackup: (label?: string) =>
    request<BackupInfo>("/backups", {
      method: "POST",
      body: JSON.stringify({ label: label || null }),
    }),
  restoreBackup: (id: string) =>
    request<BackupInfo>(`/backups/${encodeURIComponent(id)}/restore`, { method: "POST" }),
  backupDownloadUrl: (id: string) =>
    `/api/v1/backups/${encodeURIComponent(id)}/download`,
  deleteBackup: (id: string) =>
    request<void>(`/backups/${encodeURIComponent(id)}`, { method: "DELETE" }),
  tasks: (kind?: "schedule" | "event") =>
    request<TaskInfo[]>(`/tasks${kind ? `?kind=${kind}` : ""}`),
  taskRuns: (taskId?: string, limit = 100) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (taskId) query.set("task_id", taskId);
    return request<TaskRun[]>(`/tasks/runs?${query}`);
  },
  createTask: (values: TaskRequest) =>
    request<TaskInfo>("/tasks", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  updateTask: (id: string, values: TaskRequest) =>
    request<TaskInfo>(`/tasks/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(values),
    }),
  setTaskEnabled: (id: string, enabled: boolean) =>
    request<TaskInfo>(`/tasks/${encodeURIComponent(id)}/enabled`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  runTask: (id: string) =>
    request<TaskRun>(`/tasks/${encodeURIComponent(id)}/run`, { method: "POST" }),
  deleteTask: (id: string) =>
    request<void>(`/tasks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  log: (source: string) => request<LogView>(`/logs/${source}?lines=500`),
};
