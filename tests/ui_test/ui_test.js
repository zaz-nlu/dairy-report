const out = [];
const log = (name, ok, extra = '') => out.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`);
const wait = ms => new Promise(r => setTimeout(r, ms));
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
async function until(fn, ms = 9000, step = 50) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) {} await wait(step); } return false; }
const btn = t => $$('button').find(b => b.textContent.trim().includes(t));
const type = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
const st = () => API.quiet('get_state');
const scenario = async k => { MOCK.set(k); await wait(30); await until(() => store.s && !store.regenerating); await wait(250); };
const settle = async () => { await until(() => store.regenerating, 3000); await until(() => !store.regenerating, 9000); await wait(300); };

(async () => {
  try {
    await until(() => window.store && store.s);
    // ---------- 1. 状态：木牌的模式和内容 ----------
    const expect = { calm: 'calm', lt2h: 'sweat', lt30: 'panic', pending: 'pending', done: 'done', exists: 'done', late: 'late', failed: 'failed', empty: 'panic', emptyres: 'empty', rest: 'free', leave: 'leave' };
    for (const [k, mode] of Object.entries(expect)) {
      await scenario(k);
      const cls = $('.sign-wrap') ? $('.sign-wrap').className : '';
      const hasDigits = !!$('.digits'), wantDigits = ['calm', 'sweat', 'panic'].includes(mode);
      log(`状态 ${k} -> mode-${mode}`, cls.includes('mode-' + mode) && hasDigits === wantDigits, cls);
    }
    await scenario('lt30'); log('<30 分钟：警告气泡 + 数字闪烁', !!$('.bubble') && $('.digits').classList.contains('blink'));
    log('<30 分钟：气泡里的罚款金额来自设置', $('.bubble').textContent.includes('¥100'), $('.bubble').textContent);
    await scenario('late'); log('过点没交：「立即补交」按钮 + 越狱失败印章', !!btn('立即补交') && !!$('.sign .stamp'));
    log('过点没交：木牌标题带罚款金额（不写死）', $('.sign-title').textContent.includes('¥100'), $('.sign-title').textContent);
    await until(() => store.ledger, 3000); await wait(200);
    log('过点没交：账本里提示「今天要再罚 ¥100」', $('.card.tr').textContent.includes('今天已过点还没交') && $('.card.tr .money'));
    await scenario('failed'); log('失败：显示错误原因 + 补交按钮', $('.sign-sub').textContent.includes('连不上日报系统') && !!btn('立即补交'));
    await scenario('done'); log('已画押：牢门打开 + 绿色印章 + 明日收监', !!$('.celldoor.open') && !!$('.stamp.t-green') && $('.sign-sub').textContent.includes('09:00'));
    log('已画押：木牌上显示「已回读核对」', $('.sign-sub').textContent.includes('已回读核对') && $('.sign-sub').textContent.includes('一致'));
    await scenario('emptyres'); log('18:00 后草稿为空：说明原因和补救，没有倒计时', $('.sign-sub').textContent.includes('手记') && !$('.digits'));
    await scenario('empty'); store.page = 'home'; await wait(300);
    log('草稿为空：首页给出明确提示（不是悄悄隐藏）', $('.empty') && $('.empty').textContent.includes('没有可写进日报的改动'));
    store.page = 'draft'; store.draftTab = 'draft'; await wait(300);
    log('草稿为空：认罪书页提示怎么补救 + 不能画押', $('.card.empty').textContent.includes('不处理的话到点不会提交') && btn('签字画押').disabled);
    store.page = 'home';
    await scenario('rest'); log('周末：太阳 + 放风文案', !!$('.sunchain') && $('.sign-title').textContent.includes('放风'));
    await scenario('calm');
    const d = $('.digits').textContent.replace(/\s/g, ''); log('倒计时格式 HH:MM:SS', /^\d\d:\d\d:\d\d$/.test(d), d);
    const d1 = d; await wait(2100); const d2 = $('.digits').textContent.replace(/\s/g, ''); log('倒计时每秒在走', d1 !== d2, d1 + ' -> ' + d2);

    // ---------- 1b. 滚动：内容比窗口长时必须能滚动（曾经没有滚动条，不全屏看不全） ----------
    store.page = 'archive'; await until(() => $$('.case').length > 10); await wait(200);
    const pg = $('.page');
    log('页面区域高度 = 窗口剩余高度（没被内容撑高）', pg.clientHeight > 100 && pg.clientHeight < window.innerHeight, `page ${pg.clientHeight} / 窗口 ${window.innerHeight}`);
    log('长页面可滚动（内容 > 可见区域）', pg.scrollHeight > pg.clientHeight + 50 && getComputedStyle(pg).overflowY === 'auto', `scrollHeight ${pg.scrollHeight}`);
    pg.scrollTop = 400; await wait(100); log('滚动真的生效', pg.scrollTop > 0, 'scrollTop ' + pg.scrollTop);
    pg.scrollTop = 0; store.page = 'home'; await wait(150);
    log('整个应用不超出窗口（不会有页面级滚动）', document.documentElement.scrollHeight <= window.innerHeight + 1, `${document.documentElement.scrollHeight} / ${window.innerHeight}`);

    // ---------- 2. 导航 ----------
    $$('.plate')[1].click(); await wait(200); log('点「认罪书」门牌进入认罪书页', !!$('.draftpage'));
    $$('.plate')[2].click(); await until(() => $$('.case').length); log('档案室：列出案卷', $$('.case').length > 10, $$('.case').length + ' 行');
    $$('.case-row')[1].click(); await until(() => $('.case-detail .pv-item')); log('档案室：点开案卷看到认罪书', !!$('.case-detail .pv-item'));
    log('档案室：星期没有重复的「周周」', !$$('.case-date small').some(s => s.textContent.includes('周周')));
    log('档案室：漏交的日子标红色「漏交」并显示 -¥100', $$('.case').some(c => c.querySelector('.stamp') && c.querySelector('.stamp').textContent.includes('漏交') && c.textContent.includes('-¥100')));
    log('档案室：顶部有累计漏交和罚款汇总', !!$('.ledger-sum') && $('.ledger-sum').textContent.includes('累计罚款'));
    log('档案室：每行显示当天报的项目名', $$('.case-projs').some(e => e.textContent.includes('大模型和小智系统')));
    const rd = $('.case-detail'); log('档案室：点开能看到日报系统里的真实内容（工时、完成度、正文）',
      !!rd && rd.textContent.includes('日报系统里的记录') && rd.textContent.includes('适配了火狐112浏览器') && rd.textContent.includes('禅道BUG修复') && rd.textContent.includes('100%'));
    $$('.case-row')[1].click(); await wait(100); $$('.case-row').find(r => r.textContent.includes('放风')).click(); await until(() => $('.case-detail') && !$('.case-detail').textContent.includes('正在调卷宗'), 3000);
    log('没有记录的日子点开：说明「没有记录」而不是空白', $('.case-detail').textContent.includes('这天没有记录'));
    $$('.plate')[0].click(); await wait(200);

    // ---------- 3. 认罪书编辑 / 保存 / 依据不丢 ----------
    await scenario('calm'); store.page = 'draft'; store.draftTab = 'draft'; await wait(250);
    log('草稿卡片 2 张 + 存疑印章', $$('.card.item').length === 2 && $$('.card.item .stamp').length === 1);
    log('依据折叠区可见', $$('details.basis').length === 2);
    type($$('textarea.ta')[0], '1.我改过的内容'); await wait(100);
    log('编辑后出现「有未保存的修改」', store.draftDirty === true && $('.actionbar').textContent.includes('未保存'));
    btn('保存认罪书').click(); await until(() => !store.draftDirty); await wait(300);
    const s1 = await st();
    log('保存后后端收到：内容 + 标记已手改', s1.draft.items[0].workInfo === '1.我改过的内容' && !!s1.draft.edited_at);
    log('保存后依据原样保留', s1.draft.items[0].basis.length === 2 && s1.draft.items[1].basis.length === 1);
    log('保存后存疑章去掉（人看过了）', s1.draft.items.every(i => i.doubt === false));
    btn('加一条').click(); await wait(200); log('加一条 -> 3 张卡片', $$('.card.item').length === 3);
    $$('.card.item .btn.ghost')[2].click(); await wait(200); log('删除这条 -> 2 张卡片', $$('.card.item').length === 2);
    const total = $('.total').textContent; log('合计工时显示', /合计\s*8/.test(total.replace(/\s+/g, ' ')), total.trim());

    // ---------- 4. 未保存时，后台出新草稿不覆盖 ----------
    type($$('textarea.ta')[0], '1.我正在写，还没保存'); await wait(100);
    await API.quiet('interrogate_now'); await until(() => $('.alert'), 6000);
    log('后台新草稿：只提示，不冲掉未保存的修改', !!$('.alert') && $$('textarea.ta')[0].value === '1.我正在写，还没保存');
    btn('载入新草稿').click(); await wait(300);
    log('点「载入新草稿」后换成后端的', $$('textarea.ta')[0].value !== '1.我正在写，还没保存' && !$('.alert'));

    // ---------- 5. 依据记录：分组 / 勾选 / 锁定 / 永不上报 ----------
    await scenario('calm'); store.page = 'draft'; store.draftTab = 'records'; await wait(300);
    const repos = $$('.group .repo').map(e => e.textContent);
    log('按仓库分组', repos.includes('dify-1.16.0') && repos.includes('gpu-embed') && repos.includes('daily-prison'), repos.join(','));
    log('提交记录与 AI 对话分开显示', $$('.subh').some(h => h.textContent.includes('提交记录')) && $$('.subh').some(h => h.textContent.includes('AI 对话')));
    log('纯聊天默认折叠、不勾选', $$('details.rest').length >= 1 && !!$$('details.rest .rec input')[0] && !$$('details.rest .rec input')[0].checked);
    log('回看 1 天时没有昨天的记录', !$$('.rec').some(r => r.textContent.includes('菜单授权')));

    const before = (await st()).draft.generated_at;
    const sel = $$('.group-head select')[0]; type(sel, '7-300');
    log('改仓库项目 1.2 秒后自动重新审讯', await until(() => store.regenerating, 3000));
    log('重新审讯期间：置顶进度条 + 草稿区等待提示', await until(() => !!$('.busybar'), 2000) && !!$('.scanning'));
    await until(() => !store.regenerating, 9000); await wait(300);
    const after = (await st()).draft.generated_at;
    log('审讯完成后草稿已更新', after !== before, before + ' -> ' + after);
    log('仓库归属已保存', (await st()).repo_projects[$$('.group .repo')[0].textContent] === '7-300');

    const gsel = $$('.group-head select').find((s, i) => $$('.group .repo')[i].textContent === 'daily-prison');
    type(gsel, '__skip__'); await settle();
    const dg = $$('.group').find(g => g.textContent.includes('daily-prison'));
    log('私人项目：整组变灰', dg.classList.contains('skipgrp'));
    log('私人项目的记录被锁、折叠', dg.querySelectorAll('details.rest .rec input[disabled]').length >= 1);

    const row = $$('.group:not(.skipgrp) .rec').find(r => r.textContent.includes('做导出按钮'));
    const cb = row.querySelector('input'); const was = cb.checked;
    cb.checked = !was; cb.dispatchEvent(new Event('change', { bubbles: true }));
    await until(() => store.dialog || store.regenerating, 3000); if (store.dialog) act.answer(true);
    await settle();
    const e1 = (await st()).entries.find(e => e.text.includes('做导出按钮')); log('取消勾选 -> 后端 included 变化', e1.included === !was, 'was ' + was + ' now ' + e1.included);
    const nv = $$('.rec .link').find(l => l.textContent.includes('永不上报')); nv.click();
    await until(() => store.dialog || store.regenerating, 3000); if (store.dialog) act.answer(true);
    await settle();
    log('永不上报后该记录出现「恢复」', $$('.rec .link').some(l => l.textContent.includes('恢复')));

    const lb = $$('.card select.sel')[0]; type(lb, '3'); await until(() => store.dialog || store.regenerating, 3000); if (store.dialog) act.answer(true);
    await settle();
    const rs = $$('.rec').map(r => r.textContent);
    log('回看 3 天：出现前几天的记录（带日期）', rs.some(t => t.includes('菜单授权')) && $$('.rec b').some(b => /\d\d-\d\d \d\d:\d\d/.test(b.textContent)));
    const mb = $$('.rec').find(r => r.textContent.includes('2026-10-12 有手写日报'));
    log('手写日报那天的记录不锁死、可勾选，并说明不确定', !!mb && !mb.querySelector('input').disabled && !mb.querySelector('input').checked);

    // ---------- 6. 首页：手记 / 连续天数 ----------
    await scenario('calm'); store.page = 'home'; await wait(400);
    log('首页：预览 2 条 + 存疑提示', $$('.pv-item').length === 2 && !!$('.card-title .stamp'));
    await until(() => store.ledger, 3000); await wait(200);
    const L0 = store.ledger;
    log('首页：粉笔正字按账本的连续天数画（每 5 天一个「正」）', $$('.chalk .tally svg').length === Math.ceil(L0.streak / 5) && $$('.chalk .tally svg path').length === L0.streak, `streak ${L0.streak}`);
    const card = $('.card.tr').textContent;
    log('首页账本：连续天数 + 累计漏交次数 + 累计罚款（金额 = 次数 × 每次罚款）', card.includes('累计漏交') && card.includes('¥' + L0.fines) && L0.fines === L0.missed * 100, `漏交 ${L0.missed} 次 ¥${L0.fines}`);
    log('首页账本：卡片上不放长说明（精简），说明在悬停提示里', card.length < 90 && !card.includes('日报系统里的记录') && $('.card.tr').title.includes('日报系统里的记录') && $('.card.tr').title.includes('最近一次漏交'), `卡片文字 ${card.length} 字`);
    log('首页账本：今天还没到点时不显示「今天要是漏交」的假设提示', !card.includes('今天要是漏交') && !card.includes('累计罚款将变成'));
    type($('input.inp.grow'), '下午给客户讲了方案'); await wait(100); btn('记下').click(); await until(() => $$('.tl-row .tag.note').length >= 2, 3000);
    log('添加手记并显示', $$('.tl-row').some(r => r.textContent.includes('下午给客户讲了方案')));
    await settle();
    log('手记添加后自动重新审讯完成', !store.regenerating);

    // ---------- 7. 设置 + 装备检测 ----------
    await scenario('calm'); store.page = 'office'; await until(() => $('.office'), 3000); await wait(1500);
    log('设置页：账号回显、密码占位', $('.office input.inp').value === 'liuyuchen' && $$('.office input[type=password]')[0].placeholder.includes('已保存'));
    log('下拉框有选项（项目 / 任务类型 / 汇报人）', $$('.office select').some(s => s.options.length > 8) && $$('.office select').some(s => [...s.options].some(o => o.text === '开发')));
    btn('检测并试一下').click();
    log('检测中：按钮禁用 + 进度条', await until(() => $('.aicheck progress') && btn('检测并试一下').disabled, 4000));
    await until(() => $$('.ai-row').length === 3, 4000);
    log('逐个检测：某一行显示「正在真实调用」', await until(() => $$('.ai-row').some(r => r.textContent.includes('正在真实调用')), 6000));
    await until(() => !btn('检测并试一下').disabled, 20000); await wait(200);
    log('检测完成：2 个能用 1 个不能用并给原因', $$('.ai-row .okc').length === 2 && $$('.ai-row .warnc').length === 1 && $('.ai-row .warnc').textContent.includes('not supported'));
    type($('.office textarea.ta'), 'C:\\tools\\claude-ds.cmd'); await wait(100);
    log('改了设置 -> 保存按钮可点', !btn('保存设置').disabled);
    btn('保存设置').click(); await wait(1200);
    log('保存设置成功（提示条）', $$('.toast').some(t => t.textContent.includes('已保存')));

    const fineInp = $$('.office label.f').find(l => l.textContent.includes('漏交罚款')).querySelector('input'); type(fineInp, '50'); await wait(100);
    btn('保存设置').click(); await wait(1200); await until(() => store.s.fine === 50, 3000);
    log('设置里改罚款金额 -> 后端保存', store.s.fine === 50, 'fine=' + store.s.fine);
    store.page = 'home'; await act.loadLedger(); await wait(300);   // 不能 scenario()：它会重置假后端，罚款又变回 100
    log('改成 50 后：侧栏标语、账本金额跟着变，不是写死的 100', $('.ruler-foot').textContent.includes('¥50') && store.ledger.fines === store.ledger.missed * 50 && $('.card.tr').textContent.includes('¥' + store.ledger.fines), $('.ruler-foot').textContent.trim());
    store.page = 'office'; await wait(300);

    // ---------- 7b. 调试页和正式界面之间要能来回（曾经进去了出不来） ----------
    const dbg = await (await fetch('../../ui/debug.html')).text().catch(() => '');
    log('设置页有「调试页」入口，调试页有「返回正式界面」链接', btn('调试页') !== undefined && (dbg === '' || dbg.includes('返回正式界面')), dbg === '' ? 'file:// 读不到，只检查入口' : '');

    // ---------- 8. 入狱登记向导 ----------
    await scenario('fresh'); await wait(300);
    log('新同事：首先看到入狱登记', !!$('.wizard') && !$('.sign-wrap'));
    const ins = $$('.wizard input'); type(ins[0], 'newbie'); type(ins[1], 'wrong'); await wait(80); btn('登录并核对').click();
    log('密码错：停在第一步并显示原因', await until(() => $('.err-box'), 4000) && $('.err-box').textContent.includes('不正确') && !!$('.wizard .steps li.on'));
    type($$('.wizard input')[1], 'right'); await wait(80); btn('登录并核对').click();
    log('密码对：进入第 2 步并自动检测装备', await until(() => $('.wizard .aicheck .ai-row'), 5000));
    await until(() => !btn('下一步').disabled, 4000); btn('下一步').click(); await wait(300);
    log('第 3 步：牢门打开 + 完成按钮', !!$('.wizard .celldoor.open') && !!btn('入狱登记完成'));
    btn('入狱登记完成').click(); await until(() => $('.sign-wrap'), 3000);
    log('完成登记后进入牢房', !!$('.sign-wrap') && !$('.wizard') && store.page === 'home');

    // ---------- 8b. 到点后的提交确认倒计时 ----------
    await scenario('confirm'); await wait(500);
    log('18:00 到点：弹出确认窗口，显示将要提交的内容', !!$('.confirm-dialog') && $$('.confirm-dialog .pv-item').length === 2 && $('.confirm-dialog').textContent.includes('适配') === false);
    const t1 = $('.confirm-dialog .digits-sm').textContent;
    log('确认窗口：显示倒计时（N 秒后自动提交）', /\d+ 秒后自动提交/.test(t1), t1);
    await wait(2200); const t2 = $('.confirm-dialog .digits-sm').textContent;
    log('倒计时在走', t1 !== t2, t1 + ' -> ' + t2);
    log('确认窗口有三个按钮：立即提交 / 去改一改 / 取消', !!btn('立即提交') && !!btn('去改一改') && !!btn('取消本次自动提交'));
    log('倒计时期间木牌是「正在画押」而不是「越狱失败」', $('.sign-wrap').className.includes('mode-pending') && !$('.sign-wrap').className.includes('mode-late'));
    // 去改一改：窗口收起 + 宽限 10 分钟 + 跳到认罪书 + 顶部小倒计时条
    btn('去改一改').click(); await until(() => $('.pendingbar'), 3000); await wait(300);
    log('去改一改：弹窗收起，顶部出现小倒计时条', !$('.confirm-dialog') && !!$('.pendingbar') && store.page === 'draft');
    log('去改一改：自动提交被宽限（约 10 分钟后）', /分/.test($('.pendingbar').textContent), $('.pendingbar').textContent.trim().slice(0, 30));
    type($$('textarea.ta')[0], '1.我在宽限期里改的'); await wait(150);
    log('宽限期里有未保存的修改：小条上提醒「保存了才算数」', $('.pendingbar').textContent.includes('未保存'));
    // 小条上取消：要先确认，确认后不再自动提交
    $('.pendingbar .btn.danger').click(); await until(() => store.dialog, 2000);
    log('取消自动提交要二次确认（说明会漏交的风险）', !!$('.dialog') && $('.dialog').textContent.includes('漏交'));
    act.answer(true); await until(() => !$('.pendingbar'), 3000); await wait(300);
    log('取消后：小条和弹窗都消失，后端不再有倒计时', !$('.pendingbar') && !$('.confirm-dialog') && (await st()).pending === null);
    // 立即提交
    await scenario('confirm'); await wait(400); btn('立即提交').click(); await until(() => store.s.result && store.s.result.status === 'submitted', 6000); await wait(400);
    log('点「立即提交」：交了，弹窗消失，木牌已画押', !$('.confirm-dialog') && $('.sign-wrap').className.includes('mode-done'));
    // 不理它：倒计时结束自动提交
    await scenario('confirm'); await wait(300);
    log('不理它：倒计时结束自动提交，弹窗消失', await until(() => store.s.result && store.s.result.status === 'submitted' && !$('.confirm-dialog'), 80000, 500));
    // 设置里能改确认秒数
    await scenario('calm'); store.page = 'office'; await until(() => $('.office'), 3000); await wait(1200);
    const csec = $$('.office label.f').find(l => l.textContent.includes('确认倒计时')); log('设置里有「确认倒计时秒数」，默认 60', !!csec && csec.querySelector('input').value === '60');

    // ---------- 9. 提交 ----------
    await scenario('lt30'); store.page = 'home'; await wait(300);
    btn('签字画押').click(); await until(() => store.dialog, 2000);
    log('提交前有确认框', !!$('.dialog'));
    act.answer(true); await until(() => $('.busybar'), 2000); log('提交中：置顶进度条', !!$('.busybar'));
    await until(() => store.s.result && store.s.result.status === 'submitted', 6000); await wait(400);
    log('提交成功：木牌变已画押', $('.sign-wrap').className.includes('mode-done'));
    await scenario('late'); btn('立即补交').click(); await until(() => store.s.result, 6000); await wait(400);
    log('过点后「立即补交」直接提交并成功', $('.sign-wrap').className.includes('mode-done'));
  } catch (e) { log('测试脚本异常', false, String(e && e.stack || e).slice(0, 400)); }
  $('#out').textContent = out.join('\n') + '\n\n' + out.filter(l => l.startsWith('FAIL')).length + ' 项失败 / ' + out.length + ' 项';
  document.title = 'DONE';
})();
