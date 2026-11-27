'use strict';

/* SalesNote 화면. 빌드 과정 없이 도는 단일 페이지. 주소(#)에 화면과 필터 상태를 담는다. */

const S = { me: null, meta: null, auth: null, nav: 0, tlFilter: {} };
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- 공통 ---------- */

async function api(method, url, body) {
  const opt = { method, headers: { 'X-SalesNote': '1' }, credentials: 'same-origin' };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(url, opt);
  const data = (res.headers.get('content-type') || '').includes('json') ? await res.json() : null;
  if (res.ok) return data;
  const d = data && data.detail;
  const message = typeof d === 'string' ? d
    : Array.isArray(d) ? d.map(x => x.msg.replace(/^Value error, /, '')).join(', ')
    : (d && d.message) || '요청을 처리하지 못했습니다.';
  const error = Object.assign(new Error(message), { status: res.status, detail: d });
  if (res.status === 401 && S.me) { S.me = null; route(); }
  throw error;
}

function toast(message, isError) {
  const el = document.createElement('div');
  el.textContent = message;
  if (isError) el.className = 'err';
  $('#toast').append(el);
  setTimeout(() => el.remove(), isError ? 4500 : 2400);
}
window.addEventListener('unhandledrejection', e => {
  if (e.reason && e.reason.status === 401) return;
  toast((e.reason && e.reason.message) || '오류가 발생했습니다.', true);
});

const pad = n => String(n).padStart(2, '0');
const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
function fmtDT(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const year = d.getFullYear() === new Date().getFullYear() ? '' : d.getFullYear() + '.';
  return `${year}${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function ago(iso) {
  const min = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return '방금';
  if (min < 60) return min + '분 전';
  if (min < 1440) return Math.floor(min / 60) + '시간 전';
  if (min < 43200) return Math.floor(min / 1440) + '일 전';
  return fmtDT(iso).split(' ')[0];
}
const won = n => (n == null ? '' : Number(n).toLocaleString('ko-KR') + '원');
function wonShort(n) {
  if (n == null) return '';
  if (n >= 1e8) return (Math.round(n / 1e7) / 10).toLocaleString('ko-KR') + '억';
  if (n >= 1e4) return Math.round(n / 1e4).toLocaleString('ko-KR') + '만';
  return n.toLocaleString('ko-KR') + '원';
}
const fmtSize = b => (b < 1024 ? b + 'B' : b < 1048576 ? Math.round(b / 1024) + 'KB' : (b / 1048576).toFixed(1) + 'MB');
const PROB = { high: '상', mid: '중', low: '하' };
const DASH = '<span class="muted">-</span>';

const codes = kind => S.meta.codes[kind] || [];
const codeName = (kind, code) => {
  if (!code) return '';
  const hit = codes(kind).find(c => c.code === code);
  return hit ? hit.name : code;
};
const stageBadge = code => `<span class="stage s-${esc(code)}">${esc(codeName('stage', code))}</span>`;
const userLabel = u => (u ? esc(u.name) : '-');
const options = (list, selected, placeholder) =>
  (placeholder != null ? `<option value="">${esc(placeholder)}</option>` : '') +
  list.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(selected ?? '') ? ' selected' : ''}>${esc(l)}</option>`).join('');
const userOptions = (selected, placeholder) =>
  options(S.meta.users.map(u => [u.id, u.name + (u.title ? ' ' + u.title : '')]), selected, placeholder);
const codeOptions = (kind, selected, placeholder) =>
  options(codes(kind).filter(c => c.is_active || c.code === selected).map(c => [c.code, c.name]), selected, placeholder);

function amountCell(o, field = 'amount_expected', short = true) {
  if (o.amount_hidden) return '<span class="muted" title="담당자·참여자·관리자만 볼 수 있습니다">비공개</span>';
  const v = o[field];
  return v == null ? DASH : esc(short ? wonShort(v) : won(v));
}
function hl(text, q) {
  text = String(text ?? '');
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + '<mark>' + esc(text.slice(i, i + q.length)) + '</mark>' + esc(text.slice(i + q.length));
}
function mentionize(text) {
  let out = esc(text);
  for (const u of S.meta.users) {
    if (u.name) out = out.split('@' + esc(u.name)).join(`<span class="mention">@${esc(u.name)}</span>`);
  }
  return out;
}
const splitList = v => String(v || '').split(/[,\n]/).map(s => s.trim()).filter(Boolean);
const moneyVal = el => { const digits = (el.value || '').replace(/\D/g, ''); return digits ? Number(digits) : null; };
const moneyStr = n => (n == null ? '' : Number(n).toLocaleString('ko-KR'));
document.addEventListener('input', e => {
  if (e.target.matches && e.target.matches('[data-money]')) {
    const digits = e.target.value.replace(/\D/g, '');
    e.target.value = digits ? Number(digits).toLocaleString('ko-KR') : '';
  }
});

/* 서식 텍스트 편집기 */
function editor(name, html, placeholder) {
  const buttons = [['bold', '굵게'], ['italic', '기울임'], ['underline', '밑줄'], ['insertUnorderedList', '• 목록'], ['insertOrderedList', '1. 목록']];
  return `<div class="editor" data-editor="${name}">
    <div class="editor-bar">${buttons.map(([c, l]) => `<button type="button" data-cmd="${c}" tabindex="-1">${l}</button>`).join('')}</div>
    <div class="editor-body rich" contenteditable="true" data-placeholder="${esc(placeholder || '')}">${html || ''}</div>
  </div>`;
}
function editorValue(root, name) {
  const body = $(`[data-editor="${name}"] .editor-body`, root);
  return body.textContent.trim() ? body.innerHTML : '';
}
document.addEventListener('mousedown', e => {
  const btn = e.target.closest && e.target.closest('[data-cmd]');
  if (!btn) return;
  e.preventDefault();
  document.execCommand(btn.dataset.cmd);
});
document.addEventListener('paste', e => {
  if (!(e.target.closest && e.target.closest('.editor-body'))) return;
  e.preventDefault();
  document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
});

function modal(html, onMount) {
  const root = $('#modal-root');
  root.innerHTML = `<div class="modal-back"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`;
  const close = () => { root.innerHTML = ''; };
  const back = root.firstChild;
  back.addEventListener('mousedown', e => { if (e.target === back) close(); });
  $$('[data-close]', root).forEach(b => b.addEventListener('click', close));
  if (onMount) onMount($('.modal', root), close);
  const first = $('.modal input, .modal select, .modal textarea, .modal [contenteditable]', root);
  if (first) first.focus();
  return close;
}
function confirmBox(message, okLabel = '확인', danger = false) {
  return new Promise(resolve => {
    modal(`<h2>${esc(message)}</h2><div class="foot" style="margin-top:20px">
      <button class="btn" data-no>취소</button>
      <button class="btn ${danger ? 'danger' : 'primary'}" data-yes>${esc(okLabel)}</button></div>`,
    (el, close) => {
      $('[data-no]', el).onclick = () => { close(); resolve(false); };
      $('[data-yes]', el).onclick = () => { close(); resolve(true); };
    });
  });
}

/* ---------- 라우터 ---------- */

function parseHash() {
  const hash = location.hash.slice(1) || '/';
  const i = hash.indexOf('?');
  return { path: i < 0 ? hash : hash.slice(0, i), params: new URLSearchParams(i < 0 ? '' : hash.slice(i + 1)) };
}
function withParams(params, changes) {
  const p = new URLSearchParams(params);
  for (const [k, v] of Object.entries(changes)) {
    if (v === '' || v == null) p.delete(k); else p.set(k, v);
  }
  return p;
}
function go(path, params) {
  const s = params ? new URLSearchParams(params).toString() : '';
  const hash = '#' + path + (s ? '?' + s : '');
  if (location.hash === hash) route(); else location.hash = hash;
}
function mount(html) {
  const root = document.createElement('div');
  root.innerHTML = html;
  $('#app').replaceChildren(root);
  return root;
}

async function boot() {
  try {
    const res = await fetch('/api/meta', { credentials: 'same-origin' });
    if (!res.ok) return false;
    S.meta = await res.json();
    S.me = S.meta.me;
    pollUnread();
    return true;
  } catch (e) {
    return false;
  }
}
async function refreshMeta() {
  S.meta = await api('GET', '/api/meta');
  S.me = S.meta.me;
}
async function pollUnread() {
  if (!S.me) return;
  try {
    const res = await fetch('/api/notifications/count', { credentials: 'same-origin' });
    if (res.status === 401) { S.me = null; return route(); }
    const { unread } = await res.json();
    const el = $('#unread');
    el.hidden = !unread;
    el.textContent = unread > 99 ? '99+' : unread;
  } catch (e) { /* 다음 주기에 다시 시도 */ }
}
setInterval(pollUnread, 60000);

function shell(nav) {
  $('#top').hidden = false;
  $$('#nav a').forEach(a => a.classList.toggle('on', a.dataset.nav === nav));
  $('[data-admin]').hidden = S.me.role !== 'admin';
  $('#me-link').innerHTML = `<div class="avatar">${esc((S.me.name || '?').slice(0, 1))}</div><span>${esc(S.me.name)}</span>`;
}

