// 通用组件：置顶进度条、提示条、木牌倒计时、项目下拉、日期列表、侧栏导航
window.COMPONENTS = window.COMPONENTS || {};
(function () {
  const C = window.COMPONENTS;
  const pad = n => String(n).padStart(2, '0');
  const at = (day, hm) => new Date(`${day}T${hm}:00`).getTime();

  // ---------- 倒计时状态机（PLAN.md「顶部倒计时」那张表） ----------
  // 返回 mode：free 放风 / leave 请假 / done 已画押 / failed 失败 / empty 空草稿 /
  //           calm >2h / sweat <2h / panic <30min / pending 刚到点 / late 过点没交
  function signState(s, nowMs) {
    const left = Math.floor((at(s.today, s.submit_time) - nowMs) / 1000);
    const r = s.result;
    let mode;
    if (s.kind === 'rest') mode = 'free';
    else if (s.kind === 'leave') mode = 'leave';
    else if (s.pending && !(s.result && ['submitted', 'exists'].includes(s.result.status))) mode = 'pending';   // 到点后的确认倒计时中
    else if (r && (r.status === 'submitted' || r.status === 'exists')) mode = 'done';
    else if (r && r.status === 'failed') mode = 'failed';
    else if (r && r.status === 'empty') mode = 'empty';
    else if (left > 7200) mode = 'calm';
    else if (left > 1800) mode = 'sweat';
    else if (left > 0) mode = 'panic';
    else if (left > -120) mode = 'pending';
    else mode = 'late';
    return { mode, left };
  }
  window.signState = signState;

  // ---------- 置顶进度条：所有慢操作都显示在做什么 + 已用秒数 ----------
  C['busy-bar'] = {
    data: () => ({ now: Date.now(), timer: null }),
    mounted() { this.timer = setInterval(() => { this.now = Date.now(); }, 250); },
    unmounted() { clearInterval(this.timer); },
    computed: {
      cur() { const b = store.busy[store.busy.length - 1]; return b && this.now - b.t0 > 400 ? b : null; },  // 秒回的不闪
      secs() { return this.cur ? Math.floor((this.now - this.cur.t0) / 1000) : 0; },
    },
    template: `<div v-if="cur" class="busybar" role="status"><div class="busy-text"><icon-spin/> {{ cur.label }}…　已用 {{ secs }} 秒</div><div class="busy-track"><div class="busy-bar"></div></div></div>`,
  };
  C['icon-spin'] = { template: `<span class="spin">⛓</span>` };

  // ---------- 提示条 ----------
  C.toasts = {
    template: `<div class="toasts"><div v-for="t in store.toasts" :key="t.id" class="toast" :class="'k-' + t.kind" @click="act.dismissToast(t.id)">{{ t.msg }}</div></div>`,
  };

  // ---------- 到点后的提交确认：弹窗 + 倒计时，不理它就自动提交 ----------
  const fmtLeft = n => (n >= 120 ? `${Math.floor(n / 60)} 分 ${n % 60} 秒` : `${n} 秒`);
  const pendingMixin = {
    computed: {
      p: () => store.s && store.s.pending,
      left() { return this.p ? Math.max(0, Math.ceil((new Date(this.p.deadline).getTime() - act.now()) / 1000)) : 0; },
      leftText() { return this.left > 0 ? fmtLeft(this.left) + S.confirm.barLeft : S.confirm.now; },
      items: () => (store.s && store.s.draft ? store.s.draft.items : []),
    },
    methods: {
      submit() { act.submitNow(); },
      async cancel() {
        if (!(await act.ask(S.confirm.cancelAsk, { yes: S.confirm.cancelYes, no: S.confirm.cancelNo }))) return;
        await API.safe(async () => { await API.call('cancel_pending'); store.confirmCollapsed = false; await act.refresh(); });
      },
    },
  };
  C['confirm-dialog'] = {
    mixins: [pendingMixin],
    computed: {
      show() { return !!this.p && !store.confirmCollapsed; },
      pct() { return this.p && this.p.total ? Math.min(100, Math.round(100 * this.left / Math.max(this.p.total, this.left))) : 0; },
      hours() { return Math.round(this.items.reduce((a, i) => a + Number(i.workTime || 0), 0) * 10) / 10; },
    },
    methods: {
      async edit() {   // 宽限 10 分钟，弹窗收成顶部小倒计时条，去认罪书改
        await API.safe(async () => {
          await API.call('extend_pending', 10);
          await act.refresh();
          store.confirmCollapsed = true; store.page = 'draft'; store.draftTab = 'draft';
          act.toast(S.confirm.extended, 'ok');
        });
      },
    },
    template: `<div v-if="show" class="dim confirm-dim"><div class="dialog card confirm-dialog">
      <div class="card-title"><ico name="bell" :size="26"/><span>{{ S.confirm.title }}</span></div>
      <p class="hint" style="margin-top:0">{{ S.confirm.sub }}</p>
      <div class="confirm-items"><div v-for="(it, i) in items" :key="i" class="pv-item"><div class="pv-head"><b>{{ act.projectName(it.projectId) }}</b>
        <span class="chipnum">{{ it.workTime }} {{ S.draft.hours }}</span><span class="chipnum">{{ S.draft.done }} {{ it.completionDegree }}%</span></div>
        <pre class="pv-text">{{ it.workInfo }}</pre></div><div v-if="!items.length" class="muted">{{ S.confirm.empty }}</div></div>
      <div class="confirm-count"><b class="digits-sm">{{ leftText }}</b><div class="chainbar"><i :style="{ width: pct + '%' }"></i></div><small>{{ S.confirm.total }} {{ hours }} {{ S.draft.hours }}</small></div>
      <div class="row end"><button class="btn danger" @click="cancel">{{ S.confirm.cancel }}</button><button class="btn" @click="edit">{{ S.confirm.edit }}</button>
        <button class="btn primary" @click="submit">{{ S.confirm.submitNow }}</button></div></div></div>`,
  };
  // 去改一改之后：弹窗收起，顶部留一条小倒计时，随时能立即提交 / 取消
  C['pending-bar'] = {
    mixins: [pendingMixin],
    computed: { show() { return !!this.p && store.confirmCollapsed; }, dirty: () => store.draftDirty },
    template: `<div v-if="show" class="pendingbar"><span>⏳ <b>{{ leftText }}</b><span v-if="dirty" class="warnc">　{{ S.confirm.unsaved }}</span></span>
      <span class="row"><button class="btn small" @click="submit">{{ S.confirm.submitNow }}</button><button class="btn small danger" @click="cancel">{{ S.confirm.cancel }}</button></span></div>`,
  };

  // ---------- 确认框 ----------
  C['ask-dialog'] = {
    template: `<div v-if="store.dialog" class="dim ask-dim" @click.self="act.answer(false)"><div class="dialog card">
      <p>{{ store.dialog.msg }}</p><div class="row"><button class="btn" @click="act.answer(false)">{{ store.dialog.no }}</button>
      <button class="btn primary" @click="act.answer(true)">{{ store.dialog.yes }}</button></div></div></div>`,
  };

  // ---------- 木牌：倒计时 + 刑期进度 + 状态 ----------
  C['jail-sign'] = {
    computed: {
      s: () => store.s,
      st() { return store.s ? signState(store.s, act.now()) : { mode: 'calm', left: 0 }; },
      mode() { return this.st.mode; },
      isCount() { return ['calm', 'sweat', 'panic'].includes(this.mode); },
      hms() { const t = Math.max(0, this.st.left); return [Math.floor(t / 3600), Math.floor(t % 3600 / 60), t % 60].map(pad); },
      pct() {
        const s = store.s; if (!s) return 0;
        const a = at(s.today, '09:00'), b = at(s.today, s.submit_time);
        return Math.round(Math.min(1, Math.max(0, (act.now() - a) / (b - a))) * 100);
      },
      title() { const m = this.mode; return act.t(S.sign[m === 'done' ? 'done' : m] || ''); },
      sub() {
        const m = this.mode, g = S.sign;
        const v = this.s && this.s.result && this.s.result.verified;   // 提交后回读核对的结果（后端写的）
        const check = v ? (v.ok ? '　✓ 已回读核对：' : '　⚠ ') + v.note : '';
        return { done: g.rearrest + check, late: g.lateHint, empty: g.emptyHint, failed: this.s && this.s.result && this.s.result.error ? this.s.result.error : g.failedHint,
          free: g.freeHint, leave: '请假记录已报备，今天不用交。', pending: this.s && this.s.pending ? '确认窗口倒计时中，不理它就自动提交' : '几秒钟后见分晓……' }[m] || '';
      },
      avatar() { return { calm: 'calm', sweat: 'sweat', panic: 'panic', pending: 'sweat', late: 'sad', failed: 'blank', empty: 'blank' }[this.mode]; },
      showRetry() { return ['late', 'failed'].includes(this.mode); },
      showStamp() { return ['late', 'done', 'failed'].includes(this.mode); },
      stampText() { return { late: '越狱失败', done: '已画押', failed: '画押失败' }[this.mode]; },
      stampTone() { return { late: 'red', done: 'green', failed: 'red' }[this.mode]; },
      busy() { return store.busy.some(b => b.label === S.slow.submit_now); },
    },
    template: `<header class="sign-wrap" :class="'mode-' + mode">
      <div class="chains"><i></i><i></i></div>
      <div class="sign">
        <div class="sign-face">
          <celldoor v-if="mode === 'done'" :open="true" :size="76"/>
          <sunchain v-else-if="mode === 'free' || mode === 'leave'" :size="86"/>
          <prisoner v-else :mood="avatar" :size="92"/>
        </div>
        <div class="sign-main">
          <div class="sign-title">{{ title }}</div>
          <div v-if="isCount" class="digits" :class="{ blink: mode === 'panic' }">{{ hms[0] }}<b>:</b>{{ hms[1] }}<b>:</b>{{ hms[2] }}</div>
          <div v-else class="sign-sub">{{ sub }}</div>
          <div v-if="isCount || mode === 'pending'" class="sentence">
            <span class="sentence-label">{{ S.sign.sentence }}</span>
            <div class="chainbar"><i :style="{ width: pct + '%' }"></i><span class="cuff" :style="{ left: pct + '%' }"><handcuffs :size="34"/></span></div>
            <b>{{ pct }}%</b>
          </div>
        </div>
        <div class="sign-side">
          <div v-if="mode === 'panic'" class="bubble">{{ act.t(S.sign.bubble) }}</div>
          <stamp v-if="showStamp" :tone="stampTone">{{ stampText }}</stamp>
          <button v-if="showRetry" class="btn danger" :disabled="busy" @click="act.submitNow()">{{ S.actions.retry }}</button>
        </div>
      </div>
    </header>`,
  };

  // ---------- 项目下拉：最近用过的排前面；allowSkip = 加「不上报」；blank = 空选项文案 ----------
  C['proj-select'] = {
    props: { modelValue: { default: null }, blank: { type: String, default: null }, allowSkip: Boolean, auto: Boolean },
    emits: ['update:modelValue'],
    computed: {
      names() {
        const n = { ...(store.s ? store.s.project_names : {}) };
        if (store.options) store.options.projects.forEach(p => { n[p.projectId] = p.projectName; });
        return n;
      },
      recent() { return (store.s ? store.s.recent_projects : []).filter(id => this.names[id]); },
      rest() { return Object.keys(this.names).filter(id => !this.recent.includes(id)); },
      unknown() { return this.modelValue && this.modelValue !== '__skip__' && !this.names[this.modelValue]; },
    },
    template: `<select class="sel" :value="modelValue == null ? '' : modelValue" @change="$emit('update:modelValue', $event.target.value || null)">
      <option v-if="blank !== null" value="">{{ blank }}</option>
      <option v-else-if="!modelValue || unknown" value="">（未定，请选）</option>
      <option v-if="unknown" :value="modelValue">{{ modelValue }}</option>
      <option v-if="allowSkip" value="__skip__">{{ S.records.skip }}</option>
      <optgroup v-if="recent.length" label="最近用过"><option v-for="id in recent" :key="id" :value="id">{{ names[id] }}</option></optgroup>
      <optgroup label="全部项目"><option v-for="id in rest" :key="id" :value="id">{{ names[id] }}</option></optgroup>
    </select>`,
  };

  // ---------- 日期列表：节假日 / 调休 / 请假（chips + 日期选择） ----------
  C['date-list'] = {
    props: { modelValue: { type: Array, default: () => [] } },
    emits: ['update:modelValue'],
    data: () => ({ draft: '' }),
    methods: {
      add() { if (this.draft && !this.modelValue.includes(this.draft)) this.$emit('update:modelValue', [...this.modelValue, this.draft].sort()); this.draft = ''; },
      del(d) { this.$emit('update:modelValue', this.modelValue.filter(x => x !== d)); },
    },
    template: `<div class="datelist"><span v-for="d in modelValue" :key="d" class="chip">{{ d }}<button type="button" @click="del(d)" aria-label="删除">×</button></span>
      <input type="date" class="inp" v-model="draft" @keyup.enter="add"><button type="button" class="btn small" :disabled="!draft" @click="add">{{ S.office.addDate }}</button></div>`,
  };

  // ---------- 侧栏：身高刻度尺 + 牢房门牌导航 ----------
  C['nav-ruler'] = {
    computed: {
      pages: () => ['home', 'draft', 'archive', 'office'],
      badge() {
        const s = store.s; if (!s) return {};
        const items = s.draft ? s.draft.items : [];
        return { draft: items.filter(i => i.doubt).length || (store.draftDirty ? '●' : ''), home: s.result && s.result.status === 'failed' ? '!' : '' };
      },
    },
    template: `<nav class="ruler">
      <div class="ruler-ticks" aria-hidden="true"></div>
      <div class="plates">
        <button v-for="(p, i) in pages" :key="p" class="plate" :class="{ on: store.page === p }" @click="store.page = p">
          <small>囚室 {{ pad(i + 1) }}</small><b>{{ S.nav[p] }}</b><em>{{ S.navSub[p] }}</em>
          <span v-if="badge[p]" class="badge">{{ badge[p] }}</span>
        </button>
      </div>
      <div class="ruler-foot"><handcuffs :size="52"/><small>{{ act.t(S.tagline) }}</small></div>
    </nav>`,
    methods: { pad },
  };
})();
