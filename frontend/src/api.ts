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

export interface LogView {
  source: string;
  path: string | null;
  lines: string[];
}

export interface ServerConfigView {
  values: Record<string, string>;
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
  updateConfig: (values: Record<string, unknown>) =>
    request<ServerConfigView>("/server-config", {
      method: "PATCH",
      body: JSON.stringify(values),
    }),
  worlds: () => request<WorldInfo[]>("/worlds"),
  selectWorld: (path: string) =>
    request<ServerConfigView>("/worlds/select", {
      method: "POST",
      body: JSON.stringify({ path }),
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
  backups: () => request<BackupInfo[]>("/backups"),
  createBackup: (label?: string) =>
    request<BackupInfo>("/backups", {
      method: "POST",
      body: JSON.stringify({ label: label || null }),
    }),
  restoreBackup: (id: string) =>
    request<BackupInfo>(`/backups/${encodeURIComponent(id)}/restore`, { method: "POST" }),
  log: (source: string) => request<LogView>(`/logs/${source}?lines=500`),
};