async function route(keepScroll) {
  const token = ++S.nav;
  const { path, params } = parseHash();
  if (!S.me && !(await boot())) return viewLogin(params);
  if (token !== S.nav) return;
  if (path === '/login') return go('/');
  const hit = ROUTES.map(([re, view, nav]) => ({ m: path.match(re), view, nav })).find(r => r.m);
  if (!hit) return go('/');
  shell(hit.nav);
  const y = window.scrollY;
  let out;
  try {
    out = await hit.view({ params, path, arg: hit.m[1] });
  } catch (e) {
    if (token !== S.nav || e.status === 401) return;
    mount(`<div class="card empty">${esc(e.message)}<div style="margin-top:14px"><a class="btn" href="#/">목록으로</a></div></div>`);
    return;
  }
  if (token !== S.nav || !out) return;
  const root = mount(out.html);
  if (out.bind) out.bind(root);
  window.scrollTo(0, keepScroll === true ? y : 0);
}
const reload = () => route(true);
window.addEventListener('hashchange', () => route());

/* ---------- SC-01 로그인 ---------- */

async function viewLogin(params) {
  $('#top').hidden = true;
  if (!S.auth) S.auth = await (await fetch('/auth/config')).json();
  const error = {
    not_allowed: '접근이 허용되지 않은 계정입니다. 관리자에게 등록을 요청하세요.',
    failed: '로그인하지 못했습니다. 다시 시도하세요.',
  }[params.get('error')];
  const root = mount(`<div class="login"><div class="card box">
    <div class="brand">Sales<span>Note</span></div>
    <p>영업기회를 처음부터 끝까지 기록하고 공유합니다.</p>
    ${error ? `<div class="error-box">${error}</div>` : ''}
    ${S.auth.google ? '<a class="btn primary" href="/auth/login">구글 계정으로 로그인</a>'
      : '<div class="hint">구글 로그인이 설정되지 않았습니다. GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 설정하세요.</div>'}
    ${S.auth.dev_login ? `<div class="sep">개발용 로그인</div>
      <form id="dev"><input name="email" type="email" placeholder="허용된 계정 메일" required>
      <button class="btn" style="margin-top:8px">메일로 로그인</button></form>` : ''}
    <div class="hint" style="margin-top:18px">관리자가 허용한 VX 사업부 계정만 사용할 수 있습니다.</div>
  </div></div>`);
  const form = $('#dev', root);
  if (form) form.addEventListener('submit', async e => {
    e.preventDefault();
    await api('POST', '/auth/dev-login', { email: form.email.value });
    go('/');
  });
}

/* ---------- SC-02 영업기회 목록 ---------- */

const QUICK = [['', '진행 중 전체'], ['mine', '내 담당'], ['joined', '내가 참여'], ['watching', '관심 등록'], ['closed', '종료']];
const viewTabs = on => `<div class="tabs">
  <a href="#/" class="${on === 'list' ? 'on' : ''}">목록</a><a href="#/board" class="${on === 'board' ? 'on' : ''}">보드</a></div>`;
const todoCell = t => {
  if (!t) return DASH;
  const overdue = t.due_date && t.due_date < today();
  return `<span class="${overdue ? 'overdue' : ''}">${esc(t.content)}</span>
    <div class="small ${overdue ? 'overdue' : 'muted'}">${t.due_date ? esc(t.due_date) + (overdue ? ' 기한 지남' : '') : '기한 없음'}</div>`;
};

