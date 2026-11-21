import { ApiError, request } from './api.js';
import { showTrainingForm } from './training.js';

export function startWorkspace({ esc, btn, title, empty, openModal, closeModal, navItems }) {
  const byId = id => document.getElementById(id);
  const login = byId('login');
  const form = byId('loginForm');
  const submit = form.querySelector('[type=submit]');
  const password = byId('loginPassword');
  const app = byId('app');
  const content = byId('content');
  const notice = byId('loginError');
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'btn hidden';
  retry.textContent = '重试';
  notice.after(retry);

  let coach = null;
  let members = [];
  let page = 'members';
  let selectedId = null;
  let readController = null;
  let authBusy = false;
  let pendingLogout = false;

  app.querySelector('.demo-tag').textContent = '联网模式';
  app.querySelector('.coach-badge strong').textContent = '当前教练';
  app.querySelector('.topbar .avatar').setAttribute('aria-label', '当前教练');
  app.querySelector('[data-action=reset]').remove();
  app.querySelector('[data-action=notifications]').remove();

  const nav = navItems.map(item => item[0] === 'training' ? ['history', item[1], '训练历史'] : item);
  const names = { dashboard: '首页', members: '会员', member: '会员详情', history: '训练历史', schedule: '日程', ai: 'AI 分析' };
  const goButton = (label, destination, kind = '') => btn(label, 'go', kind, `data-page="${destination}"`);
  const display = value => esc(value === null || value === undefined || value === '' ? '未填写' : value);
  const errorMessage = error => error instanceof ApiError ? error.message : '无法显示工作台数据，请重试。';
  const validId = value => Number.isSafeInteger(Number(value)) && /^[1-9]\d*$/.test(String(value));
  const memberButton = id => validId(id) ? btn('查看', 'openMember', 'small', `data-id="${esc(id)}"`) : '';

  function loginNotice(message = '', retryAction = null) {
    notice.textContent = message;
    notice.classList.toggle('hidden', !message);
    retry.onclick = retryAction;
    retry.classList.toggle('hidden', !retryAction);
  }

  function clearWorkspace() {
    readController?.abort();
    readController = null;
    coach = null;
    members = [];
    page = 'members';
    selectedId = null;
    content.replaceChildren();
    closeModal();
    app.classList.add('hidden');
    login.classList.remove('hidden');
    form.reset();
  }

  async function authOperation(operation) {
    if (authBusy) return;
    authBusy = true;
    submit.disabled = true;
    retry.disabled = true;
    try {
      await operation();
    } finally {
      authBusy = false;
      submit.disabled = pendingLogout;
      retry.disabled = false;
    }
  }

  async function restore() {
    await authOperation(async () => {
      loginNotice('正在检查登录状态…');
      try {
        coach = await request('/auth/me');
        pendingLogout = false;
        loginNotice();
        login.classList.add('hidden');
        app.classList.remove('hidden');
        navigate('members');
      } catch (error) {
        clearWorkspace();
        if (error.status === 401) loginNotice();
        else loginNotice(errorMessage(error), restore);
      }
    });
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pendingLogout) return;
    await authOperation(async () => {
      const credentials = { email: byId('loginEmail').value.trim(), password: password.value };
      password.value = '';
      loginNotice('正在登录…');
      try {
        await request('/auth/login', { method: 'POST', body: credentials });
        credentials.password = '';
        coach = await request('/auth/me');
        loginNotice();
        login.classList.add('hidden');
        app.classList.remove('hidden');
        navigate('members');
      } catch (error) {
        clearWorkspace();
        loginNotice(errorMessage(error));
      } finally {
        credentials.password = '';
      }
    });
  });

  async function logout() {
    if (authBusy) return;
    clearWorkspace();
    pendingLogout = true;
    await authOperation(async () => {
      loginNotice('正在退出…');
      try {
        await request('/auth/logout', { method: 'POST' });
        pendingLogout = false;
        loginNotice('已退出登录。');
      } catch (error) {
        loginNotice('退出未确认，请重试。' + errorMessage(error), logout);
      }
    });
  }

  function shell() {
    const active = page === 'member' ? 'members' : page;
    byId('desktopNav').innerHTML = nav.map(([id, icon, label]) =>
      `<button type="button" data-action="go" data-page="${id}" class="${active === id ? 'active' : ''}">${icon}　${label}</button>`
    ).join('');
    byId('mobileNav').innerHTML = nav.map(([id, icon, label]) =>
      `<button type="button" data-action="go" data-page="${id}" class="${active === id ? 'active' : ''}"><b>${icon}</b>${label}</button>`
    ).join('');
    byId('topTitle').textContent = names[page];
    byId('mobileTitle').textContent = names[page];
    byId('sideStatus').textContent = '会员与训练历史';
  }

  function rows(query = '', order = 'recent') {
    const keyword = query.trim().toLowerCase();
    const filtered = members.filter(member => [member.name, member.goal].some(
      value => String(value ?? '').toLowerCase().includes(keyword)
    ));
    if (order === 'name') filtered.sort((first, second) => first.name.localeCompare(second.name, 'zh-CN'));
    else if (order === 'lessons') filtered.sort((first, second) => first.remaining_lessons - second.remaining_lessons);
    else filtered.sort((first, second) => (second.last_training_date ?? '').localeCompare(first.last_training_date ?? ''));
    if (!filtered.length) return empty(members.length ? '没有找到符合条件的会员。' : '暂无会员。');
    return filtered.map(member => `<div class="row">
      <div class="avatar" aria-hidden="true">${esc(member.name.slice(0, 1))}</div>
      <div class="row-main"><strong>${esc(member.name)}</strong><small>${display(member.goal)} ·
        ${member.last_training_date ? '最近训练 ' + esc(member.last_training_date) : '暂无训练日期'}</small></div>
      <span class="pill ${member.remaining_lessons <= 3 ? 'warn' : ''}">剩余 ${display(member.remaining_lessons)} 节</span>
      <div class="row-actions">${memberButton(member.id)}</div>
    </div>`).join('');
  }

  function renderMembers() {
    content.innerHTML = title('会员管理', '选择会员后可查看档案、训练历史和课时。') + `
      <div class="toolbar">
        <input id="connectedSearch" class="input" type="search" placeholder="搜索姓名 / 训练目标" aria-label="搜索会员">
        <select id="connectedSort" aria-label="会员排序"><option value="recent">最近训练</option>
          <option value="lessons">剩余课时</option><option value="name">姓名</option></select>
      </div><div class="card" id="connectedMembers">${rows()}</div>`;
    const update = () => { byId('connectedMembers').innerHTML = rows(byId('connectedSearch').value, byId('connectedSort').value); };
    byId('connectedSearch').addEventListener('input', update);
    byId('connectedSort').addEventListener('change', update);
  }

  function detailLine(label, value) {
    return `<div class="detail-line connected-detail"><span>${label}</span><strong>${display(value)}</strong></div>`;
  }

  function renderMember(member) {
    const history = btn('查看训练历史', 'history', 'primary', `data-id="${esc(selectedId)}"`);
    content.innerHTML = title(esc(member.name), '会员档案', goButton('返回会员', 'members') + history) + `
      <div class="grid cols-2">
        <section class="card"><h3>会员信息</h3>
          ${detailLine('头像标识', member.avatar_emoji)}
          ${detailLine('入会时间', member.created_at)}
          ${detailLine('联系电话', member.phone)}
          ${detailLine('备注', member.note)}
        </section>
        <section class="card"><h3>课程状态</h3>
          ${detailLine('剩余课时', member.remaining_lessons)}
          ${detailLine('训练目标', member.goal)}
          ${detailLine('最近训练日期', member.last_training_date)}
          ${detailLine('AI 提醒', member.ai_reminder)}
        </section>
      </div>`;
  }

  function renderHistory(records, confirmation) {
    const fieldNames = ['exercise_name', 'weight', 'sets', 'reps', 'rpe', 'note'];
    const buttons = goButton('返回会员', 'members') + (selectedId ?
      btn('会员详情', 'openMember', '', `data-id="${esc(selectedId)}"`) : '');
    content.innerHTML = title('训练历史', '查看指定会员的训练记录。', buttons) + `
      <div class="toolbar"><select id="connectedHistoryMember" aria-label="选择会员">
        <option value="">选择会员</option>
        ${members.filter(member => validId(member.id)).map(member =>
          `<option value="${esc(member.id)}" ${String(member.id) === selectedId ? 'selected' : ''}>${esc(member.name)}</option>`
        ).join('')}
      </select></div>
      <div class="stack">${!selectedId ? empty(members.length ? '请选择会员后查看训练记录。' : '暂无会员。') :
        records.length ? records.map(record => `<details class="card">
          <summary><strong>${display(record.training_date)}</strong></summary>
          ${detailLine('会员反馈', record.member_feedback)}
          ${detailLine('教练备注', record.coach_note)}
          ${record.exercises.length ? `<div class="table-wrap"><table class="data-table"><thead>
            <tr><th>动作</th><th>重量</th><th>组数</th><th>次数</th><th>RPE</th><th>动作备注</th></tr>
          </thead><tbody>${record.exercises.map(exercise => `<tr>${fieldNames.map(
            field => `<td>${display(exercise[field])}</td>`
          ).join('')}</tr>`).join('')}</tbody></table></div>` : empty('此记录没有动作。')}
        </details>`).join('') : empty('该会员暂无训练记录。')}</div>`;
    if (confirmation) {
      const message = document.createElement('p');
      message.setAttribute('role', 'status');
      message.textContent = confirmation;
      content.prepend(message);
    }
    if (selectedId) {
      const editor = document.createElement('details');
      editor.className = 'card';
      editor.innerHTML = '<summary>新增训练记录</summary><div></div>';
      content.querySelector('.toolbar').after(editor);
      const memberId = selectedId;
      const member = members.find(item => String(item.id) === memberId);
      editor.querySelector('summary').textContent = '新增训练记录 · ' + (member?.name ?? memberId);
      showTrainingForm(editor.querySelector('div'), memberId, {
        saved: result => navigate('history', memberId, result.should_deduct_lesson
          ? '记录已保存，已按当日首条规则结算课时。' : '记录已保存，今日未重复扣课。'),
        expired: message => { clearWorkspace(); loginNotice(message); },
        history: () => navigate('history', memberId),
      });
    }
    byId('connectedHistoryMember').addEventListener('change', event => navigate('history', event.target.value));
  }

  async function navigate(destination, id = null, confirmation = '') {
    if (!coach || !Object.hasOwn(names, destination)) return;
    if (id && !validId(id)) return;
    readController?.abort();
    const controller = new AbortController();
    readController = controller;
    page = destination;
    selectedId = id ? String(id) : null;
    const options = { signal: controller.signal };
    const active = () => readController === controller && !controller.signal.aborted;
    closeModal();
    shell();
    window.scrollTo(0, 0);
    content.innerHTML = title(names[page], '') + '<div class="card" role="status">正在加载…</div>';
    try {
      if (destination === 'members') {
        members = [];
        const data = await request('/members', options);
        if (!active()) return;
        members = data;
        renderMembers();
      } else if (destination === 'member' && id) {
        const member = await request('/members/' + encodeURIComponent(id), options);
        if (active()) renderMember(member);
      } else if (destination === 'history') {
        const records = id ? await request('/members/' + encodeURIComponent(id) + '/training-sessions', options) : [];
        if (active()) renderHistory(records, confirmation);
      } else {
        content.innerHTML = title(names[page], '', goButton('查看会员', 'members')) +
          '<div class="card">此页面的数据暂未接入联网模式。</div>';
      }
    } catch (error) {
      if (!active()) return;
      if (error.status === 401 || error.code === 'COACH_NOT_ALLOWED') {
        clearWorkspace();
        loginNotice(errorMessage(error));
        return;
      }
      content.innerHTML = title(names[page], '', goButton('返回会员', 'members')) +
        `<div class="card"><p class="notice error" role="alert">${esc(errorMessage(error))}</p>
           ${btn('重试', 'retry')}</div>`;
      content.querySelector('[data-action=retry]').onclick = () => navigate(destination, id);
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (!button || !coach) return;
    const { action, id } = button.dataset;
    if (action === 'go') navigate(button.dataset.page);
    else if (action === 'openMember' && id) navigate('member', id);
    else if (action === 'history') navigate('history', id);
    else if (action === 'logout') logout();
    else if (action === 'closeModal' || (action === 'closeBackdrop' && button === event.target)) closeModal();
    else if (action === 'menu') {
      openModal('更多操作', `<div class="stack">${goButton('训练历史', 'history')}${btn('退出登录', 'logout', 'danger')}</div>`);
    } else if (action === 'search') {
      if (page === 'members' && byId('connectedSearch')) byId('connectedSearch').focus();
      else navigate('members');
    }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });
  window.addEventListener('pagehide', clearWorkspace);
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  restore();
}
