"""python tests/test_schedule.py —— 用假时间、假日报系统走一遍 tick() 的一天"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge  # noqa: E402
import logging
logging.disable()  # 失败场景是故意的，不打堆栈
import config  # noqa: E402


class FakeDelta:
    fail = False
    calls = []

    def projects(self):
        return [{"projectId": "1-2", "projectName": "甲"}]

    def recent_reports(self):
        return []

    def last_defaults(self):
        return {"default_project": "1-2", "task_type": "1-3", "report_user": 7, "priority": 1}

    archive = []   # 假的"日报系统里本人的全部日报"；各测试按需设置
    details = {}

    verify_result = (True, "系统里现有 1 条、共 8.0 小时，和提交的一致")

    def verify(self, day, items):
        if isinstance(FakeDelta.verify_result, Exception):
            raise FakeDelta.verify_result
        return FakeDelta.verify_result

    def my_reports(self, days=90):
        return FakeDelta.archive

    def report_detail(self, main_id):
        return FakeDelta.details[main_id]

    def submit(self, day, items, defaults, leave=False):
        FakeDelta.calls.append((day.isoformat(), leave))
        if FakeDelta.fail:
            raise bridge.DeltaError("服务器挂了")
        return "submitted"


def make_api(tmp, items):
    cfg = {**config.DEFAULTS, "data_dir": str(tmp), "username": "u", "default_project": "1-2",
           "task_type": "1-3", "report_user": 7, "confirm_seconds": 0}   # 0 = 到点直接交；确认倒计时单独测（test_confirm_*）
    config.load = lambda: cfg
    api = bridge.Api()
    api.log = []
    api.fake_now = datetime(2026, 10, 13, 17, 30)
    api._notify_cb = lambda t, m: api.log.append(t)
    api._show_cb = lambda: api.log.append("show")
    api._client = lambda cfg: FakeDelta()
    api.collect_now = lambda date=None: api.log.append("collect")

    def fake_interrogate(date=None):
        api.log.append("interrogate")
        d = {"items": [dict(it) for it in items], "generated_at": api.fake_now.isoformat()}
        bridge._write(Path(tmp) / "2026-10-13" / "draft.json", d)
        return d
    api.interrogate_now = fake_interrogate
    return api, cfg


def at(hm, day="2026-10-13"):  # 2026-10-13 是周二
    return datetime.fromisoformat(f"{day}T{hm}")


ITEM = {"workInfo": "1.修bug", "projectId": "1-2", "workTime": 8.0, "completionDegree": 100, "doubt": False}


def result(tmp):
    return json.loads((Path(tmp) / "2026-10-13" / "result.json").read_text("utf-8"))


def test_normal_day():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [ITEM])
        api.tick(at("10:00"))
        assert api.log == ["collect"], api.log
        api._last_collect = at("10:00")
        api.tick(at("17:29"))
        assert "interrogate" not in api.log
        api.tick(at("17:30"))
        assert api.log.count("interrogate") == 1 and "典狱长：还有 30 分钟查房" in api.log
        api.tick(at("17:31"))
        assert api.log.count("interrogate") == 1  # 草稿已在，不重复审讯
        FakeDelta.calls = []
        api.tick(at("18:00"))
        api.tick(at("18:01"))
        assert FakeDelta.calls == [("2026-10-13", False)] and result(tmp)["status"] == "submitted"
        assert "show" in api.log and "画押成功，今日刑满释放" in api.log


def test_retry_then_give_up():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [ITEM])
        api._last_collect = at("17:00")
        FakeDelta.fail, FakeDelta.calls = True, []
        # 真实时间会写进 result.at，这里按 "at" 字段驱动：每次失败后把 at 改成假时间
        for hm, expect in [("18:00", 1), ("18:02", 1), ("18:05", 2), ("18:10", 2), ("18:15", 3), ("18:40", 3)]:
            before = len(FakeDelta.calls)
            api.tick(at(hm))
            if len(FakeDelta.calls) > before:
                r = result(tmp)
                r["at"] = at(hm).isoformat()
                bridge._write(Path(tmp) / "2026-10-13" / "result.json", r)
            assert len(FakeDelta.calls) == expect, (hm, FakeDelta.calls)
        assert result(tmp)["status"] == "failed" and "越狱失败！¥200 罚单警告" in api.log
        FakeDelta.fail = False


def test_catch_up_after_sleep():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [ITEM])
        FakeDelta.calls = []
        api.tick(at("21:00"))  # 17:30、18:00 都睡过去了，醒来一次补齐
        assert api.log[:2] == ["collect", "interrogate"] and FakeDelta.calls and result(tmp)["status"] == "submitted"


def test_empty_day_not_fabricated():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [])
        api._last_collect = at("17:00")
        FakeDelta.calls = []
        api.tick(at("17:30"))
        api.tick(at("18:00"))
        api.tick(at("18:30"))
        assert FakeDelta.calls == [] and result(tmp)["status"] == "empty"
        n_empty_alerts = api.log.count("越狱警报：认罪书是空的")
        api.tick(at("18:31")); api.tick(at("18:32"))
        assert api.log.count("越狱警报：认罪书是空的") == n_empty_alerts and FakeDelta.calls == []  # 还是空：不反复提醒、不提交
        # 18:35 用户补了内容（比如写了手记，草稿重新生成出了条目）-> 下一次检查就自动提交，不用再手动点「签字画押」
        bridge._write(Path(tmp) / "2026-10-13" / "draft.json", {"items": [dict(ITEM)], "generated_at": "2026-10-13T18:34:00", "edited_at": "2026-10-13T18:34:00"})
        api.tick(at("18:35"))
        assert FakeDelta.calls == [("2026-10-13", False)] and result(tmp)["status"] == "submitted", (FakeDelta.calls, result(tmp))
        api.tick(at("18:36"))
        assert len(FakeDelta.calls) == 1  # 交过了就不再重复


def test_morning_draft_refreshed_unless_edited():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [ITEM])
        api._last_collect = at("17:00")
        api.fake_now = at("11:00")
        api.interrogate_now()  # 上午手动审讯过
        api.tick(at("17:30"))
        assert api.log.count("interrogate") == 2  # 到点重审，补上下午的活
        api.save_draft([ITEM], "2026-10-13")  # 用户改过 → 不再覆盖
        api.tick(at("17:45"))
        assert api.log.count("interrogate") == 2


def test_weekend_and_leave():
    with tempfile.TemporaryDirectory() as tmp:
        api, cfg = make_api(tmp, [ITEM])
        FakeDelta.calls = []
        api.tick(at("18:00", "2026-10-17"))  # 周六
        assert api.log == [] and FakeDelta.calls == []
        cfg["leave_days"] = ["2026-10-13"]
        api.tick(at("18:00"))
        assert FakeDelta.calls == [("2026-10-13", True)] and "interrogate" not in api.log


def test_interrogate_backoff():
    with tempfile.TemporaryDirectory() as tmp:
        api, _ = make_api(tmp, [ITEM])
        api._last_collect = at("17:00")

        def boom(date=None):
            api.log.append("interrogate")
            raise RuntimeError("AI 挂了")
        api.interrogate_now = boom
        for hm in ("17:30", "17:31", "17:39"):
            api.tick(at(hm))
        assert api.log.count("interrogate") == 1
        api.tick(at("17:40"))
        assert api.log.count("interrogate") == 2


def test_backlog_across_days():
    """回看 3 天：手写交过的那天不翻旧账；软件交过的按账本排除；没报的流到今天；勾选的纯对话算进去；提交后记账"""
    from interrogate import uid
    with tempfile.TemporaryDirectory() as tmp:
        api, cfg = make_api(tmp, [])
        cfg["lookback_days"] = 3
        E = lambda t, text, files=("a.vue",): {"source": "claude", "time": t, "project": "dify", "cwd": "",
                                                "text": text, "files": list(files), "reply": ""}
        days = {"2026-10-11": [E("09:00", "A 手写交过的那天")],
                "2026-10-12": [E("09:00", "B1 已报"), E("10:00", "B2 没报")],
                "2026-10-13": [E("09:00", "C 今天"), E("10:00", "T 纯聊天", ())]}
        for d, entries in days.items():  # collected_at 晚于当天 = 已定稿，不会补采
            bridge._write(Path(tmp) / d / "raw.json", {"date": d, "collected_at": "2026-10-14T09:00:00",
                                                       "entries": entries, "snapshots": []})
        bridge._write(Path(tmp) / "2026-10-12" / "result.json",
                      {"status": "submitted", "used": [uid("2026-10-12", days["2026-10-12"][0])]})
        bridge._write(Path(tmp) / "options.json", {"history": [{"date": "2026-10-11", "items": []}]})
        api.pick_entry(uid("2026-10-13", days["2026-10-13"][1]), True, "2026-10-13")

        seen = {}
        api.collect_now = lambda date=None: None
        api._options = lambda cfg, client=None: {"projects": [], "auto": {}, "history": []}
        real_interrogate = bridge.interrogate
        bridge.interrogate = lambda day, *a, evidence=None, **kw: seen.update(evidence=evidence) or {
            "items": [dict(ITEM)], "used": [e["uid"] for e in evidence]}
        try:
            api.interrogate_now = bridge.Api.interrogate_now.__get__(api)
            draft = api.interrogate_now("2026-10-13")
        finally:
            bridge.interrogate = real_interrogate
        assert [e["text"] for e in seen["evidence"]] == ["B2 没报", "C 今天", "T 纯聊天"], seen["evidence"]
        bridge._write(Path(tmp) / "2026-10-13" / "draft.json", draft)
        r = api._submit(datetime(2026, 10, 13).date(), auto=False)
        assert r["status"] == "submitted" and len(r["used"]) == 3, r  # 记账：明天回看时这 3 条锁死
        cfg["lookback_days"] = 3
        nxt = api._annotated(datetime(2026, 10, 14).date(), cfg)
        assert not any(e["included"] for e in nxt), [(e["text"], e["why"]) for e in nxt]

        # 页面打开会调 fetch_options 刷新下拉框：不能把 history 冲掉（冲掉 = 认不出 10-11 交过 = 旧活被重报）
        class Opts(FakeDelta):
            def task_types(self): return []
            def report_users(self): return []
            def recent_reports(self): return [{"date": "2026-10-11", "items": []}]
        api._client = lambda cfg, *a: Opts()
        api.fetch_options()
        assert [h["date"] for h in bridge._read(Path(tmp) / "options.json")["history"]] == ["2026-10-11"]


def test_verify_after_submit():
    """提交后回读核对：一致 -> 通知里带上；不一致 / 回读出错 -> 再单独提醒，但提交状态不变（不会触发重试）"""
    for verdict, expect_ok, expect_warn in (((True, "系统里现有 1 条、共 8.0 小时，和提交的一致"), True, False),
                                            ((False, "系统里现有 1 条、4.0 小时，和提交的 1 条、8.0 小时不一致"), False, True),
                                            (RuntimeError("网络断了"), None, True)):
        with tempfile.TemporaryDirectory() as tmp:
            api, _ = make_api(tmp, [ITEM])
            api._last_collect = at("17:00")
            FakeDelta.fail, FakeDelta.calls, FakeDelta.verify_result = False, [], verdict
            api.tick(at("17:30"))
            api.tick(at("18:00"))
            r = result(tmp)
            assert r["status"] == "submitted" and r["verified"]["ok"] is expect_ok, r      # 状态不因核对结果而变
            assert len(FakeDelta.calls) == 1  # 没有因为核对不一致又提交一次
            assert ("提交了，但回读核对没通过" in api.log) is expect_warn, api.log
            if expect_ok:
                assert "已回读核对" in " ".join(api.log) or "画押成功，今日刑满释放" in api.log
    FakeDelta.verify_result = (True, "系统里现有 1 条、共 8.0 小时，和提交的一致")


def test_ledger_and_missed_days():
    """账本：连续天数遇漏交就断、节假日 / 请假不打断也不加；累计漏交 × 每次罚款 = 累计罚款；档案室里漏交的日子标 missed"""
    with tempfile.TemporaryDirectory() as tmp:
        api, cfg = make_api(tmp, [])
        row = lambda d, hours=0.0, leave=False, holiday=False, missed=False: {
            "date": d, "id": int(d[-2:]), "hours": hours, "leave": leave, "holiday": holiday, "missed": missed, "projects": ["甲"] if hours else []}
        FakeDelta.archive = [                               # 新 -> 旧
            row("2026-10-12", 8.0), row("2026-10-11", holiday=True), row("2026-10-10", 8.0),            # 周六加班也算
            row("2026-10-09", leave=True),                                                              # 请假：跳过，不打断
            row("2026-10-08", 8.0), row("2026-10-07", holiday=True),
            row("2026-09-30", missed=True),                                                             # 漏交：连续到这里为止
            row("2026-09-29", 8.0), row("2026-09-28", 8.0),
            row("2026-09-01", missed=True), row("2026-08-31", 8.0)]
        L = api.ledger()
        assert L["streak"] == 3, L                           # 10-12、10-10、10-08；10-09 请假跳过；09-30 漏交停下
        assert (L["on_time"], L["missed"], L["fines"], L["fine"]) == (6, 2, 200, 100), L
        assert L["last_miss"] == "2026-09-30" and L["since"] == "2026-08-31" and L["missed_dates"] == ["2026-09-30", "2026-09-01"], L
        cfg["fine"] = 150                                    # 罚款金额可改
        assert api.ledger()["fines"] == 300
        h = {r["date"]: r for r in api.history()}
        assert h["2026-09-30"]["status"] == "missed" and h["2026-09-30"]["kind"] == "work"
        assert h["2026-10-11"]["status"] is None and h["2026-10-11"]["kind"] == "rest"   # 系统标的节假日 = 休息
        assert h["2026-10-10"]["status"] == "submitted"
        assert api.get_state()["fine"] == 150
        FakeDelta.archive = []                               # 没数据（没配账号 / 连不上又没缓存）：全 0，不报错
        api._archive = None
        assert api.ledger()["streak"] == 0 and api.ledger()["fines"] == 0


def test_confirm_countdown():
    """到点先弹确认倒计时：不理它就提交；取消就不再自动交；去改一改会宽限；手动提交 / 草稿被改都不会丢"""
    def fresh():
        tmp = tempfile.TemporaryDirectory()
        api, cfg = make_api(tmp.name, [ITEM])
        cfg["confirm_seconds"] = 60
        api._last_collect = at("17:00")
        FakeDelta.fail, FakeDelta.calls = False, []
        api.tick(at("17:30"))                                  # 17:30 出草稿
        return tmp, api, cfg
    # ① 不理它：18:00 弹倒计时（窗口弹出 + 通知），倒计时没到不交，到了自动交
    tmp, api, cfg = fresh()
    api.tick(at("18:00"))
    assert FakeDelta.calls == [] and api._pending and "show" in api.log and any("60 秒后自动画押" in x for x in api.log), api.log
    assert api.get_state()["pending"]["total"] == 60
    api.tick(at("18:00").replace(second=30)); assert FakeDelta.calls == []   # 才 30 秒
    api.tick(at("18:01").replace(second=1)); assert FakeDelta.calls == [("2026-10-13", False)], FakeDelta.calls
    assert api._pending is None and api.get_state()["pending"] is None and result(tmp.name)["status"] == "submitted"
    # ② 取消：之后怎么 tick 都不自动交；手动「签字画押」还能交
    tmp, api, cfg = fresh()
    api.tick(at("18:00")); api.cancel_pending()
    assert api.get_state()["pending"] is None
    for hm in ("18:01", "18:05", "19:00", "23:00"):
        api.tick(at(hm))
    assert FakeDelta.calls == [], FakeDelta.calls
    api.submit_now("2026-10-13"); assert FakeDelta.calls == [("2026-10-13", False)]
    # ③ 去改一改：宽限 10 分钟，期间不交；宽限到了用最新草稿交（改过的内容）
    tmp, api, cfg = fresh()
    api.tick(at("18:00"))
    before = api._pending["deadline"]; api.extend_pending(10)
    assert api._pending["deadline"] >= datetime.now() + timedelta(minutes=9)  # 以真实时间为基准往后推
    api._pending["deadline"] = at("18:10")                     # 测试里把宽限直接设成 18:10
    bridge._write(Path(tmp.name) / "2026-10-13" / "draft.json", {"items": [{**ITEM, "workInfo": "1.我改过的"}],
                  "generated_at": "2026-10-13T18:03:00", "edited_at": "2026-10-13T18:03:00"})
    api.tick(at("18:05")); assert FakeDelta.calls == []
    api.tick(at("18:11")); assert FakeDelta.calls == [("2026-10-13", False)]
    assert result(tmp.name)["items"][0]["workInfo"] == "1.我改过的"  # 交的是改过的
    # ④ 倒计时期间用户自己点了提交：倒计时作废，不会再交第二次
    tmp, api, cfg = fresh()
    api.tick(at("18:00")); api.submit_now("2026-10-13")
    assert api._pending is None and len(FakeDelta.calls) == 1
    api.tick(at("18:02")); api.tick(at("18:05")); assert len(FakeDelta.calls) == 1
    # ⑤ 确认功能不影响失败重试：失败重试直接进行，不再弹倒计时
    tmp, api, cfg = fresh()
    FakeDelta.fail = True
    api.tick(at("18:00")); api.tick(at("18:01").replace(second=1))      # 倒计时到了 -> 提交失败
    assert result(tmp.name)["status"] == "failed" and len(FakeDelta.calls) == 1
    r = result(tmp.name); r["at"] = at("18:01").isoformat(); bridge._write(Path(tmp.name) / "2026-10-13" / "result.json", r)
    FakeDelta.fail = False
    api.tick(at("18:07")); assert len(FakeDelta.calls) == 2 and api._pending is None   # 重试直接交
    FakeDelta.fail = False
    # ⑥ 草稿是空的：没东西可确认，直接给「认罪书是空的」提醒，不弹空倒计时
    tmp = tempfile.TemporaryDirectory()
    api, cfg = make_api(tmp.name, [])
    cfg["confirm_seconds"] = 60
    api._last_collect = at("17:00"); FakeDelta.calls = []
    api.tick(at("17:30")); api.tick(at("18:00"))
    assert api._pending is None and result(tmp.name)["status"] == "empty" and FakeDelta.calls == []


def test_history_counts_manual_days():
    """档案室：手写交的日子（本地没有 result.json，但日报系统里有）算已交，并读出当天的真实内容"""
    with tempfile.TemporaryDirectory() as tmp:
        api, cfg = make_api(tmp, [])
        for d in ("2026-10-11", "2026-10-12"):   # 周日、周一，本地都有数据目录
            (Path(tmp) / d).mkdir()
        bridge._write(Path(tmp) / "2026-10-12" / "draft.json", {"items": [dict(ITEM)]})
        bridge._write(Path(tmp) / "2026-10-13" / "result.json", {"status": "submitted", "items": [dict(ITEM)]})
        FakeDelta.archive = [
            {"date": "2026-10-12", "id": 12, "hours": 8.0, "leave": False, "projects": ["甲"]},
            {"date": "2026-10-09", "id": 9, "hours": 8.0, "leave": False, "projects": ["甲", "乙"]}]
        FakeDelta.details = {9: {"remark": "", "items": [
            {"projectId": "1-2", "workInfo": "1.很早以前手写的", "workTime": 5.0, "completionDegree": 100},
            {"projectId": "1-3", "workInfo": "1.另一个项目", "workTime": 3.0, "completionDegree": 80}]}}
        got = {h["date"]: h for h in api.history()}
        assert got["2026-10-12"]["status"] == "submitted" and got["2026-10-12"]["hours"] == 8.0  # 有本地草稿，沿用它的工时
        assert got["2026-10-09"] == {"date": "2026-10-09", "kind": "work", "status": "submitted", "items": 2, "hours": 8.0,
                                     "projects": ["甲", "乙"]}  # 只在系统里：工时、项目名都来自系统
        assert got["2026-10-11"]["status"] is None  # 本地有目录、系统里没有 = 没交
        assert got["2026-10-13"]["status"] == "submitted"
        assert list(got) == sorted(got, reverse=True)  # 新 -> 旧
        # 案卷详情：日报系统里那天的真实内容
        d = api.day_detail("2026-10-09")
        assert d["remote"]["hours"] == 8.0 and [i["workInfo"] for i in d["remote"]["items"]] == ["1.很早以前手写的", "1.另一个项目"], d
        assert d["draft"] is None and d["result"] is None  # 本地没有这天
        assert api.day_detail("2026-10-11")["remote"] is None  # 系统里没有这天
        # 连不上日报系统：档案室仍然能打开，用上次缓存的概要；详情拿不到就是 null，不抛错
        api._archive = None
        api._client = lambda cfg: (_ for _ in ()).throw(bridge.DeltaError("连不上"))
        assert {h["date"] for h in api.history()} >= {"2026-10-12", "2026-10-09"}  # 缓存在 options.json 里
        assert api.day_detail("2026-10-09")["remote"] is None
        # 换账号：内存缓存和磁盘缓存都不能把上一个账号的日报带过来
        cfg["username"] = "other"
        assert api._remote_archive(cfg) == []
        # 换账号时主动清缓存；options.json 已是新账号的（向导先 fetch 再保存）则保留
        f = Path(tmp) / "options.json"
        bridge._write(f, {"user": "u", "projects": [1]})
        api._drop_cache(cfg)
        assert not f.exists() and api._archive is None
        bridge._write(f, {"user": "other", "projects": [2]})
        api._drop_cache(cfg)
        assert f.exists()


def test_reminders_when_not_submitted():
    """取消了自动提交 -> 过了 remind_times 每个时刻提醒一次；交上之后不再提醒；晚启动只补最近一个"""
    R = "典狱长：还没画押！"
    with tempfile.TemporaryDirectory() as tmp:
        api, cfg = make_api(tmp, [ITEM])
        cfg["confirm_seconds"] = 60
        api._last_collect = at("17:00"); FakeDelta.calls = []
        api.tick(at("17:30")); api.tick(at("18:00"))
        assert api._pending and api.log.count(R) == 0
        api.cancel_pending()
        api.tick(at("18:29")); assert api.log.count(R) == 0
        api.tick(at("18:30")); api.tick(at("18:31")); assert api.log.count(R) == 1   # 一个时刻只提醒一次
        api.tick(at("19:00")); assert api.log.count(R) == 2
        assert FakeDelta.calls == []   # 取消了就不会自动交
        cfg["remind_times"] = ["18:30", "坏格式", "19:00"]
        api._reminded.clear(); api.log.clear()
        api.tick(at("19:40")); assert api.log.count(R) == 1   # 晚启动：只补一条，坏格式忽略
        api.submit_now()
        api.log.clear(); api._reminded.clear()
        api.tick(at("20:00")); assert api.log.count(R) == 0   # 交上了就不提醒
    with tempfile.TemporaryDirectory() as tmp:    # 提醒关掉
        api, cfg = make_api(tmp, [])
        cfg["remind_times"] = []
        api._last_collect = at("17:00")
        api.tick(at("17:30")); api.tick(at("18:00")); api.tick(at("19:00"))
        assert R not in api.log


if __name__ == "__main__":
    for t in (test_normal_day, test_retry_then_give_up, test_catch_up_after_sleep,
              test_empty_day_not_fabricated, test_morning_draft_refreshed_unless_edited, test_weekend_and_leave,
              test_interrogate_backoff, test_backlog_across_days, test_verify_after_submit, test_ledger_and_missed_days, test_confirm_countdown, test_history_counts_manual_days, test_reminders_when_not_submitted):
        t()
    print("ok")