async function viewList({ params }) {
  const query = withParams(params, { size: params.get('size') || 20 });
  const [data, tags] = await Promise.all([api('GET', '/api/opportunities?' + query), api('GET', '/api/tags')]);
  const q = params.get('q') || '';
  const quick = params.get('quick') || '';
  const g = k => params.get(k) || '';
  const pages = Math.max(1, Math.ceil(data.total / data.size));
  const filtered = ['stage', 'owner', 'biz_type', 'customer', 'tag', 'date_from', 'date_to', 'q'].some(k => g(k));

  const rows = data.items.map(o => `<tr class="click" data-id="${o.id}">
    <td>${stageBadge(o.stage)}</td>
    <td><div class="t-title"><a href="#/opp/${o.id}">${hl(o.title, q)}</a>
        ${o.visibility === 'private' ? '<span class="lock">비공개</span>' : ''}</div>
      ${o.match.length || o.tags.length ? `<div class="t-sub">${o.match.map(m => `<span class="tag match">${m} 일치</span>`).join('')}${o.tags.map(name => `<span class="tag">${esc(name)}</span>`).join('')}</div>` : ''}</td>
    <td>${hl(o.customer, q)}</td>
    <td class="hide-md">${esc(codeName('biz_type', o.biz_type)) || DASH}</td>
    <td class="num hide-sm">${amountCell(o)}</td>
    <td class="hide-sm">${userLabel(o.owner)}</td>
    <td class="hide-md">${todoCell(o.next_todo)}</td>
    <td class="small muted" style="white-space:nowrap">${ago(o.updated_at)}</td>
    <td class="num muted hide-md">${o.comment_count || ''}</td>
  </tr>`).join('');

  const html = `
  <div class="page-head"><h1>영업기회</h1>
    <div class="actions">${viewTabs('list')}
      <a class="btn" href="/api/opportunities/export?${withParams(params, { page: '', size: '' })}" download>엑셀 내보내기</a>
      <a class="btn primary" href="#/new">영업기회 등록</a></div></div>
  <div class="toolbar">
    <div class="tabs">${QUICK.map(([v, l]) => `<button data-quick="${v}" class="${quick === v && !g('stage') ? 'on' : ''}">${l}</button>`).join('')}</div>
    <form class="search" id="search"><input name="q" type="search" value="${esc(q)}" placeholder="제목, 고객사, 기록, 댓글 검색"></form>
  </div>
  <div class="card">
    <div class="filters">
      <select data-f="stage" aria-label="단계">${options(codes('stage').filter(c => c.is_active).map(c => [c.code, c.name]), g('stage'), '단계 전체')}</select>
      <select data-f="owner" aria-label="담당자">${userOptions(g('owner'), '담당자 전체')}</select>
      <select data-f="biz_type" aria-label="사업 유형">${codeOptions('biz_type', g('biz_type'), '유형 전체')}</select>
      <input data-f="customer" value="${esc(g('customer'))}" placeholder="고객사" aria-label="고객사">
      <select data-f="tag" aria-label="태그">${options(tags.map(name => [name, name]), g('tag'), '태그 전체')}</select>
      <input data-f="date_from" type="date" value="${esc(g('date_from'))}" title="최종 갱신일 시작" aria-label="최종 갱신일 시작">
      <input data-f="date_to" type="date" value="${esc(g('date_to'))}" title="최종 갱신일 끝" aria-label="최종 갱신일 끝">
      <select data-f="sort" aria-label="정렬">${options([['', '최근 갱신순'], ['created', '등록일순'], ['title', '제목순'], ['customer', '고객사순'], ['deadline', '제안 마감일순']].concat(S.me.role === 'admin' ? [['amount', '예상 금액순']] : []), g('sort'))}</select>
      ${filtered ? '<button class="link small" data-reset>필터 초기화</button>' : ''}
    </div>
    ${data.items.length ? `<div class="table-wrap"><table>
      <thead><tr><th>단계</th><th>제목</th><th>고객사</th><th class="hide-md">사업 유형</th><th class="hide-sm">예상 금액</th>
        <th class="hide-sm">담당자</th><th class="hide-md">다음 할 일</th><th>최종 갱신</th><th class="hide-md">댓글</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : `<div class="empty">${filtered || quick ? '조건에 맞는 영업기회가 없습니다.' : '아직 등록된 영업기회가 없습니다. 제목과 고객사만으로 먼저 올려 보세요.'}</div>`}
    <div class="pager">
      <span class="muted small">전체 ${data.total.toLocaleString()}건</span>
      <span class="right"></span>
      <button class="btn sm" data-page="${data.page - 1}" ${data.page <= 1 ? 'disabled' : ''}>이전</button>
      <span class="small num">${data.page} / ${pages}</span>
      <button class="btn sm" data-page="${data.page + 1}" ${data.page >= pages ? 'disabled' : ''}>다음</button>
      <select data-size aria-label="페이지당 건수">${options([[20, '20건'], [50, '50건'], [100, '100건']], data.size)}</select>
    </div>
  </div>`;

  return { html, bind(root) {
    const set = changes => go('/', withParams(params, { page: '', ...changes }));
    $$('[data-quick]', root).forEach(b => b.addEventListener('click', () => set({ quick: b.dataset.quick, stage: '' })));
    $$('[data-f]', root).forEach(el => el.addEventListener('change', () => set({ [el.dataset.f]: el.value.trim() })));
    $('#search', root).addEventListener('submit', e => { e.preventDefault(); set({ q: e.target.q.value.trim() }); });
    const reset = $('[data-reset]', root);
    if (reset) reset.addEventListener('click', () => go('/', quick ? { quick } : null));
    $$('[data-page]', root).forEach(b => b.addEventListener('click', () => go('/', withParams(params, { page: b.dataset.page }))));
    $('[data-size]', root).addEventListener('change', e => set({ size: e.target.value }));
    $$('tr.click', root).forEach(tr => tr.addEventListener('click', e => { if (!e.target.closest('a')) go('/opp/' + tr.dataset.id); }));
  } };
}

/* ---------- SC-03 칸반 보드 ---------- */

async function viewBoard({ params }) {
  const data = await api('GET', '/api/opportunities?' + withParams(params, { size: 500 }));
  const quick = params.get('quick') || '';
  const stages = codes('stage').filter(s => !s.terminal && s.is_active);

  const columns = stages.map(s => {
    const items = data.items.filter(o => o.stage === s.code);
    const visible = items.filter(o => !o.amount_hidden);
    const sum = visible.reduce((a, o) => a + (o.amount_expected || 0), 0);
    const sumText = !items.length ? '' : !visible.length ? '금액 비공개'
      : !sum ? '' : wonShort(sum) + (visible.length < items.length ? ' (열람 가능 건)' : '');
    return `<div class="col" data-stage="${esc(s.code)}">
      <div class="col-head">${esc(s.name)} <span class="count">${items.length}</span></div>
      <div class="col-sum num">${sumText}</div>
      ${items.map(o => `<a class="kcard" href="#/opp/${o.id}" data-id="${o.id}" draggable="${o.perms.edit}">
        <div class="k-title">${esc(o.title)}</div>
        <div class="k-meta"><span>${esc(o.customer)}</span><span class="num">${o.amount_hidden || o.amount_expected == null ? '' : wonShort(o.amount_expected)}</span></div>
        <div class="k-meta"><span>${userLabel(o.owner)}</span><span class="muted">${ago(o.updated_at)}</span></div>
        ${o.next_todo ? `<div class="k-todo ${o.next_todo.due_date && o.next_todo.due_date < today() ? 'overdue' : ''}">${esc(o.next_todo.content)}${o.next_todo.due_date ? ' · ' + esc(o.next_todo.due_date.slice(5)) : ''}</div>` : ''}
      </a>`).join('')}
    </div>`;
  }).join('');

  const html = `
  <div class="page-head"><h1>보드</h1>
    <div class="actions">${viewTabs('board')}<a class="btn primary" href="#/new">영업기회 등록</a></div></div>
  <div class="toolbar">
    <div class="tabs">${QUICK.slice(0, 4).map(([v, l]) => `<button data-quick="${v}" class="${quick === v ? 'on' : ''}">${l}</button>`).join('')}</div>
    <span class="muted small">담당하는 카드를 끌어 단계를 바꿉니다.</span>
  </div>
  <div class="board">${columns}</div>`;

  return { html, bind(root) {
    $$('[data-quick]', root).forEach(b => b.addEventListener('click', () => go('/board', b.dataset.quick ? { quick: b.dataset.quick } : null)));
    root.addEventListener('dragstart', e => {
      const card = e.target.closest('.kcard[draggable=true]');
      if (!card) return e.preventDefault();
      e.dataTransfer.setData('text/plain', card.dataset.id);
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
    });
    root.addEventListener('dragend', () => $$('.dragging, .over', root).forEach(el => el.classList.remove('dragging', 'over')));
    $$('.col', root).forEach(col => {
      col.addEventListener('dragover', e => { e.preventDefault(); col.classList.add('over'); });
      col.addEventListener('dragleave', e => { if (!col.contains(e.relatedTarget)) col.classList.remove('over'); });
      col.addEventListener('drop', async e => {
        e.preventDefault();
        col.classList.remove('over');
        const id = e.dataTransfer.getData('text/plain');
        const item = data.items.find(o => String(o.id) === id);
        if (!item || item.stage === col.dataset.stage) return;
        if ((S.meta.stage_required[col.dataset.stage] || []).length) return stageModal(id, col.dataset.stage);
        await api('POST', `/api/opportunities/${id}/stage`, { stage: col.dataset.stage });
        toast('단계를 변경했습니다.');
        reload();
      });
    });
  } };
}

/* ---------- SC-06 단계 변경 창 ---------- */

async function stageModal(id, stage, direct = false) {
  const { opp: o } = await api('GET', `/api/opportunities/${id}`);
  const L = S.meta.field_labels;
  const fields = [...(S.meta.stage_required[stage] || [])];
  if (stage === 'lost') fields.push('close_reason_text');
  const reopening = codes('stage').some(s => s.code === o.stage && s.terminal) && !['won', 'lost', 'hold'].includes(stage);

  const input = f => {
    const label = { close_reason_text: stage === 'hold' ? '보류 사유' : '사유 상세' }[f] || L[f];
    const required = f === 'close_reason_text' && stage === 'lost' ? '' : 'required';
    const wrap = body => `<label class="field"><span class="${required ? 'req' : ''}">${esc(label)}</span>${body}</label>`;
    switch (f) {
      case 'contacts':
        if (o.contacts.length) return '';
        return `<div><span class="field-label req">고객 담당자</span><div class="grid">
          <input name="c_name" placeholder="이름" required maxlength="50"><input name="c_position" placeholder="부서·직책" maxlength="100">
          <input name="c_phone" placeholder="연락처" maxlength="50"><input name="c_email" type="email" placeholder="메일"></div></div>`;
      case 'amount_expected':
        return wrap(`<input name="${f}" data-money inputmode="numeric" value="${moneyStr(o.amount_expected)}" placeholder="원, 부가세 포함" required>`);
      case 'contract_amount':
        return wrap(`<input name="${f}" data-money inputmode="numeric" value="${moneyStr(o.contract_amount ?? o.amount_expected)}" placeholder="원, 부가세 포함" required>`);
      case 'expected_period':
        return wrap(`<input name="${f}" value="${esc(o.expected_period || '')}" placeholder="2027-03 또는 2027-03-15" pattern="\\d{4}-\\d{2}(-\\d{2})?" required>
          <div class="hint">미확정이면 연월만 입력합니다.</div>`);
      case 'submitted_at': case 'contract_date':
        return wrap(`<input name="${f}" type="date" value="${esc(o[f] || today())}" required>`);
      case 'review_date':
        return wrap(`<input name="${f}" type="date" value="${esc(o[f] || '')}" required>`);
      case 'close_reason_code':
        return wrap(`<select name="${f}" required>${codeOptions('loss_reason', o.close_reason_code, '선택')}</select>`);
      case 'close_reason_text':
        return wrap(`<textarea name="${f}" maxlength="2000" ${required}>${esc(stage === o.stage ? o.close_reason_text : '')}</textarea>`);
      default: return '';
    }
  };

  modal(`<form id="stage-form">
    <h2>${direct ? '바로 계약' : esc(codeName('stage', stage)) + ' 단계로 변경'}</h2>
    <div class="muted small">${esc(o.title)} · 현재 ${esc(codeName('stage', o.stage))}${reopening ? ' → 재개' : ''}</div>
    <div class="body">
      ${fields.map(input).join('')}
      <label class="field"><span>변경 사유</span><input name="reason" maxlength="200" placeholder="한 줄로 남깁니다 (선택)"></label>
    </div>
    <div class="foot"><button type="button" class="btn" data-close>취소</button><button class="btn primary">${direct ? '수주 처리' : '단계 변경'}</button></div>
  </form>`, (el, close) => {
    $('#stage-form', el).addEventListener('submit', async e => {
      e.preventDefault();
      const form = e.target;
      const out = {};
      for (const f of fields) {
        if (f === 'contacts') {
          if (form.c_name) out.contacts = [{ name: form.c_name.value.trim(), position: form.c_position.value.trim(), phone: form.c_phone.value.trim(), email: form.c_email.value.trim() }];
        } else if (form[f].hasAttribute('data-money')) out[f] = moneyVal(form[f]);
        else out[f] = form[f].value.trim();
      }
      await api('POST', `/api/opportunities/${id}/stage`, { stage, direct, reason: form.reason.value.trim(), fields: out });
      close();
      toast(direct ? '수주 처리했습니다.' : '단계를 변경했습니다.');
      reload();
    });
  });
}

/* ---------- SC-04 영업기회 등록·수정 ---------- */

const DRAFT_KEY = 'salesnote:draft';
const loadDraft = () => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY)); } catch (e) { return null; } };
const saveDraft = v => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(v)); } catch (e) { /* 저장 공간 없음 */ } };
const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* 무시 */ } };

const FORM_FIELDS = ['title', 'customer', 'biz_type', 'overview', 'source', 'contacts', 'amount_expected', 'win_probability',
  'expected_period', 'proposal_deadline', 'submitted_at', 'project_start', 'project_end', 'competitors', 'partners', 'links',
  'tags', 'visibility'];
function toModel(o) {
  const m = {};
  for (const f of FORM_FIELDS) m[f] = o[f];
  m.owner_id = o.owner ? o.owner.id : S.me.id;
  m.participant_ids = (o.participants || []).map(p => p.id);
  m.contacts = (o.contacts || []).map(c => ({ name: c.name, position: c.position, phone: c.phone, email: c.email }));
  return m;
}
const contactRow = (c = {}) => `<div class="contact-row">
  <input data-c="name" placeholder="이름" value="${esc(c.name || '')}" maxlength="50">
  <input data-c="position" placeholder="부서·직책" value="${esc(c.position || '')}" maxlength="100">
  <input data-c="phone" placeholder="연락처" value="${esc(c.phone || '')}" maxlength="50">
  <input data-c="email" placeholder="메일" value="${esc(c.email || '')}" maxlength="255">
  <button type="button" class="btn ghost sm" data-rm-contact aria-label="고객 담당자 삭제">삭제</button></div>`;

async function viewForm({ arg, params, path }) {
  const editing = path.endsWith('/edit');
  let m = { owner_id: S.me.id, participant_ids: [], contacts: [], visibility: 'public' };
  let opp = null;
  let restored = false;
  if (editing) {
    opp = (await api('GET', `/api/opportunities/${arg}`)).opp;
    if (!opp.perms.edit) throw new Error('담당자 또는 관리자만 수정할 수 있습니다.');
    m = toModel(opp);
  } else if (params.get('from')) {
    const source = (await api('GET', `/api/opportunities/${params.get('from')}`)).opp;
    m = Object.assign(toModel(source), { title: (source.title + ' (후속)').slice(0, 100), owner_id: S.me.id, submitted_at: null });
  } else {
    const draft = loadDraft();
    if (draft && (draft.title || draft.customer)) { m = Object.assign(m, draft); restored = true; }
  }
  const v = f => esc(m[f] ?? '');
  const terminal = opp && ['won', 'lost', 'hold'].includes(opp.stage);
  const hasMore = editing || restored || params.get('from');

  const closeFields = !terminal ? '' : `<div class="full"><span class="field-label">종료 정보</span><div class="grid">${
    opp.stage === 'won' ? `
      <label class="field"><span>계약 금액</span><input name="contract_amount" data-money inputmode="numeric" value="${moneyStr(opp.contract_amount)}"></label>
      <label class="field"><span>계약일</span><input name="contract_date" type="date" value="${esc(opp.contract_date || '')}"></label>`
    : opp.stage === 'lost' ? `
      <label class="field"><span>실주 사유</span><select name="close_reason_code">${codeOptions('loss_reason', opp.close_reason_code)}</select></label>
      <label class="field"><span>사유 상세</span><input name="close_reason_text" value="${esc(opp.close_reason_text)}"></label>`
    : `
      <label class="field"><span>보류 사유</span><input name="close_reason_text" value="${esc(opp.close_reason_text)}"></label>
      <label class="field"><span>재검토 예정일</span><input name="review_date" type="date" value="${esc(opp.review_date || '')}"></label>`
  }</div></div>`;

  const html = `<div class="form-wrap">
  <a class="back" href="${editing ? '#/opp/' + arg : '#/'}">← ${editing ? '상세로' : '목록으로'}</a>
  <div class="page-head" style="margin-top:6px"><h1>${editing ? '영업기회 수정' : '영업기회 등록'}</h1></div>
  ${restored ? '<div class="notice" style="margin-bottom:12px">임시 저장한 내용을 불러왔습니다. <button class="link" data-clear-draft>지우고 새로 쓰기</button></div>' : ''}
  <form id="opp-form" novalidate>
    <div class="card pad"><div class="grid">
      <label class="field full"><span class="req">제목</span><input name="title" value="${v('title')}" maxlength="100" placeholder="사업명 또는 기회를 알아볼 이름" required></label>
      <label class="field full"><span class="req">고객사</span><input name="customer" value="${v('customer')}" maxlength="100" list="customer-list" placeholder="발주 기관 또는 고객 기업" autocomplete="off" required>
        <datalist id="customer-list"></datalist></label>
      <div class="full" id="similar"></div>
    </div>
    ${editing ? '' : '<div class="hint" style="margin-top:12px">제목과 고객사만 있으면 등록됩니다. 나머지는 단계가 진행되면서 채웁니다.</div>'}
    </div>

    <details class="card more" ${hasMore ? 'open' : ''}><summary>선택 항목</summary><div class="body"><div class="grid">
      <label class="field"><span>사업 유형</span><select name="biz_type">${codeOptions('biz_type', m.biz_type, '선택 안 함')}</select></label>
      <label class="field"><span>정보 출처</span><input name="source" value="${v('source')}" maxlength="100" placeholder="소개, 기존 고객, 공고, 사전규격 등"></label>
      <label class="field"><span>예상 금액</span><input name="amount_expected" data-money inputmode="numeric" value="${moneyStr(m.amount_expected)}" placeholder="원, 부가세 포함">
        <div class="hint">관리자와 담당자·참여자에게만 보입니다.</div></label>
      <label class="field"><span>수주 가능성</span><select name="win_probability">${options([['high', '상'], ['mid', '중'], ['low', '하']], m.win_probability, '선택 안 함')}</select></label>
      <label class="field"><span>예상 공고·제안 시기</span><input name="expected_period" value="${v('expected_period')}" placeholder="2027-03 또는 2027-03-15"></label>
      <label class="field"><span>제안 마감일</span><input name="proposal_deadline" type="date" value="${v('proposal_deadline')}"></label>
      <label class="field"><span>사업 시작일</span><input name="project_start" type="date" value="${v('project_start')}"></label>
      <label class="field"><span>사업 종료일</span><input name="project_end" type="date" value="${v('project_end')}"></label>
      <label class="field"><span>담당자</span><select name="owner_id">${userOptions(m.owner_id)}</select></label>
      <label class="field"><span>공개 범위</span><select name="visibility">${options([['public', '전체 공개'], ['private', '담당자·참여자만']], m.visibility)}</select></label>
      <div class="full"><span class="field-label">참여자</span><div class="checks">${S.meta.users.map(u => `<label><input type="checkbox" name="participant" value="${u.id}" ${m.participant_ids.includes(u.id) ? 'checked' : ''}>${esc(u.name)}</label>`).join('')}</div></div>
      <label class="field full"><span>태그</span><input name="tags" value="${esc((m.tags || []).join(', '))}" placeholder="쉼표로 구분 (예: AI, 공공, 재계약)"></label>
      <label class="field"><span>경쟁사</span><input name="competitors" value="${esc((m.competitors || []).join(', '))}" placeholder="쉼표로 구분"></label>
      <label class="field"><span>협력사</span><input name="partners" value="${esc((m.partners || []).join(', '))}" placeholder="컨소시엄, 하도급 (쉼표로 구분)"></label>
      <label class="field full"><span>관련 링크</span><textarea name="links" rows="2" placeholder="https:// 로 시작하는 주소를 한 줄에 하나씩">${esc((m.links || []).join('\n'))}</textarea></label>
      <div class="full"><span class="field-label">고객 담당자</span><div id="contacts">${m.contacts.map(contactRow).join('')}</div>
        <button type="button" class="btn sm" data-add-contact>고객 담당자 추가</button></div>
      <div class="full"><span class="field-label">개요</span>${editor('overview', editing || params.get('from') ? m.overview : '', '배경, 고객 요구, 파악한 정보')}</div>
      ${closeFields}
    </div></div></details>

    <div class="form-foot"><a class="btn" href="${editing ? '#/opp/' + arg : '#/'}">취소</a><button class="btn primary">${editing ? '저장' : '등록'}</button></div>
  </form></div>`;

  return { html, bind(root) {
    const form = $('#opp-form', root);
    if (restored && m.overview) $('[data-editor="overview"] .editor-body', root).textContent = m.overview_text || '';

    const collect = () => {
      const out = {
        title: form.elements.title.value.trim(), customer: form.customer.value.trim(),
        biz_type: form.biz_type.value || null, source: form.source.value.trim(),
        amount_expected: moneyVal(form.amount_expected), win_probability: form.win_probability.value || null,
        expected_period: form.expected_period.value.trim() || null,
        proposal_deadline: form.proposal_deadline.value || null,
        project_start: form.project_start.value || null, project_end: form.project_end.value || null,
        owner_id: Number(form.owner_id.value), visibility: form.visibility.value,
        participant_ids: $$('[name=participant]:checked', form).map(c => Number(c.value)),
        tags: splitList(form.tags.value), competitors: splitList(form.competitors.value),
        partners: splitList(form.partners.value), links: splitList(form.links.value),
        contacts: $$('.contact-row', form).map(row => Object.fromEntries($$('[data-c]', row).map(i => [i.dataset.c, i.value.trim()]))).filter(c => c.name),
        overview: editorValue(form, 'overview'),
      };
      if (terminal) {
        for (const name of ['contract_date', 'close_reason_code', 'close_reason_text', 'review_date']) {
          if (form[name]) out[name] = form[name].value.trim() || (name === 'close_reason_text' ? '' : null);
        }
        if (form.contract_amount) out.contract_amount = moneyVal(form.contract_amount);
      }
      return out;
    };

    let timer;
    if (!editing) form.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const draft = collect();
        draft.overview_text = $('[data-editor="overview"] .editor-body', form).textContent;
        saveDraft(draft);
      }, 600);
    });
    const clear = $('[data-clear-draft]', root);
    if (clear) clear.addEventListener('click', () => { clearDraft(); route(); });

    $('[data-add-contact]', form).addEventListener('click', () => $('#contacts', form).insertAdjacentHTML('beforeend', contactRow()));
    form.addEventListener('click', e => { const b = e.target.closest('[data-rm-contact]'); if (b) b.closest('.contact-row').remove(); });

    // 고객사 자동완성과 같은 고객사의 진행 중인 기회 안내
    let lookup;
    const showSimilar = async () => {
      const name = form.customer.value.trim();
      const box = $('#similar', form);
      if (!name) { box.innerHTML = ''; return; }
      const list = await api('GET', `/api/opportunities/similar?customer=${encodeURIComponent(name)}${editing ? '&exclude=' + arg : ''}`);
      box.innerHTML = list.length ? `<div class="notice">같은 고객사의 진행 중인 영업기회가 있습니다. 중복이 아닌지 확인하세요.<br>${
        list.map(s => `<a href="#/opp/${s.id}" target="_blank" rel="noopener">${esc(s.title)}</a> (${esc(codeName('stage', s.stage))} · ${userLabel(s.owner)})`).join('<br>')}</div>` : '';
    };
    form.customer.addEventListener('input', () => {
      clearTimeout(lookup);
      lookup = setTimeout(async () => {
        const names = await api('GET', '/api/customers?q=' + encodeURIComponent(form.customer.value.trim()));
        $('#customer-list', form).innerHTML = names.map(n => `<option value="${esc(n)}">`).join('');
        showSimilar();
      }, 250);
    });
    if (form.customer.value) showSimilar();

    form.addEventListener('submit', async e => {
      e.preventDefault();
      const body = collect();
      if (!body.title || !body.customer) return toast('제목과 고객사를 입력하세요.', true);
      if (body.expected_period && !/^\d{4}-\d{2}(-\d{2})?$/.test(body.expected_period)) return toast('예상 공고·제안 시기는 2027-03 또는 2027-03-15 형식으로 입력하세요.', true);
      clearTimeout(timer);
      const id = editing
        ? (await api('PATCH', `/api/opportunities/${arg}`, body)).id
        : (await api('POST', '/api/opportunities', body)).id;
      if (!editing) clearDraft();
      toast(editing ? '저장했습니다.' : '등록했습니다.');
      go('/opp/' + id);
    });
  } };
}

/* ---------- SC-05 영업기회 상세 ---------- */

const fileItem = f => `<div class="file"><a href="${esc(f.url)}">${esc(f.filename)}</a><span class="muted small">${fmtSize(f.size)}</span>
  ${f.can_delete ? `<button class="link danger small" data-act="file-del" data-id="${f.id}">삭제</button>` : ''}</div>`;
const commentItem = c => `<div class="comment" id="cmt-${c.id}"><span class="who">${userLabel(c.author)}</span><span class="body">${mentionize(c.content)}</span>
  <span class="muted small"> ${ago(c.created_at)}</span>${c.can_delete ? ` <button class="link danger small" data-act="comment-del" data-id="${c.id}">삭제</button>` : ''}</div>`;
const commentForm = activityId => `<form class="comment-form" data-activity="${activityId || ''}">
  <input name="content" maxlength="2000" placeholder="댓글 (@이름으로 멘션)" aria-label="댓글" required>
  <select data-mention aria-label="멘션할 사람">${options(S.meta.users.filter(u => u.id !== S.me.id).map(u => [u.name, u.name]), '', '@ 멘션')}</select>
  <button class="btn sm">등록</button></form>`;

function systemText(t) {
  const m = t.meta || {};
  const who = `<b>${userLabel(t.author)}</b>님이`;
  const val = x => (x == null || x === '' ? '없음' : m.sensitive ? won(x) : esc(x));
  switch (t.event) {
    case 'created': return `${who} 영업기회를 등록했습니다.`;
    case 'stage_change': return `${who} ${m.direct ? '바로 계약으로 ' : m.reopened ? '다시 진행으로 돌려 ' : ''}단계를 ${esc(m.from_name)} → <b>${esc(m.to_name)}</b>(으)로 바꿨습니다.${m.reason ? ` <span class="muted">사유: ${esc(m.reason)}</span>` : ''}`;
    case 'field_change': return `${who} ${esc(m.label)}을(를) 바꿨습니다. ${m.masked ? '<span class="muted">(금액 열람 제한)</span>' : `${val(m.before)} → <b>${val(m.after)}</b>`}`;
    case 'owner_change': return `${who} 담당자를 ${esc(m.before)} → <b>${esc(m.after)}</b>(으)로 바꿨습니다.`;
    case 'todo_done': return `${who} 할 일을 완료했습니다: ${esc(m.content)}`;
    default: return `${who} ${esc(t.event || '')}`;
  }
}

function timelineItem(t) {
  if (t.kind === 'system') {
    return `<div class="tl sys" id="act-${t.id}">${systemText(t)} <span class="muted small">${fmtDT(t.created_at)}</span></div>`;
  }
  return `<div class="tl act" id="act-${t.id}"><div class="card tl-card">
    <div class="tl-head"><span class="type">${esc(codeName('activity_type', t.type))}</span><span class="who">${userLabel(t.author)}</span>
      <span class="muted small">${esc(t.activity_date)}${t.edited ? ' · 수정됨' : ''}</span><span class="right"></span>
      ${t.can_edit ? `<button class="link small" data-act="act-edit" data-id="${t.id}">수정</button>` : ''}
      ${t.can_delete ? `<button class="link danger small" data-act="act-del" data-id="${t.id}">삭제</button>` : ''}</div>
    <div class="rich">${t.content}</div>
    ${t.attachments.length ? `<div class="files">${t.attachments.map(fileItem).join('')}</div>` : ''}
    <div class="comments">${t.comments.map(commentItem).join('')}${commentForm(t.id)}</div>
  </div></div>`;
}

async function viewDetail({ arg: id, params }) {
  const data = await api('GET', `/api/opportunities/${id}`);
  const o = data.opp;
  const P = o.perms;
  const stageCodes = codes('stage').filter(s => s.is_active || s.code === o.stage);
  const progress = stageCodes.filter(s => !s.terminal);
  const ends = stageCodes.filter(s => s.terminal);
  const index = progress.findIndex(s => s.code === o.stage);
  const closed = index < 0;
  const filter = S.tlFilter[id] || '';
  const timeline = data.timeline.filter(t => !filter || (filter === 'system' ? t.kind === 'system' : t.type === filter));

  const step = (s, cls) => (P.edit && s.code !== o.stage
    ? `<button class="step ${cls}" data-act="stage" data-stage="${esc(s.code)}">${esc(s.name)}</button>`
    : `<div class="step ${cls}">${esc(s.name)}</div>`);
  const banner = o.stage === 'won' ? `<div class="banner won"><b>수주</b> · 계약 금액 ${o.amount_hidden ? '비공개' : won(o.contract_amount) || '-'} · 계약일 ${esc(o.contract_date || '-')}</div>`
    : o.stage === 'lost' ? `<div class="banner lost"><b>실주</b> · ${esc(codeName('loss_reason', o.close_reason_code))}${o.close_reason_text ? ' — ' + esc(o.close_reason_text) : ''}</div>`
    : o.stage === 'hold' ? `<div class="banner"><b>보류</b> · ${esc(o.close_reason_text)} · 재검토 예정일 ${esc(o.review_date || '-')}</div>` : '';

  const info = [
    ['고객사', esc(o.customer)],
    ['사업 유형', esc(codeName('biz_type', o.biz_type))],
    ['담당자', userLabel(o.owner) + (o.owner && o.owner.title ? ` <span class="muted">${esc(o.owner.title)}</span>` : '')],
    ['참여자', o.participants.map(userLabel).join(', ')],
    ['예상 금액', o.amount_hidden ? amountCell(o) : o.amount_expected == null ? '' : won(o.amount_expected)],
    ['수주 가능성', PROB[o.win_probability] || ''],
    ['예상 시기', esc(o.expected_period || '')],
    ['제안 마감일', esc(o.proposal_deadline || '')],
    ['제출일', esc(o.submitted_at || '')],
    ['사업 기간', o.project_start || o.project_end ? `${esc(o.project_start || '')} ~ ${esc(o.project_end || '')}` : ''],
    ['정보 출처', esc(o.source)],
    ['경쟁사', esc(o.competitors.join(', '))],
    ['협력사', esc(o.partners.join(', '))],
    ['관련 링크', o.links.map(u => `<a class="link" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u.replace(/^https?:\/\//, '').slice(0, 40))}</a>`).join('<br>')],
    ['공개 범위', o.visibility === 'private' ? '담당자·참여자만' : '전체 공개'],
    ['등록일', fmtDT(o.created_at)],
  ].filter(([, value]) => value).map(([k, value]) => `<dt>${k}</dt><dd>${value}</dd>`).join('');

  const html = `
  <a class="back" href="#/">← 목록으로</a>
  <div class="detail-head"><div class="row">
    <div class="grow"><h1>${esc(o.title)}</h1>
      <div class="sub">${stageBadge(o.stage)}<span>${esc(o.customer)}</span>${o.visibility === 'private' ? '<span class="lock">비공개</span>' : ''}
        ${o.tags.map(name => `<a class="tag" href="#/?tag=${encodeURIComponent(name)}">${esc(name)}</a>`).join('')}
        <span class="muted small">갱신 ${ago(o.updated_at)}</span></div></div>
    <div class="row">
      <button class="btn sm" data-act="watch">${o.watching ? '★ 관심 해제' : '☆ 관심 등록'}</button>
      ${P.edit ? `<a class="btn sm" href="#/opp/${o.id}/edit">수정</a>` : ''}
      <a class="btn sm" href="#/new?from=${o.id}">복제</a>
      ${P.delete ? '<button class="btn sm danger" data-act="delete">삭제</button>' : ''}
    </div></div></div>

  <div class="card stagebar">
    <div class="steps">${progress.map((s, i) => step(s, closed ? '' : i < index ? 'done' : i === index ? 'now' : '')).join('')}</div>
    <div class="ends">${ends.map(s => step(s, s.code === o.stage ? `now s-${s.code}` : '')).join('')}
      ${P.edit && !closed && o.biz_type === 'private' ? '<button class="step" data-act="direct" title="중간 단계를 거치지 않고 수주 처리합니다">바로 계약</button>' : ''}</div>
  </div>
  ${banner}

  <div class="cols">
    <div>
      ${o.overview ? `<div class="card pad" style="margin-bottom:16px"><h2>개요</h2><div class="rich">${o.overview}</div></div>` : ''}
      ${P.record ? `<form class="card pad" id="act-form">
        <h2>진행 기록 작성</h2>
        <div class="row" style="margin-bottom:10px">
          <div class="chips grow">${codes('activity_type').filter(c => c.is_active).map((c, i) => `<label class="chip"><input type="radio" name="type" value="${esc(c.code)}" ${i === 0 ? 'checked' : ''}><span>${esc(c.name)}</span></label>`).join('')}</div>
          <input type="date" name="activity_date" value="${today()}" style="width:150px" aria-label="활동 일자">
        </div>
        ${editor('activity', '', '미팅 내용, 통화 메모, 확인한 사실 등을 남깁니다. @이름으로 멘션할 수 있습니다.')}
        <div class="row" style="margin-top:10px"><input type="file" name="files" multiple class="grow" style="border:0;padding:0" aria-label="첨부파일">
          <button class="btn primary">기록 등록</button></div>
      </form>` : '<div class="card pad muted">담당자와 참여자만 진행 기록을 쓸 수 있습니다. 댓글은 누구나 달 수 있습니다.</div>'}

      <div class="chips" style="margin-top:18px">
        ${[['', '전체']].concat(codes('activity_type').filter(c => data.timeline.some(t => t.type === c.code)).map(c => [c.code, c.name]), [['system', '변경 이력']])
          .map(([v, l]) => `<button class="chip ${filter === v ? 'on' : ''}" data-act="filter" data-v="${esc(v)}">${esc(l)}</button>`).join('')}
      </div>
      <div class="timeline">${timeline.map(timelineItem).join('') || '<div class="empty">기록이 없습니다.</div>'}</div>

      <div class="card pad" style="margin-top:6px"><h2>댓글 ${data.comments.length || ''}</h2>
        <div class="comments" style="border:0;padding:0;margin:0">${data.comments.map(commentItem).join('')}${commentForm('')}</div></div>
    </div>

    <div class="side">
      <div class="card pad"><h2>기본 정보</h2><dl class="dl">${info}</dl></div>
      ${o.contacts.length ? `<div class="card pad"><h2>고객 담당자</h2>${o.contacts.map(c => `<div style="margin-bottom:8px"><b>${esc(c.name)}</b> <span class="muted">${esc(c.position)}</span>
        <div class="small">${[c.phone, c.email].filter(Boolean).map(esc).join(' · ')}</div></div>`).join('')}</div>` : ''}
      <div class="card pad"><h2>다음 할 일</h2>
        ${data.todos.map(t => `<div class="todo ${t.done ? 'done' : ''}">
          <input type="checkbox" data-todo="${t.id}" ${t.done ? 'checked' : ''} ${P.record ? '' : 'disabled'} aria-label="완료">
          <div class="grow"><div class="t-text">${esc(t.content)}</div>
            <div class="small ${!t.done && t.due_date && t.due_date < today() ? 'overdue' : 'muted'}">${t.due_date ? esc(t.due_date) : '기한 없음'} · ${userLabel(t.assignee)}</div></div>
          ${P.record ? `<button class="link danger small" data-act="todo-del" data-id="${t.id}">삭제</button>` : ''}</div>`).join('') || '<div class="muted small">등록된 할 일이 없습니다.</div>'}
        ${P.record ? `<form class="todo-form" id="todo-form"><input name="content" maxlength="300" placeholder="다음 액션" aria-label="할 일" required>
          <div class="row"><input name="due_date" type="date" aria-label="기한"><select name="assignee_id" aria-label="담당자">${userOptions(S.me.id)}</select></div>
          <button class="btn sm">할 일 추가</button></form>` : ''}
      </div>
      <div class="card pad"><h2>첨부파일 ${data.attachments.length || ''}</h2>
        <div class="files" style="margin:0">${data.attachments.map(fileItem).join('') || '<div class="muted small">첨부한 파일이 없습니다.</div>'}</div>
        ${P.record ? '<label class="btn sm" style="margin-top:10px">파일 첨부<input type="file" id="opp-files" multiple hidden></label><div class="hint">파일당 50MB 이하</div>' : ''}
      </div>
    </div>
  </div>`;

  const uploadFiles = async (files, activityId) => {
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024) { toast(`${file.name}: 파일당 50MB까지 첨부할 수 있습니다.`, true); continue; }
      const body = new FormData();
      body.append('file', file);
      if (activityId) body.append('activity_id', activityId);
      try { await api('POST', `/api/opportunities/${id}/attachments`, body); }
      catch (e) { toast(`${file.name}: ${e.message}`, true); }
    }
  };

  return { html, bind(root) {
    root.addEventListener('click', async e => {
      const el = e.target.closest('[data-act]');
      if (!el) return;
      const act = el.dataset.act;
      if (act === 'stage') return stageModal(id, el.dataset.stage);
      if (act === 'direct') return stageModal(id, 'won', true);
      if (act === 'filter') { S.tlFilter[id] = el.dataset.v; return reload(); }
      if (act === 'watch') { await api(o.watching ? 'DELETE' : 'POST', `/api/opportunities/${id}/watch`); toast(o.watching ? '관심 등록을 해제했습니다.' : '관심 기회로 등록했습니다.'); return reload(); }
      if (act === 'delete') {
        if (!(await confirmBox('이 영업기회를 삭제할까요? 휴지통에서 30일 동안 복구할 수 있습니다.', '삭제', true))) return;
        await api('DELETE', `/api/opportunities/${id}`);
        toast('휴지통으로 옮겼습니다.');
        return go('/');
      }
      if (act === 'act-edit') return activityModal(data.timeline.find(t => String(t.id) === el.dataset.id));
      const targets = { 'act-del': ['activities', '이 기록을 삭제할까요?'], 'comment-del': ['comments', '이 댓글을 삭제할까요?'], 'todo-del': ['todos', '이 할 일을 삭제할까요?'], 'file-del': ['attachments', '이 파일을 삭제할까요?'] };
      if (targets[act]) {
        if (!(await confirmBox(targets[act][1], '삭제', true))) return;
        await api('DELETE', `/api/${targets[act][0]}/${el.dataset.id}`);
        return reload();
      }
    });

    root.addEventListener('submit', async e => {
      e.preventDefault();
      const form = e.target;
      const button = $('button:not([type=button])', form);
      if (button) button.disabled = true;
      try {
        if (form.id === 'act-form') {
          const content = editorValue(form, 'activity');
          if (!content) return toast('내용을 입력하세요.', true);
          const created = await api('POST', `/api/opportunities/${id}/activities`, { type: form.type.value, activity_date: form.activity_date.value || null, content });
          await uploadFiles(form.files.files, created.id);
          toast('기록을 등록했습니다.');
        } else if (form.id === 'todo-form') {
          await api('POST', `/api/opportunities/${id}/todos`, { content: form.content.value, due_date: form.due_date.value || null, assignee_id: Number(form.assignee_id.value) });
        } else if (form.classList.contains('comment-form')) {
          await api('POST', `/api/opportunities/${id}/comments`, { content: form.content.value, activity_id: form.dataset.activity ? Number(form.dataset.activity) : null });
        } else return;
        reload();
      } finally {
        if (button) button.disabled = false;
      }
    });

    root.addEventListener('change', async e => {
      const el = e.target;
      if (el.dataset.todo) { await api('PATCH', `/api/todos/${el.dataset.todo}`, { done: el.checked }); return reload(); }
      if (el.id === 'opp-files') { await uploadFiles(el.files); return reload(); }
      if (el.hasAttribute('data-mention') && el.value) {
        const input = $('[name=content]', el.closest('form'));
        input.value = (input.value ? input.value.replace(/\s*$/, ' ') : '') + '@' + el.value + ' ';
        el.value = '';
        input.focus();
      }
    });

    // 알림에서 넘어온 경우 해당 위치로 이동
    const anchor = params.get('c') ? $('#cmt-' + CSS.escape(params.get('c')), root) : params.get('a') ? $('#act-' + CSS.escape(params.get('a')), root) : null;
    if (anchor) setTimeout(() => {
      anchor.scrollIntoView({ block: 'center' });
      const item = anchor.closest('.tl') || anchor;
      item.classList.add('flash');
      setTimeout(() => item.classList.remove('flash'), 2500);
    }, 50);
  } };
}

