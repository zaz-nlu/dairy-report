// 认罪书：①日报草稿（可直接改）②依据记录（决定哪些记录写进日报）
window.PAGES = window.PAGES || {};
window.COMPONENTS = window.COMPONENTS || {};
const clone = x => JSON.parse(JSON.stringify(x));
let keySeq = 0;

window.PAGES.draft = {
  data: () => ({ items: [], silent: false, stale: false, loadedKey: '' }),
  created() { this.sync(true); },
  computed: {
    s: () => store.s,
    dirty: () => store.draftDirty,
    d() { return this.s.draft; },
    // 后端草稿的指纹：变了说明后台重新生成过 / 保存过
    serverKey() { return this.d ? `${this.d.generated_at}|${this.d.edited_at || ''}|${this.d.items.length}` : ''; },
    target() { return (store.cfg && store.cfg.hours) || 8; },
    total() { return Math.round(this.items.reduce((a, i) => a + Number(i.workTime || 0), 0) * 10) / 10; },
    recordsCount() { return this.s.entries.filter(e => e.included).length; },
    busySave() { return store.busy.some(b => b.label === S.slow.submit_now); },
    submitted() { return this.s.result && ['submitted', 'exists'].includes(this.s.result.status); },
  },
  watch: {
    serverKey() { this.sync(false); },
    items: { deep: true, handler() { if (!this.silent) store.draftDirty = true; } },
    dirty(v) { if (!v && !this.silent) this.sync(true); },   // 别处（重新审讯确认覆盖）清了「未保存」→ 载入后端的
  },
  methods: {
    // 把后端草稿载入编辑区。有未保存的修改时不覆盖（brief 第 11 条），只提示
    sync(force) {
      if (store.draftDirty && !force) { this.stale = true; return; }
      this.silent = true;
      this.items = (this.d ? this.d.items : []).map(it => ({ ...clone(it), _k: ++keySeq }));
      this.loadedKey = this.serverKey; this.stale = false;
      store.draftDirty = false;
      this.$nextTick(() => { this.silent = false; });
    },
    add() {
      this.items.push({ _k: ++keySeq, workInfo: '', projectId: (this.s.recent_projects || [])[0] || null, workTime: 1, completionDegree: 100, doubt: false, basis: [] });
      this.$nextTick(() => { const t = this.$el.querySelectorAll('textarea.ta'); if (t.length) t[t.length - 1].focus(); });
    },
    del(i) { this.items.splice(i, 1); },
    clean() {
      return this.items.filter(i => i.workInfo.trim()).map(i => ({
        workInfo: i.workInfo.trim(), projectId: i.projectId || null, workTime: Number(i.workTime) || 0.5,
        completionDegree: Math.min(100, Math.max(0, Number(i.completionDegree) || 0)),
        doubt: false,                       // 人看过、选过了就不再存疑
        basis: i.basis || [],               // 依据原样带回，保存不会把它弄丢
      }));
    },
    async save() {
      return API.safe(async () => {
        await API.call('save_draft', this.clean());
        this.silent = true; store.draftDirty = false;
        await act.refresh();
        this.sync(true);
        act.toast(S.draft.saved, 'ok');
        return true;
      });
    },
    async submit() {
      if (store.draftDirty && !(await this.save())) return;
      await act.submitNow(undefined, true);
    },
    async regen() { await act.regenNow(); },
    autoRows: t => Math.max(3, String(t || '').split('\n').length + 1),
  },
  template: `<div class="draftpage">
    <h2 class="page-title">{{ S.draft.title }} <small>{{ s.today }}</small>
      <span class="tabs"><button class="tab" :class="{ on: store.draftTab === 'draft' }" @click="store.draftTab = 'draft'">{{ S.draft.tabDraft }}<i v-if="store.draftDirty" class="dot">●</i></button>
        <button class="tab" :class="{ on: store.draftTab === 'records' }" @click="store.draftTab = 'records'">{{ S.draft.tabRecords }}<i class="cnt">{{ recordsCount }}</i></button></span></h2>

    <records-panel v-if="store.draftTab === 'records'"/>
    <template v-else>
      <div v-if="stale" class="card alert row spread"><span>⚠ {{ S.draft.dirtyLoad }}</span><button class="btn small" @click="sync(true)">{{ S.draft.dirtyLoadBtn }}</button></div>
      <div v-if="store.regenerating" class="card scanning"><div class="scan"></div><span class="spin big">⛓</span>
        <h3>{{ S.draft.regen }}</h3><p>{{ S.draft.regenWait }}</p></div>
      <template v-else>
        <div class="row spread" style="margin-bottom:10px"><small v-if="d">{{ S.draft.provider }}：{{ d.provider }} · {{ S.draft.generated }} {{ d.generated_at.slice(11, 16) }}<template v-if="d.edited_at">　<b class="okc">{{ S.draft.edited }}</b></template></small><span v-else></span>
          <div class="row"><button class="btn small" @click="regen">{{ S.actions.interrogate }}</button><button class="btn small" @click="add">{{ S.actions.addItem }}</button></div></div>

        <section v-for="(it, i) in items" :key="it._k" class="card item" :class="{ doubt: it.doubt }">
          <div class="item-head">
            <label class="f grow"><span>{{ S.draft.project }}</span><proj-select v-model="it.projectId"/></label>
            <label class="f"><span>{{ S.draft.time }}</span><input class="inp num" type="number" min="0.5" max="24" step="0.5" v-model.number="it.workTime" :title="S.draft.autoHint"></label>
            <label class="f"><span>{{ S.draft.done }} <b>{{ it.completionDegree }}%</b></span><input class="range" type="range" min="0" max="100" step="5" v-model.number="it.completionDegree" :title="S.draft.autoHint"></label>
            <stamp v-if="it.doubt" tone="red" class="small">{{ S.draft.doubt }}</stamp>
            <button class="btn small ghost" :title="S.actions.delItem" @click="del(i)"><ico name="trash" :size="18"/></button>
          </div>
          <textarea class="ta" :rows="autoRows(it.workInfo)" v-model="it.workInfo" :placeholder="S.draft.placeholder"></textarea>
          <details v-if="(it.basis || []).length" class="basis"><summary>{{ S.draft.basis }} {{ it.basis.length }} 条（{{ S.draft.basisHint }}）</summary><div v-for="(b, k) in it.basis" :key="k">{{ b }}</div></details>
          <small v-else class="muted">{{ S.draft.manual }}</small>
        </section>

        <div v-if="!items.length" class="card empty"><handcuffs :size="80" class="handcuffs"/><h3>{{ S.draft.empty }}</h3><p class="muted">{{ S.draft.emptyHint }}</p>
          <div class="row" style="justify-content:center"><button class="btn" @click="store.draftTab = 'records'">去看依据记录</button><button class="btn" @click="add">{{ S.actions.addItem }}</button></div></div>

        <div class="actionbar">
          <span class="total" :class="{ off: items.length && total !== target }">{{ S.draft.total }} <b>{{ total }}</b> {{ S.draft.hours }}<small v-if="total !== target">　（{{ S.draft.shouldBe }} {{ target }}）</small></span>
          <span class="grow"><small v-if="store.draftDirty" class="warnc">● {{ S.draft.unsaved }}</small></span>
          <button class="btn" :disabled="!store.draftDirty" @click="save">{{ S.actions.saveDraft }}</button>
          <button class="btn primary" :disabled="busySave || submitted || !items.length" @click="submit">{{ S.actions.submit }}</button>
        </div>
      </template>
    </template>
  </div>`,
};

