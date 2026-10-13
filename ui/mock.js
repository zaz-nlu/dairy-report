// 假后端：只在网址带 ?mock 时启用（浏览器直接打开 ui/index.html?mock 就能开发，不需要 Python）。
// 严格按 bridge.py 文件头的契约返回数据；各方法加了延迟，模拟真实的快慢。正式环境里本文件什么都不做。
(function () {
  if (!/[?&]mock\b/.test(location.search)) return;
  window.IS_MOCK = true;
  const q = new URLSearchParams(location.search);
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const pad = n => String(n).padStart(2, '0');
  const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const clone = x => JSON.parse(JSON.stringify(x));

  // ---------- 场景：{日期, 时刻, kind, 提交结果, 草稿, 是否已登记} ----------
  const ITEMS = [
    { workInfo: '1.登录页显示密码错误剩余次数与账号锁定倒计时\n2.新增小智改密页，密码过期跳转区分小智与控制台\n3.改密校验新密码不能与旧密码相同', projectId: '7-296', workTime: 5.5, completionDegree: 80, doubt: false,
      basis: ['09:20 [git] dify-1.16.0: 登录页显示锁定与剩余次数 | console/auth/login.tsx, error.py', '10:05 [claude] dify-1.16.0: 需求「做导出按钮」→ 结果「导出做好了，前端测试待验证」 | web/export.tsx'] },
    { workInfo: '1.GPU 项目部署页去掉「打开试验场」入口\n2.嵌入式页面 UI 风格调整', projectId: '7-300', workTime: 2.5, completionDegree: 100, doubt: true,
      basis: ['15:10 [git] gpu-embed: 部署页去掉打开试验场 | deploy/index.tsx'] },
  ];
  const SCENARIOS = {
    calm:    { label: '工作日 · 离放风 >2 小时', time: '12:10:00' },
    lt2h:    { label: '工作日 · <2 小时（冒汗）', time: '16:20:00' },
    lt30:    { label: '工作日 · <30 分钟（警报）', time: '17:40:00' },
    pending: { label: '18:00 刚到 · 正在画押', time: '18:00:10' },
    confirm: { label: '18:00 到点 · 提交确认倒计时（60 秒）', time: '18:00:05', confirm: 60 },
    done:    { label: '已画押 · 刑满释放', time: '18:03:00', result: { status: 'submitted', at: '18:00:21', attempts: 1, verified: { ok: true, note: '系统里现有 2 条、共 8 小时，和提交的一致' } } },
    exists:  { label: '系统里已有日报（没重复交）', time: '18:03:00', result: { status: 'exists', at: '18:00:21', attempts: 1 } },
    late:    { label: '18:00 后没交 · 罚单生效', time: '18:40:00' },
    failed:  { label: '提交失败 · 警报', time: '18:10:00', result: { status: 'failed', at: '18:05:10', attempts: 2, error: '连不上日报系统：timed out' } },
    empty:   { label: '17:35 草稿为空（没搜到改动）', time: '17:35:00', draft: [] },
    emptyres:{ label: '18:03 草稿为空 · 没法画押', time: '18:03:00', draft: [], result: { status: 'empty', at: '18:00:21', attempts: 1, error: '今天没采到任何工作痕迹，去认罪书手填后再画押' } },
    rest:    { label: '周六 · 放风', time: '10:00:00', today: '2026-10-17', kind: 'rest' },
    leave:   { label: '请假日', time: '10:00:00', kind: 'leave' },
    fresh:   { label: '新同事 · 第一次打开（入狱登记）', time: '10:00:00', fresh: true },
  };

  const PROJECTS = [['7-296', '大模型和小智系统'], ['7-300', '地面态势和预测项目'], ['7-275', '一院数据治理项目2'], ['7-274', '数据集成支撑工具项目'],
    ['7-265', '贵州电网三如数字化审计项目'], ['7-278', '热工院大模型项目'], ['7-209', '课题申报'], ['7-301', '德尔塔日报填报系统'], ['7-310', '麒麟一体机交付项目']]
    .map(([projectId, projectName]) => ({ projectId, projectName }));

  // ---------- 可变的假数据 ----------
  let M, t0, base;
  function reset(key) {
    const sc = SCENARIOS[key] || SCENARIOS.calm;
    const today = sc.today || '2026-10-13';
    const yest = ymd(new Date(new Date(today).getTime() - 864e5));
    M = {
      key: SCENARIOS[key] ? key : 'calm', sc, today, yest,
      kind: sc.kind || 'work', lookback: 1, picks: {}, excluded: [], repo_projects: {},
      notes: [{ time: '15:00', text: '开了需求评审会' }], collected_at: `${today}T11:00:00`,
      draft: { provider: 'claude', generated_at: `${today}T11:41:00`, items: clone(sc.draft || ITEMS) },
      result: sc.result ? { ...sc.result, error: sc.result.error || null, items: clone(sc.draft || ITEMS), at: `${today}T${sc.result.at}` } : null,
      cfg: { username: 'liuyuchen', sources: ['git', 'claude', 'codex'], extra_repos: [], data_dir: '', collect_every_hours: 4, interrogate_time: '17:30', remind_times: ['18:30', '19:00'],
        submit_time: '18:00', hours: 8, fine: 100, confirm_seconds: 60, default_project: null, task_type: null, report_user: null, priority: null, holidays: ['2026-10-01'], workdays: [], leave_days: [],
        repo_projects: {}, ai_paths: [], lookback_days: 1, has_password: !sc.fresh, autostart: false },
      configured: !sc.fresh,
    };
    if (sc.fresh) { M.cfg.username = ''; M.draft = null; M.notes = []; }
    t0 = Date.now();
    base = new Date(`${today}T${sc.time}`).getTime();
    M.pendingDeadline = sc.confirm ? base + sc.confirm * 1000 : null;   // 到点后的确认倒计时：什么时候自动提交
    scheduleAuto();
  }

  const RAW = (today, yest) => [
    { source: 'git', date: today, time: '09:20', project: 'dify-1.16.0', text: '登录页显示锁定与剩余次数', files: ['console/auth/login.tsx', 'console/auth/error.py', 'web/lock.tsx'], reply: '' },
    { source: 'claude', date: today, time: '10:05', project: 'dify-1.16.0', text: '做导出按钮', files: ['web/export.tsx', 'web/export.css'], reply: '导出做好了，前端测试待验证' },
    { source: 'claude', date: today, time: '11:30', project: 'dify-1.16.0', text: '改一下样式，按钮对不齐', files: ['web/button.css'], reply: '对齐了，已提交' },
    { source: 'claude', date: today, time: '14:02', project: 'dify-1.16.0', text: '这个需求到底是什么意思，给客户怎么讲', files: [], reply: '可以这样讲：……' },
    { source: 'git', date: today, time: '15:10', project: 'gpu-embed', text: '部署页去掉打开试验场', files: ['deploy/index.tsx'], reply: '' },
    { source: 'codex', date: today, time: '16:00', project: 'daily-prison', text: '写个日报自动提交软件', files: ['collect.py', 'bridge.py', 'ui/index.html'], reply: '已完成骨架' },
    { source: 'claude', date: yest, time: '16:20', project: 'dify-1.16.0', text: '菜单授权弹窗首页默认必选', files: ['role-menu-auth-modal.tsx'], reply: '改好了，单测通过' },
    { source: 'claude', date: yest, time: '14:50', project: 'dify-1.16.0', text: '登录页加锁定倒计时', files: ['login.tsx'], reply: '做完了' },
  ].map(e => ({ cwd: '', ...e, key: `${e.source}|${e.time}|${e.text.slice(0, 40)}`, uid: `${e.date}|${e.source}|${e.time}|${e.text.slice(0, 40)}` }));

  function entries() {
    const all = RAW(M.today, M.yest).filter(e => M.lookback > 1 || e.date === M.today);
    return all.map(e => {
      let why, inc;
      const changed = e.source !== 'claude' && e.source !== 'codex' ? true : e.files.length > 0;
      if (M.repo_projects[e.project] === '__skip__') [why, inc] = ['private', false];
      else if (M.excluded.includes(e.key)) [why, inc] = ['never', false];
      else if (e.date === M.yest && e.time === '14:50') [why, inc] = ['maybe:' + M.yest, false];
      else if (e.uid in M.picks) [why, inc] = [M.picks[e.uid] ? 'picked' : 'unpicked', !!M.picks[e.uid]];
      else [why, inc] = changed ? ['work', true] : ['talk', false];
      return { ...e, included: inc, why };
    });
  }

  function state() {
    const nowMs = base + (Date.now() - t0);
    if (M.pendingDeadline && nowMs >= M.pendingDeadline) {   // 倒计时结束没人理它 -> 自动提交（和后端行为一致）
      M.result = { status: 'submitted', at: iso(nowMs), error: null, attempts: 1, items: clone(M.draft.items),
        verified: { ok: true, note: '系统里现有 ' + M.draft.items.length + ' 条，和提交的一致' } };
      M.pendingDeadline = null;
    }
    const now = new Date(nowMs);
    const nowStr = `${ymd(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    return {
      today: M.today, now: nowStr, kind: M.kind, submit_time: M.cfg.submit_time, interrogate_time: M.cfg.interrogate_time,
      result: M.result, draft: M.draft, notes: M.notes, entries: entries(), lookback_days: M.lookback, excluded: M.excluded,
      snapshots: [{ time: '12:00', project: 'dify-1.16.0', cwd: '', files: ['console/auth/lock.py', 'web/lock.css'] }],
      collected_at: M.collected_at, providers: ['claude', 'codex'],
      project_names: Object.fromEntries(PROJECTS.map(p => [p.projectId, p.projectName])), recent_projects: ['7-296', '7-300'],
      repo_projects: M.repo_projects, configured: M.configured, fine: M.cfg.fine,
      pending: M.pendingDeadline ? { deadline: iso(M.pendingDeadline), total: M.cfg.confirm_seconds } : null,
    };
  }

  // 倒计时结束时，真实后端会自己提交并推送「状态变了」；假后端用定时器模拟这一步
  let autoTimer = null;
  function scheduleAuto() {
    clearTimeout(autoTimer);
    if (!M.pendingDeadline) return;
    autoTimer = setTimeout(() => { state(); push({ type: 'state' }); }, Math.max(0, M.pendingDeadline - (base + (Date.now() - t0))) + 300);
  }

  // 毫秒时间戳 -> 后端那种本地无时区字符串 2026-10-13T18:00:05
  const iso = ms => { const d = new Date(ms); return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };

  function push(ev) { setTimeout(() => window.onBackendEvent && window.onBackendEvent(ev), 50); }

  const NL = String.fromCharCode(10);
  const INFO_A = ['1.适配了火狐112浏览器', '2.GPU项目 禅道需求修复', '3.页面BUG修复', '4.禅道BUG修复'];
  const INFO_B = ['1.修复了时序预测的曲线', '2.去掉了不用的编辑功能'];

  function history(limit) {
    const out = [];
    const d0 = new Date(M.today);
    for (let i = 0; i < Math.min(limit, 40); i++) {
      const d = new Date(d0.getTime() - i * 864e5), wd = d.getDay();
      const rest = wd === 0 || wd === 6;
      let status = rest ? null : (i % 11 === 5 ? 'missed' : i === 0 ? (M.result ? M.result.status : null) : i % 17 === 9 ? 'missed' : 'submitted');
      const projs = status === 'submitted' ? (i % 4 === 0 ? ['大模型和小智系统', '地面态势和预测项目'] : ['大模型和小智系统']) : [];
      out.push({ date: ymd(d), kind: rest ? 'rest' : 'work', status, items: projs.length, hours: status === 'submitted' ? 8 : 0, projects: projs });
    }
    return out;
  }

  const api = {
    async get_state() { await wait(80); return clone(state()); },
    async get_config() { await wait(60); return clone({ ...M.cfg, lookback_days: M.lookback, repo_projects: M.repo_projects }); },
    async save_config(cfg, password) {
      await wait(300);
      if ('lookback_days' in cfg) M.lookback = cfg.lookback_days;
      Object.assign(M.cfg, cfg);
      if (password) M.cfg.has_password = true;
      if (M.cfg.username && M.cfg.has_password) M.configured = true;
      push({ type: 'state' });
      return clone(M.cfg);
    },
    async fetch_options(username, password) {
      await wait(900);
      if (password === 'wrong') throw new Error('账号或密码不正确');
      if (!(username || M.cfg.username)) throw new Error('还没填日报系统账号密码，去典狱长办公室登记');
      return clone({ projects: PROJECTS, task_types: [{ projectTypeId: '7-4', projectTypeName: '开发' }, { projectTypeId: '7-5', projectTypeName: '测试' }, { projectTypeId: '7-32', projectTypeName: '会议' }],
        report_users: [{ id: 5, label: '王磊' }, { id: 7, label: '冯亮亮' }, { id: 58, label: '姚佩' }],
        auto: M.sc.fresh && !M.configured ? {} : { default_project: '7-296', task_type: '7-4', report_user: 5, priority: 1 } });
    },
    async collect_now() { await wait(1400); M.collected_at = state().now; push({ type: 'state' }); return { entries: [], snapshots: [] }; },
    async interrogate_now() {
      await wait(3200);
      const inc = entries().filter(e => e.included);
      const by = {};
      inc.forEach(e => { (by[M.repo_projects[e.project] || (e.project === 'gpu-embed' ? '7-300' : '7-296')] ||= []).push(e); });
      const items = Object.entries(by).map(([pid, es]) => ({
        workInfo: es.map((e, i) => `${i + 1}.${e.source === 'git' ? e.text : e.text + '（' + (e.reply || '已完成') + '）'}`).join('\n'),
        projectId: pid, workTime: Math.max(0.5, Math.round(8 * es.length / inc.length * 2) / 2), completionDegree: es.some(e => /待验证/.test(e.reply)) ? 80 : 100, doubt: false,
        basis: es.map(e => `${e.time} [${e.source}] ${e.project}: ${e.text}`) }));
      M.draft = { provider: 'claude', generated_at: state().now, items };
      push({ type: 'state' });
      return clone(M.draft);
    },
    async save_draft(items) { await wait(250); M.draft = { ...(M.draft || { provider: 'manual', generated_at: state().now }), items: clone(items), edited_at: state().now }; push({ type: 'state' }); return clone(M.draft); },
    async check_ai(deep, only) {
      const all = [
        { name: 'claude', path: 'C:\\Users\\ASUS\\.local\\bin\\claude.EXE', version: '2.1.278 (Claude Code)', ok: true, note: '调用成功，7 秒' },
        { name: 'codex', path: 'C:\\Users\\ASUS\\AppData\\Local\\OpenAI\\Codex\\bin\\9691020b546a15b2\\codex.exe', version: 'codex-cli 0.162.0-alpha.2', ok: true, note: '调用成功，9 秒' },
        { name: 'codex', path: 'C:\\Users\\ASUS\\AppData\\Roaming\\npm\\codex.CMD', version: 'codex-cli 0.144.1', ok: false, note: 'codex 退出码 1: The gpt-6.1-sol model is not supported' }];
      if (q.get('noai')) return [];
      const list = only ? all.filter(x => x.path === only) : all;
      await wait(deep ? 2200 : 200);
      return list.map(x => deep ? x : { ...x, ok: null, note: '' });
    },
    async pick_entry(u, on) { await wait(100); M.picks[u] = !!on; return clone(M.picks); },
    async exclude_entry(key, on) { await wait(100); M.excluded = M.excluded.filter(k => k !== key).concat(on ? [key] : []); return clone(M.excluded); },
    async set_repo_project(repo, pid) { await wait(100); if (pid) M.repo_projects[repo] = pid; else delete M.repo_projects[repo]; return clone(M.repo_projects); },
    async add_note(text) { await wait(100); if (!text.trim()) throw new Error('手记是空的'); M.notes.push({ time: state().now.slice(11, 16), text }); return clone(M.notes); },
    async remove_note(i) { await wait(80); M.notes.splice(i, 1); return clone(M.notes); },
    async submit_now() {
      await wait(1600);
      M.pendingDeadline = null;
      if (!M.draft || !M.draft.items.length) { M.result = { status: 'empty', at: state().now, error: '今天没采到任何工作痕迹，去认罪书手填后再画押', attempts: 1, items: [] }; }
      else M.result = { status: 'submitted', at: state().now, error: null, attempts: 1, items: clone(M.draft.items),
        verified: { ok: true, note: '系统里现有 ' + M.draft.items.length + ' 条、共 ' + M.draft.items.reduce((a, i) => a + i.workTime, 0) + ' 小时，和提交的一致' } };
      push({ type: 'state' });
      return clone(M.result);
    },
    async cancel_pending() { await wait(100); M.pendingDeadline = null; scheduleAuto(); push({ type: 'state' }); return true; },
    async extend_pending(minutes) {
      await wait(100);
      M.pendingDeadline = Math.max(M.pendingDeadline || 0, base + (Date.now() - t0)) + (minutes || 10) * 60000;
      scheduleAuto(); push({ type: 'state' }); return true;
    },
    async history(limit) { await wait(300); return history(limit || 60); },
    // 账本：规则和后端 bridge.ledger() 一致——从新往旧数，遇漏交就断；累计数加上假的更早历史
    async ledger() {
      await wait(150);
      const rows = history(40), missed = rows.filter(r => r.status === 'missed').map(r => r.date);
      let streak = 0;
      for (const r of rows) { if (r.status === 'missed') break; if (r.status === 'submitted' || r.status === 'exists') streak++; }
      const fine = M.cfg.fine, total = missed.length + 20;
      return { streak, on_time: rows.filter(r => r.status === 'submitted').length + 160, missed: total, fines: total * fine, fine,
        last_miss: missed[0] || '2026-09-30', since: '2025-11-05', missed_dates: missed.slice(0, 12), today: M.today };
    },
    async day_detail(date) {
      await wait(400);
      const h = history(60).find(x => x.date === date);
      const done = h && h.status === 'submitted';
      const remote = done ? { remark: '', hours: 8, items: h.projects.map((name, k) => ({
        projectId: name.startsWith('地面') ? '7-300' : '7-296', workTime: h.projects.length > 1 ? 4 : 8, completionDegree: 100,
        workInfo: (k === 0 ? INFO_A : INFO_B).join(NL) })) } : null;
      return clone({ raw: { entries: RAW(date, date).slice(0, 4).map(e => ({ ...e, date })), snapshots: [] }, remote,
        draft: date === M.today ? M.draft : null, result: date === M.today ? M.result : null, notes: [] });
    },
    async set_leave(date, on) { await wait(150); M.cfg.leave_days = M.cfg.leave_days.filter(d => d !== date).concat(on ? [date] : []); M.kind = on ? 'leave' : 'work'; push({ type: 'state' }); return clone(M.cfg); },
    async set_autostart(on) { await wait(150); M.cfg.autostart = !!on; return clone(M.cfg); },
    async open_web() { console.log('[mock] open_web'); },
    async hide_window() { console.log('[mock] hide_window'); },
    async quit_app() { console.log('[mock] quit_app'); },
  };

  reset(q.get('scenario') || 'calm');
  window.pywebview = { api };
  window.MOCK = { scenarios: SCENARIOS, current: () => M.key, set(key) { reset(key); store.page = 'home'; store.wizardOpen = !M.configured; act.refresh(); act.loadCfg(); } };

  // ---------- 右下角的状态切换面板（仅 ?mock） ----------
  window.COMPONENTS = window.COMPONENTS || {};
  window.COMPONENTS['mock-panel'] = {
    data: () => ({ open: true, key: M.key }),
    methods: {
      change() { MOCK.set(this.key); },
      notify() { act.toast('典狱长：还有 30 分钟查房——认罪书已拟好 2 条，18:00 自动画押，可以先去看看', 'info'); },
    },
    template: `<div class="mockpanel" :class="{ closed: !open }">
      <button class="mp-toggle" @click="open = !open">{{ open ? '✕' : '🛠 状态' }}</button>
      <div v-if="open"><b>假数据预览</b><br>
        <select v-model="key" @change="change"><option v-for="(sc, k) in MOCK.scenarios" :key="k" :value="k">{{ sc.label }}</option></select><br>
        <button @click="notify">模拟 17:30 通知</button></div></div>`,
    computed: { MOCK: () => window.MOCK },
  };
})();