function activityModal(t) {
  modal(`<form id="act-edit"><h2>기록 수정</h2><div class="body">
    <div class="grid"><label class="field"><span>유형</span><select name="type">${codeOptions('activity_type', t.type)}</select></label>
      <label class="field"><span>활동 일자</span><input type="date" name="activity_date" value="${esc(t.activity_date)}"></label></div>
    ${editor('edit', t.content, '')}</div>
    <div class="foot"><button type="button" class="btn" data-close>취소</button><button class="btn primary">저장</button></div></form>`,
  (el, close) => {
    $('#act-edit', el).addEventListener('submit', async e => {
      e.preventDefault();
      const content = editorValue(el, 'edit');
      if (!content) return toast('내용을 입력하세요.', true);
      await api('PATCH', `/api/activities/${t.id}`, { type: e.target.type.value, activity_date: e.target.activity_date.value || null, content });
      close();
      reload();
    });
  });
}

/* ---------- SC-07 알림 목록 ---------- */

async function viewNotifications({ params }) {
  const unreadOnly = params.get('tab') !== 'all';
  const list = await api('GET', '/api/notifications' + (unreadOnly ? '?unread=true' : ''));
  const html = `<div style="max-width:760px">
  <div class="page-head"><h1>알림</h1><div class="actions"><button class="btn" data-all>모두 읽음</button></div></div>
  <div class="toolbar"><div class="tabs"><a href="#/notifications" class="${unreadOnly ? 'on' : ''}">미확인</a><a href="#/notifications?tab=all" class="${unreadOnly ? '' : 'on'}">전체</a></div></div>
  <div class="card">${list.map(n => `<div class="noti ${n.is_read ? '' : 'unread'}" data-id="${n.id}" data-opp="${n.opportunity_id || ''}" data-a="${n.activity_id || ''}" data-c="${n.comment_id || ''}">
      <span class="dot"></span><div class="grow"><div class="msg">${esc(n.message)}</div><div class="muted small">${ago(n.created_at)}</div></div></div>`).join('')
    || `<div class="empty">${unreadOnly ? '확인하지 않은 알림이 없습니다.' : '알림이 없습니다.'}</div>`}</div></div>`;
  return { html, bind(root) {
    $('[data-all]', root).addEventListener('click', async () => { await api('POST', '/api/notifications/read-all'); pollUnread(); reload(); });
    $$('.noti', root).forEach(el => el.addEventListener('click', async () => {
      await api('POST', `/api/notifications/${el.dataset.id}/read`);
      pollUnread();
      if (!el.dataset.opp) return reload();
      go('/opp/' + el.dataset.opp, el.dataset.c ? { c: el.dataset.c } : el.dataset.a ? { a: el.dataset.a } : null);
    }));
  } };
}