// ================= 依据记录 =================
window.COMPONENTS['rec-row'] = {
  props: { e: Object },
  emits: ['pick', 'never'],
  computed: {
    changed() { return this.e.source === 'git' || this.e.source === 'svn' || this.e.files.length > 0; },
    locked() { return this.e.why === 'private' || this.e.why === 'never' || this.e.why.startsWith('reported:'); },
    why() { const w = this.e.why; return w.startsWith('reported:') ? S.records.reported.replace('{d}', w.slice(9)) : w.startsWith('maybe:') ? S.records.maybe.replace('{d}', w.slice(6)) : S.records.why[w]; },
    isToday() { return this.e.date === store.s.today; },
  },
  methods: { tail: f => String(f).split(/[\\/]/).slice(-2).join('/') },
  template: `<div class="rec" :class="{ off: !e.included }">
    <label class="rec-main"><input type="checkbox" class="chk" :checked="e.included" :disabled="locked" @change="$emit('pick', e, $event.target.checked)">
      <b>{{ isToday ? '' : e.date.slice(5) + ' ' }}{{ e.time }}</b></label>
    <div class="grow"><span v-if="why" class="tag gray">{{ why }}</span>{{ e.text }}
      <div v-if="changed && e.reply && e.source !== 'git' && e.source !== 'svn'" class="reply">→ {{ e.reply }}</div>
      <small v-if="e.files.length" class="muted">{{ S.records.changed }} {{ e.files.length }} {{ S.records.files }}：{{ e.files.slice(0, 3).map(tail).join('、') }}</small></div>
    <button v-if="e.why === 'never'" class="link" @click="$emit('never', e, false)">{{ S.records.restore }}</button>
    <button v-else-if="!locked" class="link" @click="$emit('never', e, true)">{{ S.records.never }}</button>
  </div>`,
};

