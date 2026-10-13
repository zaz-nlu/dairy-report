// 入口：注册组件和页面，定时刷新，接后端推送
(function () {
  const params = new URLSearchParams(location.search);

  const App = {
    data: () => ({ fatal: '' }),
    computed: {
      isMock: () => !!window.IS_MOCK,
      needWizard: () => store.wizardOpen,
      pageComp: () => 'page-' + store.page,
    },
    async mounted() {
      setInterval(() => { store.tick = Date.now(); }, 1000);
      // 后端主动推送：状态变了 → 重新拉；通知 → 页面里也弹一条（后端同时发了托盘气泡）
      window.onBackendEvent = ev => {
        if (ev.type === 'state') act.refresh();
        else if (ev.type === 'notify') act.toast(`${ev.title}：${ev.message}`, 'info');
      };
      if (params.get('page')) store.page = params.get('page');     // 方便截图 / 调试：?page=draft&tab=records
      if (params.get('tab')) store.draftTab = params.get('tab');
      try { await API.whenReady(); } catch (e) { this.fatal = e.message; return; }
      await act.refresh();
      if (store.s && !store.s.configured) store.wizardOpen = true;   // 第一次打开：先入狱登记
      act.loadCfg().catch(() => {});
      setInterval(act.refresh, 60000);                              // 每分钟校准一次时间和状态
    },
    template: `<div class="app">
      <busy-bar/><toasts/><ask-dialog/><confirm-dialog/>
      <mock-panel v-if="isMock"/>
      <div v-if="fatal" class="card" style="margin:40px"><h2>打不开</h2><p>{{ fatal }}</p></div>
      <div v-else-if="!store.s" class="loading"><handcuffs :size="90"/><p>正在放风……</p></div>
      <wizard v-else-if="needWizard"/>
      <template v-else>
        <jail-sign/>
        <div class="stripes"></div>
        <pending-bar/>
        <div class="body">
          <nav-ruler/>
          <main class="page"><keep-alive><component :is="pageComp"/></keep-alive></main>
        </div>
      </template>
    </div>`,
  };

  const app = Vue.createApp(App);
  // 界面自己出错时：记下来（window.__errs，排错用）并提醒用户一句，别让页面悄悄变空白
  window.__errs = [];
  app.config.errorHandler = (err, vm, info) => {
    console.error(err);
    window.__errs.push(`${err && err.message || err} @${info}`);
    if (window.__errs.length <= 3) act.toast(`界面出了点小问题：${(err && err.message) || err}（${info}）`, 'err');
  };
  Object.assign(app.config.globalProperties, { S: window.S, act: window.act, store: window.store, signState: window.signState });
  Object.entries(window.COMPONENTS).forEach(([name, c]) => app.component(name, c));
  Object.entries(window.PAGES || {}).forEach(([name, c]) => app.component('page-' + name, c));
  app.mount('#app');
})();