/* ---------- SC-08 대시보드 ---------- */

async function viewDashboard() {
  const data = await api('GET', '/api/dashboard');
  const stages = codes('stage').filter(s => s.is_active || data.stages[s.code]);
  const st = data.stats;
  const maxReason = Math.max(1, ...Object.values(st.loss_reasons));
  const stat = s => {
    const row = data.stages[s.code] || { count: 0, amount: 0, hidden: 0 };
    const amount = s.code === 'lost' || s.code === 'hold' || !row.count ? ''
      : row.hidden === row.count ? '금액 비공개'
      : !row.amount ? ''
      : wonShort(row.amount) + (row.hidden ? ' (열람 가능 건)' : '');
    return `<a class="card stat" href="#/?stage=${esc(s.code)}">${stageBadge(s.code)}
      <div class="n num">${row.count}<small> 건</small></div><div class="small muted num">${amount || '&nbsp;'}</div></a>`;
  };
  const html = `
  <div class="page-head"><h1>대시보드</h1></div>
  <div class="stats">${stages.map(stat).join('')}</div>
  <div class="two">
    <div class="card pad"><h2>기한이 가까운 할 일</h2>
      ${data.todos.map(t => `<a class="line-item" href="#/opp/${t.opportunity_id}">
        <span class="num small ${t.due_date < today() ? 'overdue' : 'muted'}" style="width:84px;flex:none;white-space:nowrap">${esc(t.due_date)}</span>
        <span class="grow">${esc(t.content)}<div class="small muted">${esc(t.opportunity_title)} · ${userLabel(t.assignee)}</div></span></a>`).join('')
        || '<div class="muted small">7일 안에 기한이 오는 할 일이 없습니다.</div>'}</div>
    <div class="card pad"><h2>최근 갱신된 영업기회</h2>
      ${data.recent.map(o => `<a class="line-item" href="#/opp/${o.id}">${stageBadge(o.stage)}
        <span class="grow">${esc(o.title)}<div class="small muted">${esc(o.customer)} · ${userLabel(o.owner)}</div></span>
        <span class="small muted">${ago(o.updated_at)}</span></a>`).join('') || '<div class="muted small">진행 중인 영업기회가 없습니다.</div>'}</div>
  </div>
  <div class="two">
    <div class="card pad"><h2>${st.year}년 수주·실주</h2>
      <div class="row" style="gap:28px;margin-bottom:14px">
        <div><div class="muted small">수주율</div><b class="num big">${st.win_rate == null ? '-' : st.win_rate + '%'}</b></div>
        <div><div class="muted small">수주</div><b class="num big">${st.won}<small>건</small></b></div>
        <div><div class="muted small">실주</div><b class="num big">${st.lost}<small>건</small></b></div></div>
      ${Object.entries(st.loss_reasons).map(([code, n]) => `<div class="line-item"><span style="width:96px;flex:none">${esc(codeName('loss_reason', code))}</span>
        <span class="bar"><i style="width:${Math.round(n / maxReason * 100)}%"></i></span><span class="num small">${n}건</span></div>`).join('')
        || '<div class="muted small">올해 실주한 건이 없습니다.</div>'}</div>
    <div class="card pad"><h2>담당자별 현황</h2>
      ${st.owners.length ? `<table><thead><tr><th style="padding-left:0">담당자</th><th>진행</th><th>수주</th><th>실주</th></tr></thead><tbody>
        ${st.owners.map(r => `<tr><td style="padding-left:0">${userLabel(r.owner)}</td><td class="num">${r.open}</td><td class="num">${r.won}</td><td class="num">${r.lost}</td></tr>`).join('')}</tbody></table>`
        : '<div class="muted small">집계할 영업기회가 없습니다.</div>'}</div>
  </div>`;
  return { html };
}

