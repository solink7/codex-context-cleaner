/**
 * [INPUT]: 设置页原生控件、本机会话令牌与 settings.py 的 JSON 接口。
 * [OUTPUT]: 配置草稿、保存反馈、运行状态、启停与客户端地址复制。
 * [POS]: UI 交互层；轮询只更新状态，不覆盖用户正在编辑的配置。
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
const form = document.querySelector('#settings-form');
const upstream = document.querySelector('#upstream');
const port = document.querySelector('#port');
const timeout = document.querySelector('#timeout');
const fullHistory = document.querySelector('#full-history');
const save = document.querySelector('#save');
const saveLabel = document.querySelector('#save-label');
const toggle = document.querySelector('#toggle');
const status = document.querySelector('#status');
const statusLabel = document.querySelector('#status-label');
const clientUrl = document.querySelector('#client-url');
const feedback = document.querySelector('#feedback');
const saveNote = document.querySelector('#save-note');
const copyLabel = document.querySelector('#copy-label');
let token = location.hash.slice(1);
try {
  if (token) sessionStorage.setItem('settings-token', token);
  else token = sessionStorage.getItem('settings-token') || '';
  if (token) history.replaceState(null, '', location.pathname);
} catch { /* 隐私模式禁用存储时，保留地址中的会话令牌。 */ }
let state = null;
let busy = false;
let connected = null;
let copyTimer;
let revision = 0;

// ---- 唯一请求出口 ----
async function request(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Settings-Token': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    cache: 'no-store',
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失败，请稍后重试。');
  return result;
}

function draft() {
  return { port: Number(port.value), upstream_base_url: upstream.value.trim(),
    timeout_seconds: Number(timeout.value), assume_full_history: fullHistory.checked };
}

function dirty() {
  return state && JSON.stringify(draft()) !== JSON.stringify(state.config);
}

function message(text, error = false) {
  feedback.textContent = text;
  feedback.dataset.error = String(error);
  feedback.setAttribute('role', error ? 'alert' : 'status');
  feedback.hidden = !text;
}

function updateControls() {
  const running = Boolean(state?.status.running);
  const healthy = Boolean(state?.status.healthy);
  status.dataset.running = String(healthy);
  statusLabel.textContent = connected === null ? '正在连接' : !connected ? '连接已断开' : healthy ? '运行中' : running ? '需要检查' : '未启动';
  saveLabel.textContent = busy ? '正在应用' : running ? '保存并应用' : '保存设置';
  toggle.firstChild.textContent = running ? '停止代理' : '启动代理';
  toggle.querySelector('path').setAttribute('d', running ? 'M4 4h8v8H4Z' : 'm6 3 6 5-6 5Z');
  const changed = dirty();
  toggle.disabled = busy || !connected || (!running && (changed || !state?.config.upstream_base_url));
  saveNote.textContent = changed ? '有未保存的修改。' : running ? '修改后会重新启动代理。' : '设置只保存在这台电脑上。';
  for (const element of form.elements) element.disabled = busy || !connected;
  save.disabled = busy || !connected;
  save.setAttribute('aria-busy', String(busy));
}

function render(result, hydrate = false) {
  hydrate = hydrate || state === null;
  state = result;
  connected = true;
  if (hydrate) {
    upstream.value = result.config.upstream_base_url;
    port.value = result.config.port;
    timeout.value = result.config.timeout_seconds;
    fullHistory.checked = result.config.assume_full_history;
  }
  clientUrl.textContent = result.client_url;
  updateControls();
}

async function operate(action) {
  if (busy) return;
  busy = true;
  revision += 1;
  message('');
  updateControls();
  try { await action(); }
  catch (error) { message(error.message || '无法连接设置服务，请重新打开“设置代理”。', true); }
  finally { busy = false; updateControls(); }
}

form.addEventListener('input', () => {
  message('');
  updateControls();
});

form.addEventListener('invalid', event => {
  const advanced = document.querySelector('#advanced');
  if (advanced.contains(event.target)) advanced.open = true;
}, true);

form.addEventListener('submit', event => {
  event.preventDefault();
  const config = draft();
  operate(async () => {
    render(await request('/api/config', config), true);
    message(state.status.healthy ? '设置已应用，代理正在运行。' : '设置已保存，可以启动代理了。');
  });
});

toggle.addEventListener('click', () => {
  const action = state?.status.running ? 'stop' : 'start';
  operate(async () => {
    render(await request('/api/' + action, {}));
    message(action === 'start' ? '代理已启动。复制下方地址，在客户端新开聊天验证连接。' : '代理已停止。');
  });
});

document.querySelector('#copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(clientUrl.textContent);
    copyLabel.textContent = '已复制';
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copyLabel.textContent = '复制'; }, 1800);
  } catch { message('无法自动复制，请选中客户端地址后手动复制。', true); }
});

async function refresh(initial = false) {
  if (busy) return;
  const startedAt = revision;
  try {
    const result = await request('/api/state');
    if (busy || startedAt !== revision) return;
    render(result, initial);
    if (initial && state.config_error) message(state.config_error, true);
    else if (initial && state.status.error) message(state.status.error, true);
  } catch (error) {
    if (busy || startedAt !== revision) return;
    connected = false;
    updateControls();
    message(initial ? error.message : '设置服务已断开，请重新打开“设置代理”。', true);
  }
}

// ---- 首次加载与轻量状态轮询 ----
updateControls();
refresh(true);
setInterval(() => { if (!document.hidden) refresh(); }, 3000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
