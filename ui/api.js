// 调后端：window.pywebview.api.<方法>()。要等 pywebviewready 之后才能调。
// - API.call(name, ...args)：慢操作自动显示置顶进度条；出错自动弹提示条并 throw（err.handled = true）
// - API.quiet(name, ...args)：静默版，不显示进度、不弹错（定时刷新用）
(function () {
  let readyPromise;
  function whenReady() {
    if (readyPromise) return readyPromise;
    readyPromise = new Promise((resolve, reject) => {
      const have = () => window.pywebview && window.pywebview.api;
      if (have()) return resolve(window.pywebview.api);
      window.addEventListener('pywebviewready', () => resolve(window.pywebview.api), { once: true });
      setTimeout(() => { if (!have()) reject(new Error('这个界面要在「日报越狱」软件里打开（或网址后面加 ?mock 预览）')); }, 10000);
    });
    return readyPromise;
  }

  const API = {
    whenReady,
    async call(name, ...args) {
      const label = S.slow[name];
      const b = label && { label, t0: Date.now() };
      if (b) store.busy.push(b);
      try {
        return await (await whenReady())[name](...args);
      } catch (e) {
        const err = new Error((e && e.message) || String(e));
        err.handled = true;
        act.toast(S.errPrefix + err.message, 'err');
        throw err;
      } finally {
        if (b) store.busy.splice(store.busy.indexOf(b), 1);
      }
    },
    async quiet(name, ...args) { return (await whenReady())[name](...args); },
    // 页面里 await 一串操作时：出错已经弹过提示了，这里吞掉 handled 的错误，别再冒泡成未捕获异常
    async safe(fn) {
      try { return await fn(); } catch (e) { if (!e.handled) throw e; }
    },
  };
  window.API = API;
})();
