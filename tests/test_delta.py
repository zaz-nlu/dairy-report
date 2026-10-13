"""python tests/test_delta.py —— 不联网：假 _call 记录请求，断言两步提交的载荷和防重复"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_client import Delta, DeltaError, _flatten  # noqa: E402

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


def test_my_reports_and_detail():
    """档案室 / 账本用：每一天的状态——交了 / 请假 / 节假日 / 漏交（系统次日凌晨补的空日报）；翻页取完；字段格式照真实接口（全是字符串）"""
    d = Delta.__new__(Delta)
    rows = [{"id": "3", "dateTime": "2026-10-11", "allWorkTime": "0.0", "isLeave": "0", "isHolidays": "1", "isHaveProject": ""},   # 周日，系统标的节假日
            {"id": "2", "dateTime": "2026-10-12", "allWorkTime": "8.0", "isLeave": "0", "isHolidays": "0",
             "isHaveProject": "<li class='workinfo'>大模型和小智系统</li><li class='workinfo'>地面态势和预测项目</li>"},
            {"id": "4", "dateTime": "2026-10-08", "allWorkTime": "0.0", "isLeave": "1", "isHolidays": "0", "isHaveProject": ""},   # 请假日
            {"id": "5", "dateTime": "2026-10-09", "allWorkTime": "0.0", "isLeave": "0", "isHolidays": "0", "isHaveProject": "",
             "remark": "系统自动补全"},                                                                                              # 漏交
            {"id": "1", "dateTime": "2026-10-10", "allWorkTime": "8.0", "isLeave": "0", "isHolidays": "0", "isHaveProject": "<li>甲</li>"}]
    pages = []

    def _call(method, path, body=None, params=None):
        if path == "/dailymain/list":
            assert params["isself"] == 1 and params["limit"] == 100
            pages.append(params["page"])
            chunk = rows[(params["page"] - 1) * 2: params["page"] * 2]       # 每页只给 2 条，逼它翻页
            return {"page": {"list": chunk, "totalCount": len(rows)}}
        assert path == "/dailymain/info/1"
        return {"dailyMain": {"remark": "备注"}, "daily": [
            {"groupId": "7", "isProjTaskId": "296", "workInfo": "1.适配了火狐112浏览器" + chr(10) + "2.修复禅道BUG", "workTime": "8.0", "completionDegree": "100"}]}
    d._call = _call
    got = d.my_reports()
    assert pages == [1, 2, 3], pages  # 5 条、每页 2 条 -> 翻 3 页取完
    flags = [(r["date"], r["id"], r["hours"], r["leave"], r["holiday"], r["missed"]) for r in got]
    assert flags == [("2026-10-12", 2, 8.0, False, False, False), ("2026-10-11", 3, 0.0, False, True, False),
                     ("2026-10-10", 1, 8.0, False, False, False), ("2026-10-09", 5, 0.0, False, False, True),   # 只有这一天是漏交
                     ("2026-10-08", 4, 0.0, True, False, False)], flags   # 新 -> 旧
    assert got[0]["projects"] == ["大模型和小智系统", "地面态势和预测项目"]
    det = d.report_detail(1)
    assert det == {"remark": "备注", "items": [{"projectId": "7-296", "workInfo": "1.适配了火狐112浏览器" + chr(10) + "2.修复禅道BUG",
                                                 "workTime": 8.0, "completionDegree": 100}]}, det


def test_verify_readback():
    """回读核对：条数和总工时一致才算通过；系统里没有当天日报 / 工时对不上 / 条数对不上都要报不一致"""
    items = [{"workTime": 5.0}, {"workTime": 3.0}]

    def make(main, rows):
        d = Delta.__new__(Delta)
        d.find_main = lambda day: main
        d.report_detail = lambda main_id: {"remark": "", "items": [{"workTime": w} for w in rows]}
        return d
    done = {"id": "7", "allWorkTime": "8.0", "isLeave": "0"}
    ok, note = make(done, [5.0, 3.0]).verify(DAY, items)
    assert ok and "一致" in note, note
    assert not make(done, [5.0, 1.0]).verify(DAY, items)[0]            # 工时对不上
    assert not make(done, [8.0]).verify(DAY, items)[0]                 # 条数对不上（合并成了一条）
    assert not make(None, []).verify(DAY, items)[0]                    # 系统里压根没有当天日报
    assert not make({"id": "7", "allWorkTime": "0.0", "isLeave": "0"}, []).verify(DAY, items)[0]  # 只有空主表 = 没写进去


def test_relogin_when_token_invalidated():
    """日报系统一个账号只认最近一次登录：token 被别处顶掉（报「token失效」）时，自动重新登录再试一次，而不是让整次提交失败"""
    import json as _json
    import delta_client
    script = []   # 按顺序给出的服务器响应

    class Resp:
        def __init__(self, obj): self.obj = obj
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps(self.obj).encode()
    sent = []

    def fake_urlopen(req, timeout=0):
        sent.append((req.get_method(), req.full_url.split("/daproject")[1], req.headers.get("Token")))
        return Resp(script.pop(0))
    real = delta_client.urlopen
    delta_client.urlopen = fake_urlopen
    try:
        script[:] = [{"code": 0, "token": "T1"}, {"code": 401, "msg": "token失效，请重新登录"},   # 登录 -> 用 T1 请求被拒
                     {"code": 0, "token": "T2"}, {"code": 0, "page": {"list": []}}]              # 重新登录 -> 用 T2 重试成功
        c = Delta("u", "p")
        assert c._call("GET", "/dailymain/list")["page"]["list"] == []
        assert [(m, p) for m, p, _ in sent] == [("POST", "/sys/login"), ("GET", "/dailymain/list"), ("POST", "/sys/login"), ("GET", "/dailymain/list")], sent
        assert sent[1][2] == "T1" and sent[3][2] == "T2" and c.token == "T2"   # 重试带的是新 token
        # 重试一次还是失败：报错，不能无限循环
        sent.clear(); script[:] = [{"code": 401, "msg": "token失效"}, {"code": 0, "token": "T3"}, {"code": 401, "msg": "token失效"}]
        try:
            c._call("GET", "/dailymain/list")
            raise AssertionError("应当报错")
        except DeltaError:
            pass
        assert len(sent) == 3, sent
        # 密码错：登录本身失败不重试
        sent.clear(); script[:] = [{"code": 500, "msg": "账号或密码不正确"}]
        try:
            Delta("u", "bad")
            raise AssertionError("应当报错")
        except DeltaError as e:
            assert "不正确" in str(e) and len(sent) == 1
    finally:
        delta_client.urlopen = real


def test_leave():
    d = fake()
    assert d.submit(DAY, [], {}, leave=True) == "submitted"
    assert d.calls[1][1]["isLeave"] == 1 and "/daily/saveorupdate" not in [p for p, _ in d.calls]


if __name__ == "__main__":
    for t in (test_flatten, test_fresh_submit, test_already_submitted_is_skipped, test_half_done_reuses_main, test_leave_day_counts_as_done, test_last_defaults_from_history, test_my_reports_and_detail, test_verify_readback, test_relogin_when_token_invalidated, test_leave):
        t()
    print("ok")
