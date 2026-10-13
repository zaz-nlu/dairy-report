// 牢房（首页）：今日认罪书预览 + 连续按时天数 + 快捷操作 + 手记 + 今日劳改记录
window.PAGES = window.PAGES || {};
window.PAGES.home = {
  data: () => ({ note: '', showAll: false, showRest: false }),
  activated() { act.loadLedger(); },   // keep-alive：每次回到首页都刷新账本
  computed: {
    s: () => store.s,
    items() { return this.s.draft ? this.s.draft.items : []; },
    doubts() { return this.items.filter(i => i.doubt).length; },
    isWork() { return this.s.kind === 'work'; },
    mode() { return signState(this.s, act.now()).mode; },
    submitted() { return ['done'].includes(this.mode); },
    // 今天做了什么：勾选进日报的记录（按时间）。纯聊天 / 已报过 / 私人的不在这里，折叠到「其他」
    entries() { return this.s.entries.filter(e => e.included).sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time)); },
    rest() { return this.s.entries.filter(e => !e.included); },
    shown() { return this.showAll ? this.entries : this.entries.slice(-5); },
    snap() { return this.s.snapshots.length ? this.s.snapshots[this.s.snapshots.length - 1] : null; },
    collectedAt() { return this.s.collected_at ? this.s.collected_at.slice(11, 16) : null; },
    // 账本全部来自后端 ledger()，以日报系统里的记录为准（漏交的日子系统次日凌晨自动补空日报，才算数）
    L() { return store.ledger; },
    ledgerTip() {   // 鼠标悬停才看得到的说明，卡片上不放长文字
      const L = this.L; if (!L) return '';
      return `${S.ledger.since} ${L.since}，${S.ledger.basis}` + (L.last_miss ? `
${S.ledger.last} ${L.last_miss}，${S.ledger.sinceLast} ${this.sinceLastMiss} ${S.home.tallyDays}` : '');
    },
    sinceLastMiss() { return this.L && this.L.last_miss ? Math.max(0, Math.round((new Date(this.s.today) - new Date(this.L.last_miss)) / 864e5)) : null; },
    todayOpen() { return this.isWork && !this.submitted; },                       // 今天还没交
    todayLate() { return ['late', 'failed', 'empty'].includes(this.mode); },       // 今天已过点还没交
    busySubmit() { return store.busy.some(b => b.label === S.slow.submit_now); },
  },
  methods: {
    async addNote() {
      const text = this.note.trim();
      if (!text) return;
      await API.safe(async () => {
        await API.call('add_note', text);
        this.note = '';
        await act.refresh();
        act.toast('记下了，正在把它算进认罪书', 'ok');
        act.scheduleRegen();
      });
    },
    async delNote(i) {
      await API.safe(async () => { await API.call('remove_note', i); await act.refresh(); act.scheduleRegen(); });
    },
    async toggleLeave() {
      const on = this.s.kind !== 'leave';
      await API.safe(async () => { await API.call('set_leave', this.s.today, on); await act.refresh(); });
    },
    srcIcon: src => (src === 'git' || src === 'svn') ? 'shovel' : 'intercom',
    short: f => String(f).split(/[\\/]/).slice(-2).join('/'),
    goDraft() { store.page = 'draft'; store.draftTab = 'draft'; },
    goRecords() { store.page = 'draft'; store.draftTab = 'records'; },
  },
  template: `<div class="home">
    <div class="grid2">
      <div>
        <section class="card tl">
          <div class="card-title"><ico name="file" :size="26"/><span class="grow">{{ S.home.previewTitle }}</span>
            <stamp v-if="doubts" tone="red" class="small">{{ doubts }} {{ S.home.doubtN }}</stamp></div>
          <div v-if="store.regenerating" class="empty"><span class="spin big">⛓</span><p>{{ S.draft.regen }}<br><small>{{ S.draft.regenWait }}</small></p></div>
          <template v-else-if="items.length">
            <div v-for="(it, i) in items" :key="i" class="pv-item" :class="{ doubt: it.doubt }">
              <div class="pv-head"><b>{{ act.projectName(it.projectId) }}</b>
                <span class="chipnum">{{ it.workTime }} {{ S.draft.hours }}</span><span class="chipnum">{{ S.draft.done }} {{ it.completionDegree }}%</span>
                <stamp v-if="it.doubt" tone="red" class="small">{{ S.draft.doubt }}</stamp></div>
              <pre class="pv-text">{{ it.workInfo }}</pre>
            </div>
            <div class="row spread" style="margin-top:8px">
              <small>{{ S.draft.provider }}：{{ s.draft.provider }} · {{ S.draft.generated }} {{ s.draft.generated_at.slice(11, 16) }}<template v-if="s.draft.edited_at">　{{ S.draft.edited }}</template></small>
              <button class="btn small" @click="goDraft">{{ S.home.toDraft }}</button></div>
          </template>
          <div v-else class="empty"><handcuffs :size="70" class="handcuffs"/><p><b>{{ S.home.previewEmpty }}</b><br><small>{{ S.home.previewEmptyHint }}</small></p>
            <div class="row" style="justify-content:center"><button class="btn small" @click="goRecords">看看依据记录</button><button class="btn small" @click="goDraft">手填一条</button></div></div>
          <p v-if="isWork && ['calm', 'sweat', 'panic'].includes(mode) && items.length" class="hint" style="margin-bottom:0">{{ S.home.autoNote }}</p>
          <p v-else-if="mode === 'late' || mode === 'failed'" class="hint warnc" style="margin-bottom:0">{{ S.sign.lateHint }}</p>
        </section>
      </div>
      <div>
        <section class="card tr" :title="ledgerTip">
          <div class="card-title"><ico name="check" :size="24"/><span>{{ S.home.tallyTitle }}</span></div>
          <div v-if="!L" class="muted">{{ S.ledger.loading }}</div>
          <template v-else>
            <div class="chalk"><tally :n="L.streak"/></div>
            <div class="row spread" style="margin-top:8px"><b class="big-n">{{ L.streak }} <small>{{ S.home.tallyDays }}</small></b>
              <small>{{ S.ledger.onTime }} {{ L.on_time }} {{ S.ledger.days }}</small></div>
            <div class="fineline" :class="L.missed ? 'bad' : 'good'">
              <template v-if="L.missed">{{ S.ledger.missed }} <b>{{ L.missed }}</b> {{ S.ledger.times }} · <b class="money">¥{{ L.fines }}</b></template>
              <template v-else>✓ {{ S.ledger.never }}</template></div>
            <div v-if="todayLate" class="fineline bad">⚠ {{ S.ledger.lateToday }} <b class="money">¥{{ L.fine }}</b></div>
          </template>
        </section>
        <section class="card">
          <div class="card-title"><ico name="gear" :size="24"/><span>快捷操作</span></div>
          <div class="actions">
            <button class="btn" @click="act.collectNow()">{{ S.actions.collect }}</button>
            <button class="btn" @click="act.regenNow()" :disabled="store.regenerating">{{ S.actions.interrogate }}</button>
            <button class="btn primary" :disabled="busySubmit || submitted || !isWork" @click="act.submitNow(undefined, true)">{{ S.actions.submit }}</button>
            <button class="btn ghost" @click="toggleLeave">{{ s.kind === 'leave' ? S.home.leaveCancel : S.home.leaveToday }}</button>
          </div>
          <p class="hint" style="margin:8px 0 0">{{ S.home.searched }}：{{ collectedAt || S.home.never }}</p>
        </section>
      </div>
    </div>

    <section class="card">
      <div class="card-title"><ico name="pen" :size="24"/><span>{{ S.home.noteTitle }}</span></div>
      <div class="row nowrap"><input class="inp grow" v-model="note" :placeholder="S.home.notePlaceholder" @keyup.enter="addNote"><button class="btn" :disabled="!note.trim()" @click="addNote">{{ S.home.noteAdd }}</button></div>
      <p class="hint">{{ S.home.saveNote }}</p>
      <div v-for="(n, i) in s.notes" :key="i" class="tl-row"><b>{{ n.time }}</b><span class="tag note">手记</span><span class="grow">{{ n.text }}</span><button class="link" @click="delNote(i)">删</button></div>
    </section>

    <section class="card">
      <div class="card-title"><ico name="search" :size="24"/><span class="grow">{{ S.home.logTitle }}</span>
        <small>{{ entries.length }} 条写进日报<template v-if="rest.length"> · 另有 {{ rest.length }} 条不计入</template></small></div>
      <div v-if="!entries.length && !snap" class="muted">{{ S.home.logEmpty }}</div>
      <div v-for="e in shown" :key="e.uid" class="tl-row">
        <ico :name="srcIcon(e.source)" :size="22"/><b>{{ e.date !== s.today ? e.date.slice(5) + ' ' : '' }}{{ e.time }}</b>
        <span class="tag" :class="e.source">{{ e.project }}</span>
        <span class="grow">{{ e.text }}<span v-if="e.reply" class="reply">→ {{ e.reply }}</span></span></div>
      <div v-if="snap" class="tl-row"><ico name="shovel" :size="22"/><b>{{ snap.time }}</b><span class="tag git">{{ snap.project }}</span>
        <span class="grow"><small>未提交的改动：{{ snap.files.slice(0, 4).map(short).join('、') }}<template v-if="snap.files.length > 4"> 等 {{ snap.files.length }} 个</template></small></span></div>
      <div class="row spread" style="margin-top:6px">
        <button v-if="entries.length > 5" class="link" @click="showAll = !showAll">{{ showAll ? S.home.logLess : S.home.logAll + '（' + entries.length + '）' }}</button><span v-else></span>
        <button class="link" @click="goRecords">管理依据记录 →</button></div>
    </section>
  </div>`,
};
