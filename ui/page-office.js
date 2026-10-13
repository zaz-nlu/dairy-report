// 典狱长办公室（设置）+ 装备检测组件（入狱登记向导也用）
window.PAGES = window.PAGES || {};
window.COMPONENTS = window.COMPONENTS || {};

// ---------- 装备（AI 工具）检测：先秒出找到哪几个，再逐个真调用，每个完成更新一行 + N/总数进度条 ----------
window.COMPONENTS['ai-check'] = {
  props: { auto: Boolean, compact: Boolean },
  emits: ['found'],
  data: () => ({ list: null, states: [], done: 0, running: false, deep: false }),
  mounted() { if (this.auto) this.run(false); },
  computed: { okCount() { return this.states.filter(s => s && s.ok).length; } },
  methods: {
    async run(deep) {
      this.running = true; this.deep = deep; this.list = null;
      try {
        await API.safe(async () => {
          const list = await API.call('check_ai', false);
          this.list = list; this.done = 0; this.states = list.map(() => (deep ? { wait: true } : null));
          this.$emit('found', list);
          if (!deep) return;
          for (let i = 0; i < list.length; i++) {
            this.states[i] = { run: true };
            const r = await API.call('check_ai', true, list[i].path);
            this.states[i] = r && r[0] ? r[0] : { ok: false, note: '检测失败' };
            this.done = i + 1;
          }
        });
      } finally { this.running = false; }
    },
  },
  template: `<div class="aicheck">
    <div class="row"><button class="btn small" :disabled="running" @click="run(false)">{{ S.office.aiCheck }}</button>
      <button v-if="!compact" class="btn small" :disabled="running" @click="run(true)">{{ S.office.aiTest }}</button></div>
    <div v-if="list && !list.length" class="warn-box">{{ S.office.aiNone }}</div>
    <div v-if="list && list.length" class="ai-list">
      <div v-if="deep" class="prog"><progress :max="list.length" :value="done"></progress><small>{{ done }} / {{ list.length }}</small></div>
      <div v-for="(it, i) in list" :key="it.path" class="ai-row">
        <b class="tag" :class="it.name === 'claude' ? 'claude' : 'codex'">{{ it.name }}</b><span>{{ it.version || S.office.aiNoVersion }}</span>
        <template v-if="deep"><span v-if="states[i] && states[i].run" class="muted"><span class="spin">⛓</span> {{ S.office.aiRun }}</span>
          <span v-else-if="states[i] && states[i].wait" class="muted">· {{ S.office.aiWait }}</span>
          <span v-else-if="states[i] && states[i].ok" class="okc"><b>✓ {{ S.office.aiOk }}</b>（{{ states[i].note }}）</span>
          <span v-else-if="states[i]" class="warnc"><b>✗ {{ S.office.aiBad }}</b> {{ states[i].note }}</span></template>
        <div class="ai-path"><small>{{ it.path }}</small></div>
      </div>
      <div v-if="deep && !running" class="hint">{{ okCount ? '检测完成：' + okCount + ' 个能用，软件会按上面的顺序依次尝试' : '没有一个能用，请看上面每个的原因' }}</div>
    </div>
  </div>`,
};

