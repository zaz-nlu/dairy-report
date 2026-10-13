"""python tests/test_delta.py —— 不联网：假 _call 记录请求，断言两步提交的载荷和防重复"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_client import Delta, _flatten  # noqa: E402

DAY = date(2026, 10, 13)
ITEMS = [{"workInfo": "1.修bug", "projectId": "7-275", "workTime": 6.5, "completionDegree": 80},
         {"workInfo": "1.写文档", "projectId": "7-274", "workTime": 1.5, "completionDegree": 100}]
DEFAULTS = {"taskTypeId": "7-4", "reportUserId": "7", "priority": 2}


def fake(existing=None):
    """没有 __init__ 的 Delta：不登录；existing = 当天已有的主表行"""
    d = Delta.__new__(Delta)
    d.calls = []

    def _call(method, path, body=None, params=None):
        d.calls.append((path, body))
        if path == "/dailymain/list":
            return {"page": {"list": [existing] if existing else []}}
        if path == "/dailymain/save":
            return {"data": 99, "groupId": 7}
        return {"data": None, "groupId": 7}
    d._call = _call
    return d


def test_flatten():
    groups = [{"groupName": "研发一部", "groupId": 7, "list": [{"projectId": "7-1", "projectName": "甲"}]},
              {"groupName": "研发二部", "groupId": 8, "list": [{"projectId": "8-2", "projectName": "乙"}]}]
    assert [r["projectName"] for r in _flatten(groups, "projectName")] == ["研发一部 / 甲", "研发二部 / 乙"]
    assert _flatten(groups[:1], "projectName")[0]["projectName"] == "甲"  # 单部门不加前缀
    assert _flatten([], "projectName") == [] and _flatten([{"groupName": "x", "list": None}], "projectName") == []


def test_fresh_submit():
    d = fake()
    assert d.submit(DAY, ITEMS, DEFAULTS) == "submitted"
    paths = [p for p, _ in d.calls]
    assert paths == ["/dailymain/list", "/dailymain/save", "/daily/saveorupdate"], paths
    assert d.calls[1][1] == {"dateTime": "2026-10-13", "remark": "", "isLeave": 0}
    body = d.calls[2][1]
    assert body["mainId"] == 99 and len(body["list"]) == 2
    row = body["list"][0]
    assert (row["isProjTaskId"], row["isProjTaskTypeId"], row["sendUserId"]) == (275, 4, 7)  # "7-275" → 275，"7" → 7
    assert (row["groupId"], row["mainId"], row["workTime"], row["completionDegree"], row["priority"]) == (7, 99, 6.5, 80, 2)


def test_already_submitted_is_skipped():
    d = fake({"id": "5", "dateTime": "2026-10-13", "allWorkTime": "8.0", "isLeave": "0"})
    assert d.submit(DAY, ITEMS, DEFAULTS) == "exists"
    assert [p for p, _ in d.calls] == ["/dailymain/list"]  # 没有任何写入


def test_half_done_reuses_main():
    """上次主表存了、明细失败（工时 0）：重试复用主表，不能再 save 一个"""
    d = fake({"id": "5", "dateTime": "2026-10-13", "allWorkTime": "0.0", "isLeave": "0", "remark": "系统自动补全"})
    assert d.submit(DAY, ITEMS, DEFAULTS) == "submitted"
    paths = [p for p, _ in d.calls]
    assert "/dailymain/save" not in paths and "/dailymain/update" in paths, paths
    assert d.calls[-1][1]["mainId"] == 5, d.calls[-1]  # 字符串 id 转数字，和网页一致


def test_leave_day_counts_as_done():
    assert Delta._done({"id": "5", "allWorkTime": "0.0", "isLeave": "1"})  # 请假日 0 工时也算交过
    assert not Delta._done({"id": "5", "allWorkTime": "0.0", "isLeave": "0"}) and not Delta._done(None)


def test_last_defaults_from_history():
    d = Delta.__new__(Delta)
    rows = [{"id": "3", "dateTime": "2026-10-11", "allWorkTime": "0.0"},   # 系统自动补的空日报：跳过
            {"id": "2", "dateTime": "2026-10-12", "allWorkTime": "8.0"},
            {"id": "1", "dateTime": "2026-10-10", "allWorkTime": "8.0"}]

    def _call(method, path, body=None, params=None):
        if path == "/dailymain/list":
            return {"page": {"list": rows}}
        assert path == "/dailymain/info/2", path   # 取的是最近一份有工时的
        return {"daily": [{"groupId": "7", "isProjTaskId": "296", "isProjTaskTypeId": "4", "sendUserId": "5", "priority": "1"}]}
    d._call = _call
    assert d.last_defaults() == {"default_project": "7-296", "task_type": "7-4", "report_user": "5", "priority": 1}
    rows.clear()
    assert d.last_defaults() == {}  # 新同事没有历史：交给设置页手选


def test_leave():
    d = fake()
    assert d.submit(DAY, [], {}, leave=True) == "submitted"
    assert d.calls[1][1]["isLeave"] == 1 and "/daily/saveorupdate" not in [p for p, _ in d.calls]


if __name__ == "__main__":
    for t in (test_flatten, test_fresh_submit, test_already_submitted_is_skipped, test_half_done_reuses_main, test_leave_day_counts_as_done, test_last_defaults_from_history, test_leave):
        t()
    print("ok")
