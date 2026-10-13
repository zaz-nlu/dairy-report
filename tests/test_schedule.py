"""python tests/test_schedule.py —— 用假时间、假日报系统走一遍 tick() 的一天"""
import json
import sys
import tempfile
from datetime import datetime
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

    def submit(self, day, items, defaults, leave=False):
        FakeDelta.calls.append((day.isoformat(), leave))
        if FakeDelta.fail:
            raise bridge.DeltaError("服务器挂了")
        return "submitted"


def make_api(tmp, items):
    cfg = {**config.DEFAULTS, "data_dir": str(tmp), "username": "u", "default_project": "1-2",
           "task_type": "1-3", "report_user": 7}
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


if __name__ == "__main__":
    for t in (test_normal_day, test_retry_then_give_up, test_catch_up_after_sleep,
              test_empty_day_not_fabricated, test_morning_draft_refreshed_unless_edited, test_weekend_and_leave,
              test_interrogate_backoff, test_backlog_across_days):
        t()
    print("ok")