/* ---------- SC-09 내 설정 ---------- */

async function viewSettings() {
  const me = S.me;
  const html = `<div style="max-width:560px">
  <div class="page-head"><h1>내 설정</h1></div>
  <form class="card pad" id="me-form"><div class="grid">
    <label class="field full"><span>구글 계정</span><input value="${esc(me.email)}" disabled></label>
    <label class="field"><span>이름</span><input name="name" value="${esc(me.name)}" maxlength="100" required><div class="hint">멘션(@이름)에 쓰입니다.</div></label>
    <label class="field"><span>직급</span><input name="title" value="${esc(me.title)}" maxlength="50"></label>
    <label class="full row"><input type="checkbox" name="notify_email" ${me.notify_email ? 'checked' : ''}> 멘션과 담당자 지정을 메일로도 받기</label>
  </div><div class="form-foot"><button type="button" class="btn" id="logout">로그아웃</button><button class="btn primary">저장</button></div></form></div>`;
  return { html, bind(root) {
    $('#me-form', root).addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target;
      await api('PATCH', '/api/me', { name: f.elements.name.value.trim(), title: f.elements.title.value.trim(), notify_email: f.notify_email.checked });
      await refreshMeta();
      toast('저장했습니다.');
      route();
    });
    $('#logout', root).addEventListener('click', async () => { await api('POST', '/auth/logout'); S.me = null; go('/login'); });
  } };
}

