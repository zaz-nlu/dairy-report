// 入狱登记向导：新同事第一次打开只被要求填账号密码，其余全自动。
// ①登记（验证账号 → 保存）②验货（自动检测 AI 工具，读到历史日报里的默认值）③入狱
window.COMPONENTS = window.COMPONENTS || {};
window.COMPONENTS.wizard = {
  data: () => ({ step: 1, user: '', pw: '', busy: false, error: '', found: null, hasDefaults: null }),
  computed: {
    mood() { return this.error ? 'sweat' : this.step === 3 ? 'free' : 'calm'; },
    canNext() { return this.user.trim() && this.pw; },
  },
  methods: {
    // 先用填的账号密码联系日报系统（验证对不对），对了才保存；错误直接显示在表单下面，不弹别处
    async register() {
      this.error = ''; this.busy = true;
      try {
        const o = await API.quiet('fetch_options', this.user.trim(), this.pw);
        await API.quiet('save_config', { username: this.user.trim() }, this.pw);
        this.hasDefaults = !!(o.auto && o.auto.default_project);
        this.pw = ''; this.step = 2;
      } catch (e) { this.error = (e && e.message) || S.wizard.bad; }
      this.busy = false;
    },
    async finish() {
      store.wizardOpen = false; store.page = 'home';
      await act.refresh(); API.safe(act.loadCfg);
    },
  },
  template: `<div class="wizard">
    <div class="wizard-card card">
      <div class="wz-head"><prisoner :mood="mood" :size="96"/><div><h1>{{ S.wizard.title }}</h1><p class="muted">{{ act.t(S.tagline) }}</p></div></div>
      <ol class="steps"><li v-for="(t, i) in S.wizard.step" :key="i" :class="{ on: step === i + 1, done: step > i + 1 }"><b>{{ step > i + 1 ? '✓' : i + 1 }}</b>{{ t }}</li></ol>

      <div v-if="step === 1">
        <h3>{{ S.wizard.s1 }}</h3><p class="hint">{{ S.wizard.s1hint }}</p>
        <div class="form col"><label class="f"><span>{{ S.office.username }}</span><input class="inp" v-model="user" autocomplete="off" @keyup.enter="canNext && register()"></label>
          <label class="f"><span>{{ S.office.password }}</span><input class="inp" type="password" v-model="pw" autocomplete="new-password" @keyup.enter="canNext && register()"></label></div>
        <p v-if="error" class="err-box">✗ {{ error }}</p>
        <div class="row end"><button class="btn primary" :disabled="!canNext || busy" @click="register">{{ busy ? '正在联系日报系统…' : S.actions.login }}</button></div>
      </div>

      <div v-else-if="step === 2">
        <h3>{{ S.wizard.s2 }}</h3><p class="hint">{{ S.wizard.s2hint }}</p>
        <ai-check auto compact @found="found = $event"/>
        <p v-if="found && !found.length" class="hint">{{ S.wizard.foundNoneHint }}</p>
        <p class="hint" :class="hasDefaults ? 'okc' : ''">{{ hasDefaults ? '✓ ' + S.wizard.defaultsFound : S.wizard.defaultsNone }}</p>
        <div class="row end"><button class="btn primary" :disabled="found === null" @click="step = 3">{{ S.actions.next }}</button></div>
      </div>

      <div v-else>
        <div class="row" style="align-items:center"><celldoor :open="true" :size="84"/><div><h3>{{ S.wizard.s3 }}</h3><p class="hint">{{ S.wizard.s3hint }}</p></div></div>
        <div class="row end"><button class="btn primary" @click="finish">{{ S.actions.finish }}</button></div>
      </div>
    </div>
  </div>`,
};
