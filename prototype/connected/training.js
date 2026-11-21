import { request } from './api.js';

export function showTrainingForm(host, memberId, { saved, expired, history }) {
  host.innerHTML = `<form class="card stack">
    <h3>记录本次训练</h3>
    <label>训练日期<input type="date" name="training_date" required></label>
    <div class="stack" data-exercises></div>
    <button type="button" class="btn" data-add>添加动作</button>
    <label>会员反馈<textarea name="member_feedback" maxlength="2000"></textarea></label>
    <label>教练备注<textarea name="coach_note" maxlength="2000"></textarea></label>
    <p>同一会员同一训练日期仅首条记录扣一节，余额最低为零。</p>
    <button type="submit" class="btn primary">保存训练记录</button>
    <p role="status"></p></form>`;
  const form = host.querySelector('form');
  const exercises = form.querySelector('[data-exercises]');
  const add = form.querySelector('[data-add]');
  const submit = form.querySelector('[type=submit]');
  const status = form.querySelector('[role=status]');
  const today = new Date();
  form.elements.training_date.value = new Date(today - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  function addExercise() {
    const row = document.createElement('fieldset');
    row.className = 'stack';
    row.innerHTML = `<legend>训练动作</legend>
      <label>动作名称<input name="exercise_name" maxlength="120" required pattern=".*\\S.*"></label>
      <label>重量<input name="weight" maxlength="40" placeholder="例如 20 kg"></label>
      <label>组数<input name="sets" maxlength="40"></label>
      <label>次数<input name="reps" maxlength="40"></label>
      <label>RPE<input name="rpe" maxlength="20"></label>
      <label>动作备注<input name="note" maxlength="500"></label>`;
    if (exercises.children.length) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn';
      remove.textContent = '移除此动作';
      remove.onclick = () => { row.remove(); add.disabled = false; };
      row.append(remove);
    }
    exercises.append(row);
    add.disabled = exercises.children.length >= 40;
  }
  addExercise();
  add.onclick = addExercise;
  form.onsubmit = async event => {
    event.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    status.textContent = '正在保存…';
    const body = {
      training_date: form.elements.training_date.value,
      member_feedback: form.elements.member_feedback.value,
      coach_note: form.elements.coach_note.value,
      exercises: [...exercises.children].map(row =>
        Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.name, input.value.trim()]))),
    };
    try {
      const result = await request('/members/' + memberId + '/training-sessions', { method: 'POST', body });
      if (form.isConnected) saved(result);
    } catch (error) {
      if (!form.isConnected) return;
      if (error.status === 401 || error.code === 'COACH_NOT_ALLOWED') return expired(error.message);
      if (error.status === 422) {
        submit.disabled = false;
        status.textContent = '请检查日期和动作名称后重新保存。';
      } else {
        status.textContent = '保存未确认，请先查看训练历史，核对后再决定是否重新录入。';
        const check = document.createElement('button');
        check.type = 'button';
        check.className = 'btn';
        check.textContent = '核对训练历史';
        check.onclick = history;
        status.append(check);
      }
    }
  };
}