/* ---------- SC-10 관리자 ---------- */

const ADMIN_TABS = [['users', '허용 사용자'], ['codes', '코드'], ['chat', '구글 챗 연동'], ['trash', '휴지통'], ['audit', '감사 기록']];
const KIND_NAMES = { stage: '영업 단계', biz_type: '사업 유형', activity_type: '활동 유형', loss_reason: '실주 사유' };
const AUDIT_NAMES = { login: '로그인', login_denied: '로그인 차단', view_restricted: '열람 제한 항목 조회', delete: '삭제', purge: '영구 삭제', export: '엑셀 내보내기' };

async function viewAdmin({ arg, params }) {
  if (S.me.role !== 'admin') throw new Error('관리자만 사용할 수 있습니다.');
  const tab = arg || 'users';
  const pane = await ({ users: adminUsers, codes: adminCodes, chat: adminChat, trash: adminTrash, audit: adminAudit }[tab] || adminUsers)(params);
  return {
    html: `<div class="page-head"><h1>관리자</h1></div>
      <div class="toolbar"><div class="tabs">${ADMIN_TABS.map(([k, l]) => `<a href="#/admin/${k}" class="${k === tab ? 'on' : ''}">${l}</a>`).join('')}</div></div>${pane.html}`,
    bind: pane.bind,
  };
}

