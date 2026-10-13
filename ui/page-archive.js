// 档案室：过往案卷，每天一行，点开看当天的认罪书和提交结果
window.PAGES = window.PAGES || {};
window.PAGES.archive = {
  data: () => ({ open: null, detail: null, loading: false }),
  activated() { API.safe(act.loadHistory); act.loadLedger(); },
  computed: {
    rows() {
      return (store.history || []).map(h => {
        const d = new Date(h.date + 'T00:00:00');
        return { ...h, md: h.date.slice(5), wd: S.weekdays[d.getDay()], stamp: this.stampOf(h), isToday: h.date === store.s.today };
      });
    },
  },
  methods: {
    // 状态印章：已画押 / 越狱失败 / 空白案卷 / 放风 / 请假 / 未交
    stampOf(h) {
      const A = S.archive.status;
      if (h.status === 'submitted' || h.status === 'exists') return { t: A.submitted, tone: 'green' };  // 休息日加班交了也算已画押
      if (h.status === 'failed') return { t: A.failed, tone: 'red' };
      if (h.status === 'missed') return { t: A.missed, tone: 'red' };   // 系统次日凌晨补的空日报 = 漏交，要罚款
      if (h.kind === 'leave') return { t: A.leave, tone: 'orange' };
      if (h.kind === 'rest') return { t: A.rest, tone: 'ink' };
      if (h.status === 'empty') return { t: A.empty, tone: 'orange' };
      return h.date === store.s.today ? { t: '进行中', tone: 'orange' } : { t: A.none, tone: 'red' };
    },
    async toggle(r) {
      if (this.open === r.date) { this.open = null; return; }
      this.open = r.date; this.detail = null; this.loading = true;
      await API.safe(async () => { this.detail = await API.call('day_detail', r.date); });
      this.loading = false;
    },
    tail: f => String(f).split(/[\\/]/).slice(-2).join('/'),
    projectName: id => act.projectName(id),
  },
  template: `<div class="archive">
    <h2 class="page-title">{{ S.archive.title }} <small>{{ S.archive.hint }}</small></h2>
    <div v-if="store.ledger" class="card slim ledger-sum" :class="store.ledger.missed ? 'alert' : ''">
      <template v-if="store.ledger.missed">{{ S.archive.summary }} <b>{{ store.ledger.missed }}</b> {{ S.ledger.times }} · {{ S.ledger.fines }} <b class="money">¥{{ store.ledger.fines }}</b>
        <small class="muted">（{{ S.ledger.since }} {{ store.ledger.since }}，每次 ¥{{ store.ledger.fine }}）</small></template>
      <template v-else>✓ {{ S.ledger.never }}</template></div>
    <div v-if="!store.history" class="empty">正在翻档案……</div>
    <div v-else-if="!rows.length" class="card empty"><handcuffs :size="80" class="handcuffs"/><p>{{ S.archive.empty }}</p></div>
    <template v-else>
      <div v-for="r in rows" :key="r.date" class="case" :class="{ open: open === r.date, restday: r.kind !== 'work' && r.status !== 'submitted', missed: r.status === 'missed' }">
        <button class="case-row" @click="toggle(r)" :aria-expanded="open === r.date">
          <span class="case-date"><b>{{ r.md }}</b><small>{{ r.wd }}<template v-if="r.isToday"> · 今天</template></small></span>
          <stamp :tone="r.stamp.tone" :tilt="r.kind === 'work' ? -4 : 3" class="small">{{ r.stamp.t }}</stamp>
          <span class="grow case-projs"><template v-if="r.projects.length">{{ r.projects.join('、') }}</template><template v-else-if="r.items"><span class="muted">{{ r.items }} {{ S.archive.items }}</span></template></span>
          <span v-if="r.hours" class="chipnum">{{ r.hours }} {{ S.archive.hours }}</span><span v-if="r.status === 'missed'" class="chipnum fine">-¥{{ store.s.fine }}</span>
          <span class="chev">{{ open === r.date ? '▲' : '▼' }}</span>
        </button>
        <div v-if="open === r.date" class="case-detail">
          <div v-if="loading" class="muted">正在调卷宗……</div>
          <template v-else-if="detail">
            <div v-if="detail.result" class="row" style="margin-bottom:6px"><b>{{ S.archive.result }}：</b>
              <span>{{ S.archive.status[detail.result.status] || detail.result.status }}</span><small class="muted">{{ (detail.result.at || '').slice(11, 16) }} · 第 {{ detail.result.attempts }} 次</small>
              <span v-if="detail.result.error" class="warnc">{{ detail.result.error }}</span>
              <span v-if="detail.result.verified" :class="detail.result.verified.ok ? 'okc' : 'warnc'">{{ detail.result.verified.ok ? '✓ 已回读核对：' : '⚠ ' }}{{ detail.result.verified.note }}</span></div>
            <template v-if="detail.remote">
              <div class="subh">{{ S.archive.remote }}（{{ detail.remote.hours }} {{ S.archive.hours }}）</div>
              <div v-for="(it, i) in detail.remote.items" :key="'r' + i" class="pv-item"><div class="pv-head"><b>{{ projectName(it.projectId) }}</b>
                <span class="chipnum">{{ it.workTime }} {{ S.draft.hours }}</span><span class="chipnum">{{ S.draft.done }} {{ it.completionDegree }}%</span></div>
                <pre class="pv-text">{{ it.workInfo }}</pre></div>
              <p v-if="detail.remote.remark" class="muted">{{ S.archive.remark }}：{{ detail.remote.remark }}</p>
            </template>
            <div v-else-if="r.projects.length" class="warn-box">{{ S.archive.remoteFail }}</div>
            <template v-if="detail.draft && detail.draft.items.length">
              <div class="subh">{{ S.archive.draft }}</div>
              <div v-for="(it, i) in detail.draft.items" :key="i" class="pv-item"><div class="pv-head"><b>{{ projectName(it.projectId) }}</b>
                <span class="chipnum">{{ it.workTime }} {{ S.draft.hours }}</span><span class="chipnum">{{ S.draft.done }} {{ it.completionDegree }}%</span></div>
                <pre class="pv-text">{{ it.workInfo }}</pre>
                <details v-if="it.basis && it.basis.length" class="basis"><summary>{{ S.draft.basis }} {{ it.basis.length }} 条</summary><div v-for="(b, k) in it.basis" :key="k">{{ b }}</div></details></div>
            </template>
            <div v-else-if="!detail.remote && !r.projects.length" class="muted">{{ S.archive.none }}</div>
            <details v-if="detail.raw && detail.raw.entries.length" class="rest"><summary>{{ S.archive.raw }} {{ detail.raw.entries.length }} 条</summary>
              <div v-for="(e, k) in detail.raw.entries" :key="k" class="tl-row"><b>{{ e.time }}</b><span class="tag" :class="e.source">{{ e.project }}</span><span class="grow">{{ e.text }}</span></div></details>
            <div v-if="detail.notes && detail.notes.length" style="margin-top:6px"><span class="tag note">手记</span><span v-for="(n, k) in detail.notes" :key="k">{{ n.text }}　</span></div>
          </template>
        </div>
      </div>
    </template>
  </div>`,
};