window.PAGES.office = {
  data: () => ({ cfg: null, pw: '', extraText: '', aiText: '', autostart: false, saving: false, verified: false, orig: '' }),
  async activated() {
    await API.safe(async () => {
      if (!store.cfg) await act.loadCfg();
      this.load();
      if (store.s.configured) await act.loadOptions();
    });
  },
  computed: {
    opts() { return store.options || { projects: [], task_types: [], report_users: [] }; },
    auto() { return (store.options && store.options.auto) || {}; },
    dirty() { return this.cfg && JSON.stringify(this.pack()) !== this.orig; },
    hasPw() { return store.cfg && store.cfg.has_password; },
  },
  methods: {
    load() {
      this.cfg = JSON.parse(JSON.stringify(store.cfg));
      this.extraText = (this.cfg.extra_repos || []).join('\n'); this.aiText = (this.cfg.ai_paths || []).join('\n');
      this.autostart = !!this.cfg.autostart; this.pw = '';
      this.orig = JSON.stringify(this.pack());
    },
    lines: t => t.split('\n').map(x => x.trim()).filter(Boolean),
    // 要保存的字段（只发设置页管的这些，别把别处管的 repo_projects 等覆盖掉）
    pack() {
      const c = this.cfg;
      return { username: c.username.trim(), hours: Number(c.hours) || 8, collect_every_hours: Number(c.collect_every_hours) || 4,
        interrogate_time: c.interrogate_time, submit_time: c.submit_time, confirm_seconds: Number.isFinite(Number(c.confirm_seconds)) && c.confirm_seconds !== '' && c.confirm_seconds !== null ? Math.max(0, Math.round(Number(c.confirm_seconds))) : 60, fine: Number.isFinite(Number(c.fine)) && c.fine !== '' && c.fine !== null ? Number(c.fine) : 100, data_dir: (c.data_dir || '').trim(),
        default_project: c.default_project || null, task_type: c.task_type || null, report_user: c.report_user || null,
        priority: c.priority ? Number(c.priority) : null,
        extra_repos: this.lines(this.extraText), ai_paths: this.lines(this.aiText),
        holidays: c.holidays, workdays: c.workdays, leave_days: c.leave_days };
    },
    async login() {
      if (!this.cfg.username.trim() || !(this.pw || this.hasPw)) { act.toast('账号和密码都要填', 'err'); return; }
      await API.safe(async () => {
        await API.call('save_config', { username: this.cfg.username.trim() }, this.pw || null);
        await act.loadCfg(); store.cfg && (this.cfg.has_password = store.cfg.has_password);
        this.pw = '';
        await act.loadOptions();
        this.verified = true; act.toast(S.office.verified, 'ok');
        await act.refresh();
      });
    },
    async save() {
      this.saving = true;
      await API.safe(async () => {
        await API.call('save_config', this.pack(), this.pw || null);
        if (this.autostart !== !!store.cfg.autostart) await API.call('set_autostart', this.autostart);
        await act.loadCfg(); await act.refresh(); act.loadLedger(); this.load();
        act.toast(S.office.saved, 'ok');
      });
      this.saving = false;
    },
    async quit() { if (await act.ask('真的要退出吗？退出后到点不会自动画押。', { yes: '退出', no: '算了' })) API.safe(() => API.call('quit_app')); },
    hide() { API.safe(() => API.call('hide_window')); },
    openDebug() { location.href = 'debug.html' + (window.IS_MOCK ? '?mock' : ''); },
  },
  template: `<div v-if="cfg" class="office">
    <h2 class="page-title">{{ S.office.title }} <small>{{ S.office.sub }}</small></h2>

    <section class="card"><div class="card-title"><ico name="file" :size="24"/><span>{{ S.office.account }}</span></div>
      <div class="form"><label class="f"><span>{{ S.office.username }}</span><input class="inp" v-model="cfg.username" autocomplete="off"></label>
        <label class="f"><span>{{ S.office.password }}</span><input class="inp" type="password" v-model="pw" :placeholder="hasPw ? S.office.passwordKeep : '必填'" autocomplete="new-password"></label>
        <button class="btn" @click="login">{{ S.actions.login }}</button><span v-if="verified" class="okc">✓ {{ S.office.verified }}</span></div></section>

    <section class="card"><div class="card-title"><ico name="pen" :size="24"/><span>{{ S.office.defaults }}</span></div>
      <div class="form"><label class="f grow"><span>{{ S.office.project }}</span><proj-select v-model="cfg.default_project" :blank="S.office.auto"/></label>
        <label class="f"><span>{{ S.office.taskType }}</span><select class="sel" v-model="cfg.task_type"><option :value="null">{{ S.office.auto }}</option><option v-for="t in opts.task_types" :key="t.projectTypeId" :value="t.projectTypeId">{{ t.projectTypeName }}</option></select></label>
        <label class="f"><span>{{ S.office.reportUser }}</span><select class="sel" v-model="cfg.report_user"><option :value="null">{{ S.office.auto }}</option><option v-for="u in opts.report_users" :key="u.id" :value="u.id">{{ u.label }}</option></select></label>
        <label class="f"><span>{{ S.office.priority }}</span><select class="sel" v-model="cfg.priority"><option :value="null">{{ S.office.prioAuto }}</option><option v-for="p in S.office.prio" :key="p[0]" :value="p[0]">{{ p[1] }}</option></select></label>
        <label class="f"><span>{{ S.office.hoursPerDay }}</span><input class="inp num" type="number" min="0.5" max="24" step="0.5" v-model.number="cfg.hours"></label></div></section>

    <section class="card"><div class="card-title"><ico name="intercom" :size="24"/><span>{{ S.office.ai }}</span></div><p class="hint">{{ S.office.aiHint }}</p>
      <ai-check/>
      <label class="f" style="margin-top:10px"><span>{{ S.office.aiPaths }}</span><textarea class="ta" rows="2" v-model="aiText" placeholder="例如 C:\\tools\\claude-ds.cmd"></textarea><small class="muted">{{ S.office.aiPathsHint }}</small></label></section>

    <section class="card"><div class="card-title"><ico name="search" :size="24"/><span>{{ S.office.collect }}</span></div>
      <div class="form"><label class="f"><span>{{ S.office.interval }}</span><input class="inp num" type="number" min="1" max="24" v-model.number="cfg.collect_every_hours"></label>
        <label class="f grow"><span>{{ S.office.dataDir }}</span><input class="inp" v-model="cfg.data_dir"></label></div>
      <label class="f" style="margin-top:8px"><span>{{ S.office.extraRepos }}</span><textarea class="ta" rows="2" v-model="extraText"></textarea></label></section>

    <section class="card"><div class="card-title"><ico name="bell" :size="24"/><span>{{ S.office.times }}</span></div>
      <div class="form"><label class="f"><span>{{ S.office.interrogateAt }}</span><input class="inp" type="time" v-model="cfg.interrogate_time"></label>
        <label class="f"><span>{{ S.office.submitAt }}</span><input class="inp" type="time" v-model="cfg.submit_time"></label>
        <label class="f"><span>{{ S.office.confirmSec }}</span><input class="inp num" type="number" min="0" max="600" step="10" v-model.number="cfg.confirm_seconds"></label>
        <label class="f"><span>{{ S.office.fine }}</span><input class="inp num" type="number" min="0" step="10" v-model.number="cfg.fine"></label>
        <label class="row" style="padding-bottom:6px"><input type="checkbox" class="chk" v-model="autostart"> {{ S.office.autostart }}</label></div></section>

    <section class="card"><div class="card-title"><ico name="sun" :size="24"/><span>{{ S.office.dates }}</span></div><p class="hint">{{ S.office.datesHint }}</p>
      <label class="f"><span>{{ S.office.holidays }}</span><date-list v-model="cfg.holidays"/></label>
      <label class="f"><span>{{ S.office.workdays }}</span><date-list v-model="cfg.workdays"/></label>
      <label class="f"><span>{{ S.office.leaves }}</span><date-list v-model="cfg.leave_days"/></label></section>

    <section class="card"><div class="row spread"><div class="row"><button class="btn small" @click="hide"><ico name="tray" :size="16"/> {{ S.office.hide }}</button>
        <button class="btn small danger" @click="quit"><ico name="exit" :size="16"/> {{ S.office.quit }}</button></div>
      <button class="link" @click="openDebug">{{ S.office.debug }}（{{ S.office.debugHint }}）</button></div></section>

    <div class="actionbar"><span class="grow"><small v-if="dirty" class="warnc">● {{ S.draft.unsaved }}</small></span>
      <button class="btn primary" :disabled="saving || !(dirty || pw || autostart !== !!store.cfg.autostart)" @click="save">{{ S.actions.save }}</button></div>
  </div>`,
};