async function adminUsers() {
  const users = await api('GET', '/api/admin/users');
  const html = `<form class="card pad row" id="user-add" style="margin-bottom:12px">
    <input name="email" type="email" placeholder="구글 계정 메일" required class="grow" style="min-width:200px">
    <input name="name" placeholder="이름" maxlength="100" style="width:130px"><input name="title" placeholder="직급" maxlength="50" style="width:110px">
    <select name="role" style="width:110px">${options([['member', '구성원'], ['admin', '관리자']], 'member')}</select>
    <button class="btn primary">허용 계정 추가</button></form>
  <div class="card"><div class="table-wrap"><table><thead><tr><th>이름</th><th>직급</th><th>구글 계정</th><th>역할</th><th>사용</th><th class="hide-sm">최근 로그인</th></tr></thead><tbody>
    ${users.map(u => `<tr data-id="${u.id}">
      <td><input data-u="name" value="${esc(u.name)}" maxlength="100" style="min-width:90px" aria-label="이름"></td>
      <td><input data-u="title" value="${esc(u.title)}" maxlength="50" style="min-width:70px" aria-label="직급"></td>
      <td>${esc(u.email)}</td>
      <td><select data-u="role" aria-label="역할" ${u.id === S.me.id ? 'disabled' : ''}>${options([['member', '구성원'], ['admin', '관리자']], u.role)}</select></td>
      <td><input type="checkbox" data-u="is_active" ${u.is_active ? 'checked' : ''} ${u.id === S.me.id ? 'disabled' : ''} aria-label="사용"></td>
      <td class="small muted hide-sm">${u.last_login_at ? fmtDT(u.last_login_at) : '로그인 전'}</td></tr>`).join('')}
  </tbody></table></div></div>
  <div class="hint">여기 등록된 구글 계정만 로그인할 수 있습니다. 사용을 끄면 즉시 차단됩니다.</div>`;
  return { html, bind(root) {
    $('#user-add', root).addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target;
      await api('POST', '/api/admin/users', { email: f.email.value, name: f.elements.name.value, title: f.elements.title.value, role: f.role.value });
      await refreshMeta();
      toast('허용 계정을 추가했습니다.');
      reload();
    });
    $$('[data-u]', root).forEach(el => el.addEventListener('change', async () => {
      const value = el.type === 'checkbox' ? el.checked : el.value;
      try {
        await api('PATCH', `/api/admin/users/${el.closest('tr').dataset.id}`, { [el.dataset.u]: value });
        await refreshMeta();
        toast('저장했습니다.');
      } catch (e) { reload(); throw e; }
    }));
  } };
}

async function adminCodes() {
  const all = await api('GET', '/api/admin/codes');
  const html = `<div class="two">${Object.keys(KIND_NAMES).map(kind => {
    const list = all.filter(c => c.kind === kind);
    return `<div class="card pad" data-kind="${kind}"><h2>${KIND_NAMES[kind]}</h2>
      ${list.map((c, i) => `<div class="row" data-id="${c.id}" style="margin-bottom:6px;flex-wrap:nowrap">
        <input data-name value="${esc(c.name)}" maxlength="100" class="grow" aria-label="이름">
        <button class="btn ghost sm" data-move="-1" ${i === 0 ? 'disabled' : ''} aria-label="위로">↑</button>
        <button class="btn ghost sm" data-move="1" ${i === list.length - 1 ? 'disabled' : ''} aria-label="아래로">↓</button>
        <label class="row small" style="flex:none;gap:4px" title="${c.is_system ? '기본 코드는 이름과 순서만 바꿀 수 있습니다' : ''}"><input type="checkbox" data-active ${c.is_active ? 'checked' : ''} ${c.is_system ? 'disabled' : ''}>사용</label></div>`).join('')}
      <form class="row" data-add style="margin-top:10px;flex-wrap:nowrap"><input name="name" placeholder="새 항목 이름" maxlength="100" class="grow" required><button class="btn sm">추가</button></form>
      ${kind === 'stage' ? '<div class="hint">수주·실주·보류는 종료 상태입니다. 단계별 필수 입력은 기본 단계에만 적용됩니다.</div>' : ''}</div>`;
  }).join('')}</div>`;
  const done = async () => { await refreshMeta(); reload(); };
  return { html, bind(root) {
    $$('[data-name]', root).forEach(el => el.addEventListener('change', async () => {
      await api('PATCH', `/api/admin/codes/${el.closest('[data-id]').dataset.id}`, { name: el.value });
      toast('저장했습니다.');
      done();
    }));
    $$('[data-active]', root).forEach(el => el.addEventListener('change', async () => {
      try { await api('PATCH', `/api/admin/codes/${el.closest('[data-id]').dataset.id}`, { is_active: el.checked }); }
      finally { done(); }
    }));
    $$('[data-move]', root).forEach(el => el.addEventListener('click', async () => {
      const card = el.closest('[data-kind]');
      const ids = $$('[data-id]', card).map(r => Number(r.dataset.id));
      const i = ids.indexOf(Number(el.closest('[data-id]').dataset.id));
      const j = i + Number(el.dataset.move);
      [ids[i], ids[j]] = [ids[j], ids[i]];
      await api('POST', '/api/admin/codes/reorder', { kind: card.dataset.kind, ids });
      done();
    }));
    $$('[data-add]', root).forEach(form => form.addEventListener('submit', async e => {
      e.preventDefault();
      await api('POST', '/api/admin/codes', { kind: form.closest('[data-kind]').dataset.kind, name: form.elements.name.value });
      done();
    }));
  } };
}

async function adminChat() {
  const { webhook } = await api('GET', '/api/admin/chat');
  const html = `<form class="card pad" id="chat-form" style="max-width:720px"><h2>구글 챗 스페이스 연동</h2>
    <label class="field"><span>수신 웹훅 주소</span><input name="webhook" value="${esc(webhook)}" placeholder="https://chat.googleapis.com/v1/spaces/…/messages?key=…&token=…"></label>
    <div class="hint">구글 챗 스페이스의 앱 및 통합 → 웹훅에서 만든 주소를 넣습니다. 새 영업기회 등록과 단계 변경을 이 스페이스로 보냅니다. 비공개 기회는 보내지 않습니다. 비워서 저장하면 연동이 꺼집니다.</div>
    <div class="form-foot"><button type="button" class="btn" id="chat-test">테스트 메시지 보내기</button><button class="btn primary">저장</button></div></form>`;
  return { html, bind(root) {
    $('#chat-form', root).addEventListener('submit', async e => {
      e.preventDefault();
      await api('PUT', '/api/admin/chat', { webhook: e.target.webhook.value });
      toast('저장했습니다.');
    });
    $('#chat-test', root).addEventListener('click', async () => { await api('POST', '/api/admin/chat/test'); toast('테스트 메시지를 보냈습니다.'); });
  } };
}

async function adminTrash() {
  const list = await api('GET', '/api/admin/trash');
  const html = `<div class="card">${list.length ? `<div class="table-wrap"><table><thead><tr><th>제목</th><th>고객사</th><th>담당자</th><th>삭제 일시</th><th></th></tr></thead><tbody>
    ${list.map(o => `<tr data-id="${o.id}"><td class="t-title">${esc(o.title)}</td><td>${esc(o.customer)}</td><td>${userLabel(o.owner)}</td><td class="small muted">${fmtDT(o.deleted_at)}</td>
      <td style="white-space:nowrap;text-align:right"><button class="btn sm" data-restore>복구</button> <button class="btn sm danger" data-purge>영구 삭제</button></td></tr>`).join('')}
    </tbody></table></div>` : '<div class="empty">휴지통이 비어 있습니다.</div>'}</div>
  <div class="hint">삭제한 영업기회는 30일 뒤 기록, 첨부파일, 고객 담당자 연락처와 함께 영구 삭제됩니다.</div>`;
  return { html, bind(root) {
    $$('[data-restore]', root).forEach(b => b.addEventListener('click', async () => {
      await api('POST', `/api/admin/trash/${b.closest('tr').dataset.id}/restore`);
      toast('복구했습니다.');
      reload();
    }));
    $$('[data-purge]', root).forEach(b => b.addEventListener('click', async () => {
      if (!(await confirmBox('영구 삭제하면 되돌릴 수 없습니다. 삭제할까요?', '영구 삭제', true))) return;
      await api('DELETE', `/api/admin/trash/${b.closest('tr').dataset.id}`);
      reload();
    }));
  } };
}

async function adminAudit(params) {
  const page = Number(params.get('page')) || 1;
  const data = await api('GET', '/api/admin/audit?page=' + page);
  const pages = Math.max(1, Math.ceil(data.total / data.size));
  const html = `<div class="card"><div class="table-wrap"><table><thead><tr><th>일시</th><th>계정</th><th>행위</th><th>대상</th><th class="hide-sm">내용</th><th class="hide-md">IP</th></tr></thead><tbody>
    ${data.items.map(r => `<tr><td class="small muted" style="white-space:nowrap">${fmtDT(r.created_at)}</td><td>${esc(r.user_email)}</td><td>${esc(AUDIT_NAMES[r.action] || r.action)}</td>
      <td class="small">${esc(r.target)}</td><td class="small hide-sm">${esc(r.detail)}</td><td class="small muted hide-md">${esc(r.ip)}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="pager"><span class="muted small">전체 ${data.total.toLocaleString()}건 · 1년 보관</span><span class="right"></span>
      <a class="btn sm" ${page <= 1 ? 'hidden' : ''} href="#/admin/audit?page=${page - 1}">이전</a><span class="small num">${page} / ${pages}</span>
      <a class="btn sm" ${page >= pages ? 'hidden' : ''} href="#/admin/audit?page=${page + 1}">다음</a></div></div>`;
  return { html };
}

const ROUTES = [
  [/^\/$/, viewList, 'list'],
  [/^\/board$/, viewBoard, 'board'],
  [/^\/new$/, viewForm, 'list'],
  [/^\/opp\/(\d+)$/, viewDetail, 'list'],
  [/^\/opp\/(\d+)\/edit$/, viewForm, 'list'],
  [/^\/notifications$/, viewNotifications, ''],
  [/^\/dashboard$/, viewDashboard, 'dashboard'],
  [/^\/settings$/, viewSettings, ''],
  [/^\/admin(?:\/(\w+))?$/, viewAdmin, 'admin'],
];

route();
