import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const source = readFileSync(resolve('prototype/ai_coach_os_coach_final.html'), 'utf8');
const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const scratch = mkdtempSync(join(tmpdir(), 'coach-prototype-'));
const profile = join(scratch, 'profile');
const htmlPath = join(scratch, 'prototype-test.html');
const screenshots = resolve('prototype/qa');
mkdirSync(screenshots, { recursive: true });

const test = `
<script>
try {
  const phase = new URL(location.href).searchParams.get('phase');
  const check = (ok, text) => { if (!ok) throw Error(text); };
  if (phase === 'flow') {
    document.querySelector('#loginPassword').value = 'wrong';
    document.querySelector('#loginForm').requestSubmit();
    check(!document.querySelector('#loginError').classList.contains('hidden'), 'invalid login feedback');
    document.querySelector('#loginPassword').value = '123456';
    document.querySelector('#loginForm').requestSubmit();
    check(state.loggedIn && state.page === 'dashboard', 'login');
    document.querySelector('[data-action=startTraining][data-id=m1]').click();
    check(state.page === 'training', 'start training');
    const name = document.querySelector('.exercise-input[data-field=name]');
    const reps = document.querySelector('.exercise-input[data-field=reps]');
    name.value = '杠铃卧推'; reps.value = '8/8/8';
    name.dispatchEvent(new Event('input', { bubbles: true }));
    reps.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('[data-action=saveTraining]').click();
    check(member('m1').lessons === 7, 'first save deducts once');
    check(state.sessions.filter(s => s.memberId === 'm1').length === 2, 'new session saved');
    document.querySelector('[data-action=saveTraining]').click();
    check(member('m1').lessons === 7, 'update does not deduct twice');
    check(state.appointments.find(a => a.id === 'a1').status === 'completed', 'appointment completion');
    document.querySelector('[data-action=generateAI]').click();
    check(state.page === 'ai' && allPending().length === 1 && state.plans.length === 0, 'AI waits for confirmation');
    document.querySelector('[data-action=confirmAI]').click();
    check(allPending().length === 0 && state.plans.length === 1, 'confirmation creates plan');
    startTraining('m1');
    const secondName = document.querySelector('.exercise-input[data-field=name]');
    const secondReps = document.querySelector('.exercise-input[data-field=reps]');
    secondName.value = '坐姿划船'; secondReps.value = '10/10/10';
    secondName.dispatchEvent(new Event('input', { bubbles: true }));
    secondReps.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('[data-action=saveTraining]').click();
    check(member('m1').lessons === 7, 'second same-day record does not deduct twice');
    go('ai');
  } else if (phase === 'refresh') {
    check(state.loggedIn && member('m1').lessons === 7 && state.plans.length === 1, 'local persistence');
    check(getComputedStyle(document.querySelector('.mobile-nav')).display !== 'none', 'mobile navigation');
    check(getComputedStyle(document.querySelector('.page-head .actions')).display !== 'none', 'mobile actions');
    document.querySelector('#mobileNav [data-page=members]').click();
    check(state.page === 'members', 'mobile navigation action');
    check(document.documentElement.scrollWidth <= innerWidth + 1, 'mobile horizontal overflow');
  } else if (phase === 'extras') {
    check(weekStart('2026-09-14') === weekStart('2026-09-20'), 'week range');
    check(weekStart('2026-09-14') !== weekStart('2026-09-21'), 'next week boundary');
    document.querySelector('[data-action=newMember]').click();
    document.querySelector('#mName').value = '测试会员';
    document.querySelector('#mGoal').value = '力量提升';
    document.querySelector('#memberForm').requestSubmit();
    check(state.members.some(m => m.name === '测试会员'), 'member creation');
    go('schedule');
    document.querySelector('[data-action=newAppointment]').click();
    document.querySelector('#aDate').value = addDays(1);
    document.querySelector('#aTime').value = '17:00';
    document.querySelector('#appointmentForm').requestSubmit();
    check(state.appointments.some(a => a.memberId === current().id && a.time === '17:00'), 'appointment creation');
    startTraining(current().id);
    document.querySelector('[data-action=smartPaste]').click();
    document.querySelector('#pasteText').value = '杠铃卧推 65kg 4x8';
    document.querySelector('#pasteForm').requestSubmit();
    check(draft().exercises[0].name === '杠铃卧推', 'smart paste');
  } else if (phase === 'reset') {
    document.querySelector('[data-action=reset]').click();
    document.querySelector('[data-action=confirmReset]').click();
    check(!state.loggedIn && member('m1').lessons === 8 && state.plans.length === 0, 'reset');
  }
  const result = document.createElement('pre'); result.id = 'qa-result'; result.textContent = phase + ':PASS'; document.body.append(result);
} catch (error) {
  const result = document.createElement('pre'); result.id = 'qa-result'; result.textContent = 'FAIL:' + error.message; document.body.append(result);
}
</script>`;
writeFileSync(htmlPath, source.replace('</body>', `${test}\n</body>`), 'utf8');

try {
  for (const [phase, size, screenshot] of [
    ['flow', '1440,900', 'desktop-ai.png'],
    ['refresh', '500,844', 'mobile-members.png'],
    ['extras', '1440,900', null],
    ['reset', '500,844', null],
  ]) {
    const args = ['--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run', '--disable-extensions', `--user-data-dir=${profile}`, `--window-size=${size}`, '--virtual-time-budget=1500', '--dump-dom'];
    if (screenshot) args.push(`--screenshot=${join(screenshots, screenshot)}`);
    args.push(`${pathToFileURL(htmlPath).href}?phase=${phase}`);
    const run = spawnSync(chrome, args, { encoding: 'utf8', maxBuffer: 20_000_000, windowsHide: true });
    assert.equal(run.status, 0, `Chrome failed: ${run.stderr?.slice(-500)}`);
    const result = run.stdout.match(/<pre id="qa-result">([^<]+)<\/pre>/)?.[1];
    assert.equal(result, `${phase}:PASS`, `${phase}: ${result || 'missing result'}`);
  }
  console.log('Prototype checks passed: login, training, single deduction, AI confirmation, persistence, mobile actions, member and appointment forms, smart paste, reset.');
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
