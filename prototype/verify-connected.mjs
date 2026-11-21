import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, realpath, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

const python = process.env.AI_COACH_TEST_PYTHON || resolve('.venv/Scripts/python.exe');
const chrome = process.env.AI_COACH_TEST_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const tempRoot = await realpath(tmpdir());
const profile = await mkdtemp(join(tempRoot, 'coach-connected-'));
const reservation = createServer();
reservation.listen(0, '127.0.0.1');
await once(reservation, 'listening');
const { port } = reservation.address();
await new Promise((done, fail) => reservation.close(error => error ? fail(error) : done()));
const origin = `http://127.0.0.1:${port}`;
const url = origin + '/app/';
const env = Object.fromEntries(Object.entries(process.env).filter(([name]) => !/^SUPABASE_/i.test(name)));
const server = spawn(python, ['-B', 'tests/connected_browser_fixture.py', String(port)],
  { env, windowsHide: true, stdio: 'ignore' });
let browser;
let connection;

async function until(check, label) {
  for (let attempt = 0; attempt < 120; attempt++) {
    if (await check()) return;
    await delay(100);
  }
  assert.fail(label);
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, 'exit');
  child.kill();
  await exited;
}

try {
  await until(async () => (await fetch(url).catch(() => null))?.ok, 'mock FastAPI startup');
  const html = await fetch(url);
  assert.equal(html.headers.get('cache-control'), 'no-store');
  assert.equal((await fetch(origin + '/docs')).status, 200);
  assert.equal((await fetch(origin + '/app/assets/workspace.js')).status, 200);
  assert.equal((await fetch(origin + '/app/ACCEPTANCE.md')).status, 404);
  browser = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--disable-background-networking', '--disable-component-update', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });
  let devTools;
  await until(async () => {
    devTools = await readFile(join(profile, 'DevToolsActivePort'), 'utf8').catch(() => '');
    return devTools.length > 0;
  }, 'Chrome DevTools startup');
  const [debugPort] = devTools.split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
  const target = targets.find(item => item.type === 'page');
  assert.ok(target);
  connection = new WebSocket(target.webSocketDebuggerUrl);
  await once(connection, 'open');
  let sequence = 0;
  const pending = new Map();
  const runtimeErrors = [];
  connection.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') runtimeErrors.push(message.method);
    const waiter = pending.get(message.id);
    if (!waiter) return;
    clearTimeout(waiter.timer);
    pending.delete(message.id);
    if (message.error) waiter.reject(Error(`DevTools command failed (${message.error.code})`));
    else waiter.resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(Error(method + ' timed out')); }, 10000);
    pending.set(id, { resolve, reject, timer });
    connection.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw Error('Browser evaluation failed');
    return result.result.value;
  };
  const waitFor = (condition, label) => until(() => evaluate(condition), label);
  const contentHas = text => waitFor(
    `document.querySelector('#content')?.textContent.includes(${JSON.stringify(text)})`, text,
  );
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const login = (email, password) => evaluate(`
    document.querySelector('#loginEmail').value = ${JSON.stringify(email)};
    document.querySelector('#loginPassword').value = ${JSON.stringify(password)};
    document.querySelector('#loginForm').requestSubmit();
  `);
  const status = path => evaluate(`fetch(${JSON.stringify(path)}, {credentials:'same-origin',cache:'no-store'}).then(response => response.status)`);
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await send('Page.navigate', { url });
  await waitFor("document.querySelector('#loginForm button[type=submit]')?.disabled === false", 'session check');
  assert.equal(await status('/api/v1/members'), 401);
  assert.equal(await evaluate("document.querySelector('#loginPassword').value"), '');
  await evaluate(`localStorage.setItem('ai-coach-os-final-prototype-v1', JSON.stringify({
    version:1,loggedIn:true,members:[{name:'Demo-Only Sentinel'}]
  }))`);
  const demoStorage = await evaluate('JSON.stringify(localStorage)');

  await login('a@example.invalid', 'wrong');
  await waitFor("document.querySelector('#loginError')?.textContent.includes('登录失败')", 'login error');
  await login('a@example.invalid', 'local-fixture');
  await contentHas('Member A');
  assert.equal(await evaluate("document.querySelector('#content').textContent.includes('Demo-Only Sentinel')"), false);
  assert.equal(await evaluate("document.querySelector('#content').textContent.includes('Member B')"), false);
  assert.equal(await evaluate("document.cookie.includes('ai_coach')"), false);
  const cookies = await send('Network.getCookies', { urls: [url] });
  assert.ok(cookies.cookies.some(cookie => cookie.name === 'ai_coach_dev_session' && cookie.httpOnly));
  assert.equal(await status('/api/v1/members/202'), 404);
  assert.equal(await status('/api/v1/members/202/training-sessions'), 404);
  assert.equal(await status('/api/v1/members?coach_id=other'), 422);

  await click('[data-action=openMember][data-id="101"]');
  for (const value of ['入会时间', '2026-11-01T08:00:00Z', '复查练习', '联系电话', '000-000',
    '<img src=x onerror=alert(1)>']) {
    await contentHas(value);
  }
  assert.equal(await evaluate("document.querySelector('#content img') === null"), true);
  assert.equal(await evaluate("document.querySelector('#content').textContent.includes('剩余课时0')"), true);
  await click('[data-action=history]');
  await contentHas('2026-11-14');
  await click('#content .stack details summary');
  for (const value of ['会员反馈样例', '教练备注样例', '深蹲', '30 kg', 'RPE', '动作备注样例']) {
    await contentHas(value);
  }
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), true);
  for (const [name, confirmation] of [['动作一', '当日首条'], ['动作二', '未重复扣课']]) {
    await click('#content details:has(form) summary');
    await evaluate(`document.querySelector('#content [name=exercise_name]').value = ${JSON.stringify(name)};
      { const editor = document.querySelector('#content form'); editor.requestSubmit(); editor.requestSubmit(); }`);
    await contentHas(confirmation);
    await contentHas(name);
    assert.equal(await evaluate(`[...document.querySelectorAll('#content td')].filter(td => td.textContent === ${JSON.stringify(name)}).length`), 1);
  }
  await click('#content [data-page=members]');
  await contentHas('Member A');
  await evaluate("window.oldDocument = true");
  await send('Page.reload');
  await waitFor("!window.oldDocument && document.querySelector('#content')?.textContent.includes('Member A')", 'cookie restore after reload');
  assert.equal(await evaluate('JSON.stringify(localStorage)'), demoStorage);

  await send('Network.setBlockedURLs', { urls: [origin + '/api/v1/members/101'] });
  await click('[data-action=openMember][data-id="101"]');
  await contentHas('无法连接服务');
  await send('Network.setBlockedURLs', { urls: [] });
  await click('[data-action=retry]');
  await contentHas('复查练习');

  await send('Network.setBlockedURLs', { urls: [origin + '/api/v1/auth/logout'] });
  await click('.mobile-top [data-action=menu]');
  await click('#modalRoot [data-action=logout]');
  await waitFor("document.querySelector('#loginError')?.textContent.includes('退出未确认')", 'logout network error');
  assert.equal(await evaluate("document.querySelector('#content').textContent"), '');
  assert.equal(await evaluate("document.querySelector('#loginForm button[type=submit]').disabled"), true);
  await send('Network.setBlockedURLs', { urls: [] });
  await click('#loginError + button');
  await waitFor("document.querySelector('#loginError')?.textContent.includes('已退出登录')", 'logout confirmed');
  assert.equal(await status('/api/v1/members'), 401);
  assert.equal(await evaluate("document.querySelector('#content').textContent"), '');
  await login('b@example.invalid', 'local-fixture');
  await contentHas('Member B');
  assert.equal(await status('/api/v1/members/101'), 404);
  assert.equal(await status('/api/v1/members/101/training-sessions'), 404);
  assert.equal(await evaluate("document.body.textContent.includes('Member A')"), false);
  assert.equal(await evaluate('JSON.stringify(localStorage)'), demoStorage);
  assert.equal(await evaluate('sessionStorage.length'), 0);
  assert.equal(runtimeErrors.length, 0);

  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await click('#desktopNav [data-page=history]');
  await contentHas('请选择会员后查看训练记录');
  await send('Page.navigate', { url: pathToFileURL(resolve('prototype/ai_coach_os_coach_final.html')).href });
  await waitFor("location.protocol === 'file:' && document.querySelector('#loginEmail')?.value === 'coach@example.com'", 'standalone demo boot');
  await evaluate("document.querySelector('#loginForm').requestSubmit()");
  await waitFor("state.loggedIn && state.page === 'dashboard'", 'demo login');
  assert.equal(await evaluate("JSON.stringify(localStorage) !== '{}'"), true);
  console.log('PASS: Connected Chrome login, mobile training save/readback, double submit, same-day receipts, history, reload, logout, authorization and storage isolation; standalone Demo boot.');
} finally {
  connection?.close();
  try { await stop(browser); } finally { await stop(server); }
  const resolved = await realpath(profile);
  assert.equal(dirname(resolved), tempRoot);
  assert.ok(resolved.startsWith(join(tempRoot, 'coach-connected-')));
  await rm(resolved, { recursive: true, force: true, maxRetries: 10, retryDelay: 150 });
}
