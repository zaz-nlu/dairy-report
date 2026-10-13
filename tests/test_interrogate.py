"""python tests/test_interrogate.py —— 不调 AI，只测规整/校验逻辑"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from interrogate import build_prompt, finalize, fit_hours, merge_points, parse, sample  # noqa: E402


def test_fit_hours():
    for hours in ([3, 3, 3], [7.3, 0.2], [0, 0, 0], [None, 5], [1] * 6, [100, 1, 1]):
        out = fit_hours(hours, 8.0)
        assert sum(out) == 8.0, (hours, out)
        assert all(h >= 0.5 and h * 2 == int(h * 2) for h in out), (hours, out)
    assert fit_hours([6, 2], 8.0) == [6.0, 2.0]


def test_finalize():
    projects = [{"projectId": p, "projectName": p} for p in ("3-12", "3-13", "3-14")]
    items = [
        {"workInfo": " 1.改了A ", "projectId": "3-12", "workTime": 5, "completionDegree": 83, "confidence": 0.9},
        {"workInfo": "1.改了B", "projectId": "99", "workTime": 3, "completionDegree": 130, "confidence": 0.9},
        {"workInfo": "1.改了C", "projectId": "3-14", "workTime": 1, "completionDegree": -5, "confidence": 0.3},
    ]
    a, b, c = finalize(items, projects, 8.0, "3-13")
    assert a == {"workInfo": "1.改了A", "projectId": "3-12", "workTime": 4.5, "completionDegree": 85, "doubt": False}, a
    assert b["projectId"] == "3-13" and b["doubt"] and b["completionDegree"] == 100  # 不存在的项目 → 默认 + 存疑
    assert c["doubt"] and c["completionDegree"] == 0  # 低置信度 → 存疑


def test_merge_same_project():
    assert merge_points(["1.改A 2.改B", "1.加C，提速 2.5 倍"]) == "1.改A\n2.改B\n3.加C，提速 2.5 倍"
    projects = [{"projectId": "7-1", "projectName": "甲"}, {"projectId": "7-2", "projectName": "乙"}]
    items = [{"workInfo": "1.a", "projectId": "7-1", "workTime": 3, "completionDegree": 30, "confidence": 0.9},
             {"workInfo": "1.b", "projectId": "7-2", "workTime": 1, "completionDegree": 100, "confidence": 0.9},
             {"workInfo": "1.c 2.d", "projectId": "7-1", "workTime": 3, "completionDegree": 60, "confidence": 0.4}]
    got = finalize(items, projects, 8.0, "7-2")
    assert [g["projectId"] for g in got] == ["7-1", "7-2"], got   # 同项目合成一条
    assert got[0]["workInfo"] == "1.a\n2.c\n3.d" and got[0]["doubt"] and got[0]["completionDegree"] == 60
    assert sum(g["workTime"] for g in got) == 8.0 and got[0]["workTime"] > got[1]["workTime"]


def test_skip_private_repo():
    import json
    import tempfile
    from datetime import date
    from interrogate import SKIP, drop_skipped, interrogate
    raw = {"entries": [{"time": "10:00", "source": "claude", "project": "daily-prison", "text": "私活", "files": []},
                       {"time": "11:00", "source": "claude", "project": "dify", "text": "公活", "files": []}],
           "snapshots": [{"time": "12:00", "project": "daily-prison", "files": ["a.py"]}]}
    got = drop_skipped(raw, {"daily-prison": SKIP, "dify": "7-296"})
    assert [e["text"] for e in got["entries"]] == ["公活"] and got["snapshots"] == []
    from interrogate import entry_key
    one = drop_skipped(raw, {}, [entry_key(raw["entries"][1])])  # 单条排除：只去掉那一条，别的仓库不受影响
    assert [e["text"] for e in one["entries"]] == ["私活"] and len(one["snapshots"]) == 1
    assert "私活" not in build_prompt(got, [], [], 8.0)  # 私人项目的内容不会进提示词
    with tempfile.TemporaryDirectory() as tmp:  # 当天只有私活：不调 AI，草稿为空（不会拿私活去交差）
        (Path(tmp) / "2026-10-13").mkdir()
        (Path(tmp) / "2026-10-13" / "raw.json").write_text(json.dumps({"entries": raw["entries"][:1], "snapshots": []}), "utf-8")
        assert interrogate(date(2026, 10, 13), [], 8.0, None, tmp, repo_projects={"daily-prison": SKIP})["items"] == []
        # 只聊天没改代码 + 空白手记：也不能调 AI（否则 AI 会硬编一条"无法生成"交上去）
        talk = {**raw["entries"][1], "files": []}
        (Path(tmp) / "2026-10-13" / "raw.json").write_text(json.dumps({"entries": [talk], "snapshots": []}), "utf-8")
        (Path(tmp) / "2026-10-13" / "notes.json").write_text(json.dumps([{"time": "11:16", "text": " "}]), "utf-8")
        assert interrogate(date(2026, 10, 13), [], 8.0, None, tmp, provider="不存在")["items"] == []


def test_annotate_backlog():
    """分天上报：前几天没报的活流到今天；报过的锁死；勾选优先；私人/永不上报排除"""
    from interrogate import SKIP, annotate, entry_key, uid
    E = lambda t, text, files=(), project="dify", source="claude": {
        "source": source, "time": t, "project": project, "text": text, "files": list(files), "reply": ""}
    mon = [E("09:00", "页面1", ["a.vue"]), E("10:00", "页面2", ["b.vue"]), E("11:00", "闲聊"),
           E("12:00", "私活", ["x.py"], project="daily-prison"), E("13:00", "不想报", ["c.vue"])]
    tue = [E("09:00", "页面3", ["d.vue"]), E("10:00", "给客户讲方案"), E("11:00", "页面4", ["e.vue"]),
           E("12:00", "修bug", source="git")]
    raws = {"2026-10-12": {"entries": mon}, "2026-10-13": {"entries": tue}}
    got = annotate("2026-10-13", raws, {"daily-prison": SKIP},
                   excluded={"2026-10-12": [entry_key(mon[4])]},
                   picks={uid("2026-10-13", tue[1]): True, uid("2026-10-13", tue[2]): False},
                   reported={uid("2026-10-12", mon[0]): "2026-10-12"})
    why = {e["text"]: e["why"] for e in got}
    inc = [e["text"] for e in got if e["included"]]
    assert why == {"页面1": "reported:2026-10-12", "页面2": "work", "闲聊": "talk", "私活": "private",
                   "不想报": "never", "页面3": "work", "给客户讲方案": "picked", "页面4": "unpicked", "修bug": "work"}, why
    assert inc == ["页面2", "页面3", "给客户讲方案", "修bug"], inc  # 周一没报的页面2 流到周二
    assert [e["date"] for e in got][:2] == ["2026-10-12", "2026-10-12"]  # 按日期再按时间排
    # 同一天的日报重新生成时，自己之前用过的条目不算"报过"
    again = annotate("2026-10-12", {"2026-10-12": {"entries": mon[:1]}}, {}, {}, {},
                     {uid("2026-10-12", mon[0]): "2026-10-12"})
    assert again[0]["included"] and again[0]["why"] == "work"
    # 前几天的条目进提示词时带日期，今天的不带
    p = build_prompt({"date": "2026-10-13", "entries": [e for e in got if e["included"]], "snapshots": []}, [], [], 8.0)
    assert "10-12 10:00 [claude] dify: 需求「页面2」" in p and "\n09:00 [claude] dify: 需求「页面3」" in p


def test_parse():
    good = '好的：\n```json\n{"items":[{"workInfo":"1.x","projectId":null,"workTime":8,"completionDegree":50,"confidence":1}]}\n```'
    assert parse(good)[0]["workInfo"] == "1.x"
    for bad in ("没有json", '{"items":[]}', '{"items":[{"workInfo":"","workTime":1}]}',
                '{"items":[{"workInfo":"1.x","workTime":"很多"}]}'):
        try:
            parse(bad)
        except (ValueError, KeyError):
            continue
        raise AssertionError(f"应当拒绝: {bad}")


def test_prompt():
    assert sample(list(range(10)), 5) == [0, 2, 4, 6, 8]
    raw = {"entries": [{"time": "09:00", "source": "git", "project": "dify", "text": "修bug",
                        "files": ["web/a/b.tsx"]}], "snapshots": []}
    hist = [{"date": "2026-10-12", "items": [{"project": "大模型和小智系统", "text": "1.修了知识库bug\n2.改了页面"}]}]
    p = build_prompt(raw, [{"time": "15:00", "text": "开需求评审会"}], [], 8.0, hist)
    assert "09:00 [git] dify: 修bug | a/b/b.tsx" not in p  # 路径只有 3 层以内时原样保留
    assert "09:00 [git] dify: 修bug | web/a/b.tsx" in p and "[用户手记] 开需求评审会" in p and "projectId 一律填 null" in p
    assert "2026-10-12 【大模型和小智系统】1.修了知识库bug 2.改了页面" in p  # 历史日报进了提示词，换行压成一行
    projs = [{"projectId": "7-296", "projectName": "大模型和小智系统"}]
    p = build_prompt(raw, [], projs, 8.0, hist, {"dify": "7-296", "别的仓库": "7-296", "dify2": "不存在的id"})
    assert "修bug | web/a/b.tsx 【用户已指定归属：大模型和小智系统（id 7-296）】" in p  # 用户指定的仓库带上标记
    assert "不存在的id" not in p and "用户已指定归属" not in build_prompt(raw, [], projs, 8.0, hist, {"x": "7-296"}).split("今日证据（时间")[1]


if __name__ == "__main__":
    test_fit_hours()
    test_finalize()
    test_merge_same_project()
    test_skip_private_repo()
    test_annotate_backlog()
    test_parse()
    test_prompt()
    print("ok")
