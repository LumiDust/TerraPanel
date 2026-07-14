<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  CalendarClock,
  History,
  Pencil,
  Play,
  Plus,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import {
  api,
  type EventTaskTrigger,
  type TaskAction,
  type TaskActionType,
  type TaskEventType,
  type TaskInfo,
  type TaskRequest,
  type TaskRun,
  type TaskTrigger,
} from "../api";

type TaskKind = "schedule" | "event";
type ScheduleType = "interval" | "weekly" | "once";

interface TaskForm {
  name: string;
  enabled: boolean;
  kind: TaskKind;
  scheduleType: ScheduleType;
  intervalSeconds: number;
  weekdays: number[];
  atTime: string;
  timezone: string;
  runAt: string;
  event: TaskEventType;
  cooldownSeconds: number;
  actions: TaskAction[];
}

const emit = defineEmits<{ error: [message: string] }>();
const activeKind = ref<TaskKind>("schedule");
const tasks = ref<TaskInfo[]>([]);
const runs = ref<TaskRun[]>([]);
const loading = ref(false);
const saving = ref(false);
const editorOpen = ref(false);
const editingId = ref<string | null>(null);
const pendingDelete = ref<TaskInfo | null>(null);
const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
let refreshTimer: number | undefined;

const actionLabels: Record<TaskActionType, string> = {
  wait: "等待",
  start: "启动服务器",
  stop: "停止服务器",
  restart: "重启服务器",
  command: "发送命令",
  backup: "创建备份",
};
const eventLabels: Record<TaskEventType, string> = {
  panel_started: "面板启动",
  server_started: "服务器启动",
  server_stopped: "服务器正常停止",
  server_failed: "服务器异常退出",
};
const weekdayOptions = [
  { value: 0, label: "一" },
  { value: 1, label: "二" },
  { value: 2, label: "三" },
  { value: 3, label: "四" },
  { value: 4, label: "五" },
  { value: 5, label: "六" },
  { value: 6, label: "日" },
];

const defaultRunAt = () => {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setSeconds(0, 0);
  return toLocalDateTime(date);
};

const newForm = (kind: TaskKind = activeKind.value): TaskForm => ({
  name: "",
  enabled: true,
  kind,
  scheduleType: "interval",
  intervalSeconds: 3600,
  weekdays: [0, 1, 2, 3, 4],
  atTime: "04:00",
  timezone: browserTimezone,
  runAt: defaultRunAt(),
  event: "server_failed",
  cooldownSeconds: 30,
  actions: [{ type: kind === "event" ? "start" : "backup" }],
});

const form = ref<TaskForm>(newForm());
const filteredTasks = computed(() => tasks.value.filter((task) => taskKind(task) === activeKind.value));
const enabledCount = computed(() => filteredTasks.value.filter((task) => task.enabled).length);
const recentRuns = computed(() => runs.value.slice(0, 20));