window.COMPONENTS['records-panel'] = {
  computed: {
    s: () => store.s,
    changed: () => e => e.source === 'git' || e.source === 'svn' || e.files.length > 0,
    shown() { return e => this.changed(e) && e.why !== 'private' && !e.why.startsWith('reported:'); },
    used() { return this.s.entries.filter(e => e.included); },
    older() { return this.used.filter(e => e.date !== this.s.today).length; },
    nChanged() { return this.s.entries.filter(this.shown).length; },
    repos() {
      const names = [...new Set(this.s.entries.map(e => e.project).concat(this.s.snapshots.map(x => x.project)))];
      const n = r => this.s.entries.filter(e => e.project === r && this.shown(e)).length;
      return names.sort((a, b) => n(b) - n(a)).map(r => {
        const es = this.s.entries.filter(e => e.project === r);
        return { name: r, commits: es.filter(e => this.shown(e) && ['git', 'svn'].includes(e.source)), chats: es.filter(e => this.shown(e) && !['git', 'svn'].includes(e.source)),
          rest: es.filter(e => !this.shown(e)), snap: this.s.snapshots.filter(x => x.project === r).slice(-1)[0] };
      });
    },
  },
  methods: {
    tail: f => String(f).split(/[\\/]/).slice(-2).join('/'),
    // 改完任何一项：存后端 → 刷新 → 自动重新审讯（防抖）
    async after(fn) { await API.safe(async () => { await fn(); await act.refresh(); act.scheduleRegen(); }); },
    pick(e, on) { return this.after(() => API.call('pick_entry', e.uid, on)); },
    never(e, on) { return this.after(() => API.call('exclude_entry', e.key, on, e.date)); },
    repoProject(r, v) { return this.after(() => API.call('set_repo_project', r, v || '')); },
    lookback(v) { return this.after(() => API.call('save_config', { lookback_days: Number(v) }, null)); },
  },
  template: `<div class="records">
    <div v-if="store.regenerating" class="card scanning slim"><div class="scan"></div><span class="spin">⛓</span> {{ S.draft.regen }}　<button class="link" @click="store.draftTab = 'draft'">去看草稿</button></div>
    <div class="card">
      <div class="row spread"><div class="row"><b>{{ S.records.lookback }}</b>
          <select class="sel" :value="s.lookback_days" @change="lookback($event.target.value)"><option v-for="o in S.records.lookbackOpts" :key="o[0]" :value="o[0]">{{ o[1] }}</option></select></div>
        <span>{{ S.records.count }} <b>{{ nChanged }}</b> 条，{{ S.records.pick }} <b class="okc">{{ used.length }}</b> {{ S.records.toReport }}<template v-if="older">（其中 {{ older }} 条是{{ S.records.older }}）</template></span></div>
      <p class="hint" style="margin-bottom:0">{{ S.records.hint }}</p>
    </div>
    <div v-if="!repos.length" class="card empty"><p>{{ S.records.empty }}</p></div>
    <section v-for="g in repos" :key="g.name" class="card group" :class="{ skipgrp: s.repo_projects[g.name] === '__skip__' }">
      <div class="group-head"><b class="repo">{{ g.name }}</b><span>→ {{ S.records.belongs }}</span>
        <proj-select class="grow" :modelValue="s.repo_projects[g.name] || null" :blank="S.records.auto" allow-skip @update:modelValue="repoProject(g.name, $event)"/></div>
      <div v-if="g.commits.length" class="sub"><div class="subh"><ico name="shovel" :size="16"/> {{ S.records.commits }}（{{ g.commits.length }}）</div><rec-row v-for="e in g.commits" :key="e.uid" :e="e" @pick="pick" @never="never"/></div>
      <div v-if="g.chats.length" class="sub"><div class="subh"><ico name="intercom" :size="16"/> {{ S.records.chats }}（{{ g.chats.length }}）</div><rec-row v-for="e in g.chats" :key="e.uid" :e="e" @pick="pick" @never="never"/></div>
      <div v-if="g.snap" class="sub"><div class="subh">{{ S.records.uncommitted }}</div><small>{{ g.snap.files.slice(0, 8).map(tail).join('、') }}<template v-if="g.snap.files.length > 8"> 等 {{ g.snap.files.length }} 个</template></small></div>
      <div v-if="!g.commits.length && !g.chats.length && !g.snap" class="sub"><small class="muted">{{ S.records.noChange }}</small></div>
      <details v-if="g.rest.length" class="rest"><summary>{{ S.records.rest }} {{ g.rest.length }} 条（{{ S.records.restHint }}）</summary><rec-row v-for="e in g.rest" :key="e.uid" :e="e" @pick="pick" @never="never"/></details>
    </section>
  </div>`,
};
