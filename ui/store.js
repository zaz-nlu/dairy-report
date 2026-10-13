// 全局状态（响应式）+ 通用动作。页面只读 store、调 act.*，不直接碰后端。
(function () {
  const { reactive } = Vue;

  const store = reactive({
    s: null,            // get_state() 的返回
    cfg: null,          // get_config()
    options: null,      // fetch_options()：项目 / 任务类型 / 汇报人
    history: null,      // history()
    offset: 0,          // 后端时间 − 本机时间（毫秒）：倒计时以后端为准，防本机时钟不准
    tick: Date.now(),   // 每秒刷新，驱动倒计时
    page: 'home',       // home | draft | archive | office
    draftTab: 'draft',  // draft | records
    busy: [],           // 正在进行的慢操作 [{label, t0}]
    toasts: [],         // 提示条 [{id, msg, kind}]
    draftDirty: false,  // 认罪书有未保存的修改
    regenerating: false,// 正在按用户的选择重新审讯
    wizardOpen: false,  // 入狱登记向导（首次打开时账号没配才开；只有「完成」按钮能关，免得保存账号后向导中途消失）
    dialog: null,       // 自定义确认框 {msg, yes, no, res}
    confirmCollapsed: false, // 用户点了「去改一改」：确认弹窗收起成顶部的小倒计时条
    ledger: null,       // 账本：连续按时天数、累计漏交次数和罚款（日报系统里的记录算出来的）
  });

  let toastId = 0;
  const act = {
    now: () => store.tick + store.offset,        // 后端的「现在」（毫秒时间戳）
    toast(msg, kind = 'info') {
      const id = ++toastId;
      store.toasts.push({ id, msg, kind });
      setTimeout(() => { store.toasts = store.toasts.filter(t => t.id !== id); }, kind === 'err' ? 9000 : 5000);
    },
    dismissToast(id) { store.toasts = store.toasts.filter(t => t.id !== id); },

    // 拉最新状态；静默（不弹错误，定时刷新不能刷屏）
    async refresh() {
      try {
        const s = await API.quiet('get_state');
        store.s = s;
        if (!s.pending) store.confirmCollapsed = false;   // 倒计时结束 / 取消了：下次到点重新弹
        store.offset = new Date(s.now).getTime() - Date.now();
        return s;
      } catch (e) { /* 后端暂时没响应：保留旧状态 */ }
    },
    async loadCfg() { store.cfg = await API.call('get_config'); return store.cfg; },
    async loadOptions() { store.options = await API.call('fetch_options'); return store.options; },
    async loadHistory() { store.history = await API.call('history', 60); return store.history; },

    // 项目 id → 名称 / 最近用过 的排序
    projectName: id => (store.s && store.s.project_names[id]) || (store.options && (store.options.projects.find(p => p.projectId === id) || {}).projectName) || id || '（未定）',
  };

  // 罚款金额不写死：文案里的 {fine} 一律换成后端设置的值（设置页可改，默认 100）
  act.fine = () => (store.s && store.s.fine) || 100;
  act.t = str => String(str).replace(/\{fine\}/g, act.fine());
  act.loadLedger = async () => { try { store.ledger = await API.quiet('ledger'); } catch (e) { /* 没配账号 / 连不上：账本留空 */ } };

  // ---------- 自定义确认框（别用 window.confirm：桌面窗口里不一定可靠，也不搭风格） ----------
  act.ask = (msg, o = {}) => new Promise(res => { store.dialog = { msg, yes: o.yes || '好', no: o.no || '算了', res }; });
  act.answer = ok => { const d = store.dialog; store.dialog = null; if (d) d.res(ok); };

  // ---------- 常用动作（都会在做完后刷新状态；出错 API 层已弹提示，这里只负责不让异常冒出去） ----------
  act.collectNow = () => API.safe(async () => {
    await API.call('collect_now');
    await act.refresh();
    act.toast('搜身完毕', 'ok');
  });
  act.submitNow = (date, needConfirm = false) => API.safe(async () => {
    if (needConfirm && !(await act.ask(S.draft.submitConfirm, { yes: '签字画押', no: '再看看' }))) return;
    const r = await API.call('submit_now', date);
    await act.refresh();
    act.loadLedger();
    if (r.status === 'submitted') act.toast(S.draft.submitDone, 'ok');
    else if (r.status === 'exists') act.toast('日报系统里已经有今天的日报，没有重复提交', 'ok');
    else act.toast(r.error || '没有提交成功', 'err');
  });

  // 改了仓库归属 / 勾选 / 永不上报 / 回看范围之后，停 1.2 秒自动按新选择重新审讯，给用户预览（连改几下只生成一次）
  let regenTimer = null;
  act.scheduleRegen = () => { clearTimeout(regenTimer); regenTimer = setTimeout(act.regenNow, 1200); };
  act.regenNow = async () => {
    const d = store.s && store.s.draft;
    if (((d && d.edited_at) || store.draftDirty) && !(await act.ask(S.draft.confirmOverwrite, { yes: '覆盖', no: '保留我的' }))) return;
    store.draftDirty = false;   // 用户确认覆盖：认罪书页面会据此载入新生成的草稿
    store.regenerating = true;
    try { await API.safe(() => API.call('interrogate_now')); }
    finally { store.regenerating = false; }
    await act.refresh();
  };

  window.store = store;
  window.act = act;
})();