async function refresh() {
  if (loading.value) return;
  loading.value = true;
  try {
    [tasks.value, runs.value] = await Promise.all([api.tasks(), api.taskRuns(undefined, 100)]);
  } catch (reason) {
    report(reason);
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  form.value = newForm(activeKind.value);
  editorOpen.value = true;
}

function openEdit(task: TaskInfo) {
  editingId.value = task.id;
  form.value = taskToForm(task);
  editorOpen.value = true;
}

function closeEditor() {
  if (!saving.value) editorOpen.value = false;
}

async function saveTask() {
  saving.value = true;
  try {
    const request = formToRequest(form.value);
    if (editingId.value) await api.updateTask(editingId.value, request);
    else await api.createTask(request);
    editorOpen.value = false;
    await refresh();
  } catch (reason) {
    report(reason);
  } finally {
    saving.value = false;
  }
}

async function toggleTask(task: TaskInfo) {
  try {
    await api.setTaskEnabled(task.id, !task.enabled);
    await refresh();
  } catch (reason) {
    report(reason);
  }
}

async function runTask(task: TaskInfo) {
  try {
    await api.runTask(task.id);
    await refresh();
    window.setTimeout(() => void refresh(), 500);
  } catch (reason) {
    report(reason);
  }
}

async function deleteTask() {
  const task = pendingDelete.value;
  pendingDelete.value = null;
  if (!task) return;
  try {
    await api.deleteTask(task.id);
    await refresh();
  } catch (reason) {
    report(reason);
  }
}

function addAction() {
  if (form.value.actions.length < 10) form.value.actions.push({ type: "command", command: "" });
}

function removeAction(index: number) {
  if (form.value.actions.length > 1) form.value.actions.splice(index, 1);
}

function moveAction(index: number, offset: -1 | 1) {
  const destination = index + offset;
  if (destination < 0 || destination >= form.value.actions.length) return;
  const [action] = form.value.actions.splice(index, 1);
  form.value.actions.splice(destination, 0, action);
}

function changeActionType(action: TaskAction) {
  action.command = action.type === "command" ? "" : null;
  action.delay_seconds = action.type === "wait" ? 10 : null;
  action.backup_label = null;
}

function toggleWeekday(day: number) {
  const index = form.value.weekdays.indexOf(day);
  if (index >= 0) {
    if (form.value.weekdays.length > 1) form.value.weekdays.splice(index, 1);
  } else {
    form.value.weekdays.push(day);
    form.value.weekdays.sort();
  }
}

function taskKind(task: TaskInfo): TaskKind {
  return task.trigger.type === "event" ? "event" : "schedule";
}

function triggerLabel(trigger: TaskTrigger): string {
  if (trigger.type === "interval") return `每 ${formatDuration(trigger.interval_seconds)}`;
  if (trigger.type === "weekly") {
    const days = trigger.weekdays.map((day) => weekdayOptions[day]?.label ?? day).join("、");
    return `周${days} ${trigger.at_time.slice(0, 5)} · ${trigger.timezone}`;
  }
  if (trigger.type === "once") return new Date(trigger.run_at).toLocaleString();
  return `${eventLabels[trigger.event]} · 冷却 ${trigger.cooldown_seconds}s`;
}

function actionSummary(actions: TaskAction[]): string {
  return actions.map((action) => actionLabels[action.type]).join(" → ");
}

function runStatusLabel(status: TaskRun["status"]): string {
  return { running: "执行中", success: "成功", failed: "失败", skipped: "已跳过" }[status];
}

function runSourceLabel(run: TaskRun): string {
  if (run.source === "manual") return "手动";
  if (run.source === "schedule") return "计划";
  return run.event ? eventLabels[run.event] : "事件";
}

function taskToForm(task: TaskInfo): TaskForm {
  const result = newForm(taskKind(task));
  result.name = task.name;
  result.enabled = task.enabled;
  result.actions = task.actions.map((action) => ({ ...action }));
  const trigger = task.trigger;
  if (trigger.type === "interval") {
    result.scheduleType = "interval";
    result.intervalSeconds = trigger.interval_seconds;
  } else if (trigger.type === "weekly") {
    result.scheduleType = "weekly";
    result.weekdays = [...trigger.weekdays];
    result.atTime = trigger.at_time.slice(0, 5);
    result.timezone = trigger.timezone;
  } else if (trigger.type === "once") {
    result.scheduleType = "once";
    result.runAt = toLocalDateTime(new Date(trigger.run_at));
  } else {
    result.event = trigger.event;
    result.cooldownSeconds = trigger.cooldown_seconds;
  }
  return result;
}

function formToRequest(value: TaskForm): TaskRequest {
  let trigger: TaskTrigger;
  if (value.kind === "event") {
    trigger = {
      type: "event",
      event: value.event,
      cooldown_seconds: value.cooldownSeconds,
    } satisfies EventTaskTrigger;
  } else if (value.scheduleType === "interval") {
    trigger = { type: "interval", interval_seconds: value.intervalSeconds };
  } else if (value.scheduleType === "weekly") {
    trigger = {
      type: "weekly",
      weekdays: value.weekdays,
      at_time: value.atTime.length === 5 ? `${value.atTime}:00` : value.atTime,
      timezone: value.timezone,
    };
  } else {
    trigger = { type: "once", run_at: new Date(value.runAt).toISOString() };
  }
  return {
    name: value.name.trim(),
    enabled: value.enabled,
    trigger,
    actions: value.actions.map(cleanAction),
  };
}

function cleanAction(action: TaskAction): TaskAction {
  if (action.type === "command") return { type: action.type, command: action.command?.trim() ?? "" };
  if (action.type === "wait") return { type: action.type, delay_seconds: action.delay_seconds ?? 10 };
  if (action.type === "backup") {
    return { type: action.type, backup_label: action.backup_label?.trim() || null };
  }
  return { type: action.type };
}

function toLocalDateTime(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function formatDuration(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

function report(reason: unknown) {
  emit("error", reason instanceof Error ? reason.message : String(reason));
}

onMounted(() => {
  void refresh();
  refreshTimer = window.setInterval(() => void refresh(), 3000);
});
onBeforeUnmount(() => window.clearInterval(refreshTimer));
defineExpose({ refresh });
</script>

<template>
  <section class="panel task-panel">
    <div class="task-toolbar">
      <div class="segmented" aria-label="任务类型">
        <button :class="{ active: activeKind === 'schedule' }" @click="activeKind = 'schedule'">
          计划任务
        </button>
        <button :class="{ active: activeKind === 'event' }" @click="activeKind = 'event'">
          事件任务
        </button>
      </div>
      <div class="task-toolbar-meta">
        <span>{{ enabledCount }} 启用 · {{ filteredTasks.length }} 总计</span>
        <button class="primary" @click="openCreate"><Plus :size="17" />新建任务</button>
      </div>
    </div>

    <div class="task-list" :aria-busy="loading">
      <div v-for="task in filteredTasks" :key="task.id" class="task-row">
        <label class="switch" :title="task.enabled ? '停用任务' : '启用任务'">
          <input type="checkbox" :checked="task.enabled" @change="toggleTask(task)" />
          <span></span>
        </label>
        <div class="task-main">
          <div class="task-title">
            <strong>{{ task.name }}</strong>
            <span v-if="task.running" class="task-state running">执行中</span>
            <span v-else-if="!task.enabled" class="task-state disabled">已停用</span>
          </div>
          <small>{{ triggerLabel(task.trigger) }}</small>
          <span class="action-path">{{ actionSummary(task.actions) }}</span>
        </div>
        <div class="task-timing">
          <span>{{ task.next_run_at ? "下次 " + new Date(task.next_run_at).toLocaleString() : "无下次执行" }}</span>
          <small v-if="task.last_run">上次 {{ runStatusLabel(task.last_run.status) }} · {{ new Date(task.last_run.started_at).toLocaleString() }}</small>
          <small v-else>尚未执行</small>
        </div>
        <div class="row-actions">
          <button class="icon-button" title="立即运行" :disabled="task.running" @click="runTask(task)">
            <Play :size="17" />
          </button>
          <button class="icon-button" title="编辑任务" @click="openEdit(task)"><Pencil :size="17" /></button>
          <button class="icon-button danger-icon" title="删除任务" :disabled="task.running" @click="pendingDelete = task">
            <Trash2 :size="17" />
          </button>
        </div>
      </div>
      <div v-if="!filteredTasks.length && !loading" class="empty">
        {{ activeKind === "schedule" ? "暂无计划任务" : "暂无事件任务" }}
      </div>
    </div>

    <section class="run-history" aria-labelledby="run-history-title">
      <div class="history-heading">
        <History :size="18" />
        <h2 id="run-history-title">执行历史</h2>
        <span>{{ recentRuns.length }} 条</span>
      </div>
      <div class="history-list">
        <div v-for="run in recentRuns" :key="run.id" class="history-row">
          <span :class="['run-status', run.status]">{{ runStatusLabel(run.status) }}</span>
          <span><strong>{{ run.task_name }}</strong><small>{{ runSourceLabel(run) }} · {{ new Date(run.started_at).toLocaleString() }}</small></span>
          <span class="run-message">{{ run.message || "—" }}</span>
        </div>
        <div v-if="!recentRuns.length" class="empty">暂无执行记录</div>
      </div>
    </section>
  </section>

  <div v-if="editorOpen" class="modal-backdrop" role="presentation" @click.self="closeEditor">
    <section class="confirm-dialog task-dialog" role="dialog" aria-modal="true" aria-labelledby="task-dialog-title">
      <div class="dialog-title">
        <div>
          <h2 id="task-dialog-title">{{ editingId ? "编辑任务" : "新建任务" }}</h2>
          <p>{{ form.kind === "schedule" ? "计划任务" : "事件任务" }}</p>
        </div>
        <button class="icon-button" title="关闭" @click="closeEditor"><X :size="18" /></button>
      </div>

      <form class="task-form" @submit.prevent="saveTask">
        <div class="task-form-grid">
          <label>名称<input v-model="form.name" required maxlength="80" /></label>
          <label class="enabled-field">状态<span><input v-model="form.enabled" type="checkbox" />启用</span></label>
        </div>

        <div v-if="form.kind === 'schedule'" class="trigger-fields">
          <label>计划类型<select v-model="form.scheduleType"><option value="interval">固定间隔</option><option value="weekly">每周循环</option><option value="once">指定时间</option></select></label>
          <label v-if="form.scheduleType === 'interval'">间隔秒数<input v-model.number="form.intervalSeconds" type="number" min="5" max="31536000" required /></label>
          <template v-if="form.scheduleType === 'weekly'">
            <label>执行时间<input v-model="form.atTime" type="time" step="1" required /></label>
            <label>时区<input v-model="form.timezone" maxlength="100" required /></label>
            <fieldset class="weekday-field"><legend>星期</legend><button v-for="day in weekdayOptions" :key="day.value" type="button" :class="{ selected: form.weekdays.includes(day.value) }" @click="toggleWeekday(day.value)">{{ day.label }}</button></fieldset>
          </template>
          <label v-if="form.scheduleType === 'once'">执行时间<input v-model="form.runAt" type="datetime-local" required /></label>
        </div>

        <div v-else class="trigger-fields">
          <label>触发事件<select v-model="form.event"><option v-for="(label, value) in eventLabels" :key="value" :value="value">{{ label }}</option></select></label>
          <label>冷却秒数<input v-model.number="form.cooldownSeconds" type="number" min="0" max="86400" required /></label>
        </div>

        <div class="action-editor">
          <div class="action-editor-heading"><h3>动作序列</h3><button type="button" class="secondary" :disabled="form.actions.length >= 10" @click="addAction"><Plus :size="16" />添加动作</button></div>
          <div v-for="(action, index) in form.actions" :key="index" class="action-row">
            <span class="action-number">{{ index + 1 }}</span>
            <select v-model="action.type" aria-label="动作类型" @change="changeActionType(action)"><option v-for="(label, value) in actionLabels" :key="value" :value="value">{{ label }}</option></select>
            <input v-if="action.type === 'command'" v-model="action.command" maxlength="2048" placeholder="服务端命令" required />
            <input v-else-if="action.type === 'wait'" v-model.number="action.delay_seconds" type="number" min="1" max="3600" placeholder="秒" required />
            <input v-else-if="action.type === 'backup'" v-model="action.backup_label" maxlength="60" pattern="[A-Za-z0-9_.-]+" placeholder="备份标签（可选）" />
            <span v-else class="action-no-input">无需参数</span>
            <div class="action-controls">
              <button type="button" class="icon-button" title="上移" :disabled="index === 0" @click="moveAction(index, -1)"><ArrowUp :size="16" /></button>
              <button type="button" class="icon-button" title="下移" :disabled="index === form.actions.length - 1" @click="moveAction(index, 1)"><ArrowDown :size="16" /></button>
              <button type="button" class="icon-button danger-icon" title="移除动作" :disabled="form.actions.length === 1" @click="removeAction(index)"><Trash2 :size="16" /></button>
            </div>
          </div>
        </div>

        <div class="dialog-actions"><button type="button" class="secondary" @click="closeEditor">取消</button><button class="primary" :disabled="saving || !form.name.trim()"><CalendarClock :size="17" />保存任务</button></div>
      </form>
    </section>
  </div>

  <div v-if="pendingDelete" class="modal-backdrop" role="presentation" @click.self="pendingDelete = null">
    <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-task-title">
      <div><h2 id="delete-task-title">删除任务</h2><p>{{ pendingDelete.name }}</p></div>
      <div class="dialog-actions"><button class="secondary" @click="pendingDelete = null">取消</button><button class="danger" @click="deleteTask">删除</button></div>
    </section>
  </div>
</template>

<style scoped>
.task-panel { padding-bottom: 8px; }
.task-toolbar, .task-toolbar-meta, .history-heading, .dialog-title, .action-editor-heading { display: flex; align-items: center; }
.task-toolbar { justify-content: space-between; gap: 16px; padding-bottom: 14px; border-bottom: 1px solid #e2e5e7; }
.task-toolbar-meta { gap: 14px; color: #737b85; font-size: 12px; }
.task-list { display: grid; }
.task-row { min-height: 84px; display: grid; grid-template-columns: 40px minmax(240px, 1.2fr) minmax(250px, .8fr) auto; align-items: center; gap: 12px; border-bottom: 1px solid #e8eaec; padding: 12px 4px; }
.task-main, .task-timing, .history-row > span:nth-child(2) { min-width: 0; display: grid; gap: 4px; }
.task-title { min-width: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.task-title strong { font-size: 13px; overflow-wrap: anywhere; }
.task-main small, .task-timing, .history-row small { color: #7b838c; font-size: 11px; }
.action-path { color: #404850; font-size: 12px; overflow-wrap: anywhere; }
.task-timing > span { color: #404850; font-size: 12px; }
.task-state, .run-status { width: fit-content; border: 1px solid #b9d9cc; border-radius: 3px; padding: 2px 6px; color: #237a5b; font-size: 10px; }
.task-state.disabled, .run-status.skipped { border-color: #d2d5d8; color: #737b85; }
.run-status.failed { border-color: #e0aaaa; color: #a53d3d; }
.run-status.running { border-color: #dfc581; color: #80651c; }
.run-history { margin-top: 14px; border-top: 1px solid #dfe2e4; }
.history-heading { min-height: 52px; gap: 8px; }
.history-heading h2 { font-size: 14px; }
.history-heading span { margin-left: auto; color: #7b838c; font-size: 11px; }
.history-list { display: grid; }
.history-row { min-height: 54px; display: grid; grid-template-columns: 64px minmax(190px, .7fr) minmax(220px, 1fr); align-items: center; gap: 12px; border-top: 1px solid #e8eaec; }
.history-row strong { font-size: 12px; }
.run-message { min-width: 0; color: #59616b; font-size: 11px; overflow-wrap: anywhere; }
.task-dialog { width: min(760px, 100%); max-height: calc(100vh - 40px); overflow: auto; }
.dialog-title { justify-content: space-between; gap: 12px; }
.dialog-title p { margin-top: 4px; color: #737b85; font-size: 12px; }
.task-form { margin-top: 18px; }
.task-form-grid, .trigger-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.enabled-field > span { min-height: 38px; display: flex; align-items: center; gap: 8px; }
.enabled-field input { width: 16px; min-height: 16px; accent-color: #237a5b; }
.trigger-fields { margin-top: 12px; padding: 12px; background: #f5f7f7; }
.weekday-field { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; border: 0; }
.weekday-field legend { width: 100%; margin-bottom: 4px; color: #59616b; font-size: 12px; }
.weekday-field button { width: 34px; height: 32px; border: 1px solid #ccd1d5; border-radius: 4px; background: #fff; color: #59616b; }
.weekday-field button.selected { border-color: #237a5b; background: #237a5b; color: #fff; }
.action-editor { margin-top: 18px; }
.action-editor-heading { justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.action-row { display: grid; grid-template-columns: 28px minmax(130px, .45fr) minmax(180px, 1fr) auto; align-items: center; gap: 8px; min-height: 54px; border-top: 1px solid #e8eaec; padding: 8px 0; }
.action-number { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: #e7f1ed; color: #237a5b; font-size: 11px; }
.action-no-input { color: #8a929b; font-size: 11px; }
.action-controls { display: flex; gap: 5px; }
.action-controls .icon-button { width: 32px; min-height: 32px; }
@media (max-width: 820px) {
  .task-row { grid-template-columns: 36px minmax(0, 1fr) auto; }
  .task-timing { grid-column: 2 / -1; }
  .history-row { grid-template-columns: 64px minmax(0, 1fr); padding: 8px 0; }
  .run-message { grid-column: 2; }
}
@media (max-width: 620px) {
  .task-toolbar { align-items: stretch; flex-direction: column; }
  .task-toolbar-meta { justify-content: space-between; }
  .task-row { grid-template-columns: 34px minmax(0, 1fr); }
  .task-row > .row-actions, .task-timing { grid-column: 2; justify-content: flex-start; }
  .task-form-grid, .trigger-fields { grid-template-columns: 1fr; }
  .weekday-field { grid-column: auto; }
  .action-row { grid-template-columns: 28px minmax(0, 1fr); }
  .action-row > input, .action-row > .action-no-input { grid-column: 2; }
  .action-controls { grid-column: 2; justify-content: flex-end; }
}
@media (max-width: 390px) {
  .task-toolbar-meta { align-items: stretch; flex-direction: column; }
  .task-toolbar-meta .primary { width: 100%; }
  .history-row { grid-template-columns: 1fr; }
  .run-message, .history-row > span:nth-child(2) { grid-column: 1; }
}
</style>
