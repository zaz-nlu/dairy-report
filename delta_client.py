"""德尔塔日报系统客户端（renren-fast 后端，接口从前端 JS 反查，见 PLAN.md）

只读自检：DELTA_USER=xx DELTA_PASS=yy python delta_client.py
试提交：  DELTA_USER=xx DELTA_PASS=yy python delta_client.py submit 2026-10-13   （读当天 draft.json，人在场时用）
"""
import json
import os
import re
import sys
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://221.238.56.226:8866/daproject"
WEB = "http://221.238.56.226:8866/dailyweb/"


class DeltaError(Exception):
    pass


def _num(v):
    """前端下拉值是 "groupId-id"，提交时只要 id"""
    return int(str(v).split("-")[-1])


def _flatten(groups, name_key):
    """接口按部门分组返回 [{groupName, groupId, list:[…]}]，展平成一维；多个部门时名称前加部门名区分"""
    multi = len(groups) > 1
    return [{**row, name_key: f"{g['groupName']} / {row[name_key]}" if multi else row[name_key]}
            for g in groups for row in g.get("list") or []]


def _li(html):
    """日报列表里的 <li>…</li> 拆成文本列表；去掉末尾「( 工时: 8.0 h 完成: 100 % )」"""
    html = re.sub(r"\(\s*(?:<span.*?</span>\s*)+\)", "", html or "")
    return [t.strip() for t in re.sub(r"<[^>]+>", "", html.replace("</li>", "␞")).split("␞") if t.strip()]


class Delta:
    def __init__(self, username, password, base=BASE):
        self.base, self.token, self._cred = base, None, (username, password)
        self._login()

    def _login(self):
        username, password = self._cred
        r = self._call("POST", "/sys/login", {"username": username, "password": password,
                                              "uuid": str(uuid.uuid4()), "captcha": "111"})  # 验证码不校验
        self.token = r["token"]

    def _call(self, method, path, body=None, params=None, _retry=True):
        url = self.base + path + ("?" + urlencode(params) if params else "")
        req = Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json;charset=UTF-8", "token": self.token or ""})
        try:
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except OSError as e:
            raise DeltaError(f"连不上日报系统：{e}") from e
        if data.get("code") != 0:
            msg = data.get("msg") or ""
            # 日报系统一个账号同一时间只认最近一次登录：别处（网页、另一个请求）登录过，这边的 token 就作废。
            # 作废了就重新登录再试一次，不然 18:00 提交到一半被踢掉就白费了
            if _retry and path != "/sys/login" and getattr(self, "_cred", None) and (data.get("code") == 401 or "token" in msg and "失效" in msg):
                self._login()
                return self._call(method, path, body, params, _retry=False)
            raise DeltaError(f"{path}: {msg or data}")
        return data

    def projects(self):
        """[{projectId:"7-275", projectName}]（id 形如 部门id-项目id，和网页下拉值一致）"""
        return _flatten(self._call("GET", "/projtask/selfProject")["data"], "projectName")

    def task_types(self):
        return _flatten(self._call("GET", "/projtasktype/selfProjectType")["data"], "projectTypeName")

    def report_users(self):
        return self._call("GET", "/sys/user/reportUser")["data"]  # [{id, label}]

    def find_main(self, day):
        """本人当天的日报主表行，没有返回 None"""
        d = day.isoformat()
        rows = self._call("GET", "/dailymain/list", params={"page": 1, "limit": 10, "isself": 1,
                                                            "start": d, "end": d})["page"]["list"]
        return next((r for r in rows if str(r.get("dateTime", "")).startswith(d)), None)

    def recent_reports(self, days=14, limit=8):
        """本人最近交过的日报 [{date, items:[{project, text}]}]，新→旧；给 AI 当"这个人平时把什么活归到哪个项目"的参考"""
        today = date.today()
        rows = self._call("GET", "/dailymain/list", params={
            "page": 1, "limit": 40, "isself": 1, "start": (today - timedelta(days=days)).isoformat(),
            "end": (today - timedelta(days=1)).isoformat()})["page"]["list"]
        out = []
        for m in sorted(rows, key=lambda r: str(r.get("dateTime")), reverse=True):
            if float(m.get("allWorkTime") or 0) <= 0:
                continue
            names, texts = _li(m.get("isHaveProject")), _li(m.get("workInfo"))
            if len(names) != len(texts):  # 对不上就整体当一条，不瞎配对
                names, texts = ["、".join(names)], ["\n".join(texts)]
            out.append({"date": str(m["dateTime"])[:10],
                        "items": [{"project": n, "text": t} for n, t in zip(names, texts)]})
            if len(out) >= limit:
                break
        return out

    def my_reports(self, days=400):
        """本人在日报系统里最近 days 天的每一天，新→旧：[{date, id, hours, leave, holiday, missed, projects:[项目名]}]。
        系统给每天都建一行：漏交的日子次日凌晨 1 点自动补一条 0 工时、备注「系统自动补全」的空日报，节假日 / 周末
        系统自己标 isHolidays=1。所以：有工时或请假 = 交了；0 工时且不是节假日也没请假 = 漏交（罚款就是这么来的）。
        档案室、连续天数、罚款账本都以它为准。一页 100 条，翻页取完（400 天约 4 页）"""
        today, rows, page = date.today(), [], 1
        while True:
            r = self._call("GET", "/dailymain/list", params={
                "page": page, "limit": 100, "isself": 1, "start": (today - timedelta(days=days)).isoformat(),
                "end": today.isoformat()})["page"]
            rows += r["list"]
            if not r["list"] or len(rows) >= int(r.get("totalCount") or 0) or page >= 10:
                break
            page += 1
        out = []
        for m in sorted(rows, key=lambda r: str(r.get("dateTime")), reverse=True):
            hours, leave, holiday = float(m.get("allWorkTime") or 0), str(m.get("isLeave")) == "1", str(m.get("isHolidays")) == "1"
            out.append({"date": str(m["dateTime"])[:10], "id": int(m["id"]), "hours": hours, "leave": leave, "holiday": holiday,
                        "missed": hours <= 0 and not leave and not holiday, "projects": _li(m.get("isHaveProject"))})
        return out

    def report_detail(self, main_id):
        """某一天日报的完整内容：{remark, items:[{projectId, workInfo, workTime, completionDegree}]}，projectId 形如 7-296"""
        r = self._call("GET", f"/dailymain/info/{main_id}")
        return {"remark": (r.get("dailyMain") or {}).get("remark") or "",
                "items": [{"projectId": f"{d.get('groupId')}-{d.get('isProjTaskId')}", "workInfo": d.get("workInfo") or "",
                           "workTime": float(d.get("workTime") or 0), "completionDegree": int(float(d.get("completionDegree") or 0))}
                          for d in r.get("daily") or []]}

    def verify(self, day, items):
        """提交后回读核对（只读）：系统里当天的日报，条数和总工时是否和刚提交的一致。返回 (是否一致, 说明)。
        只比条数和工时，不比文字——服务器可能改写换行 / 转义，比文字会误报"""
        main = self.find_main(day)
        if not self._done(main):
            return False, "回读时系统里没看到当天的日报"
        rows = self.report_detail(int(main["id"]))["items"]
        want = round(sum(float(i["workTime"]) for i in items), 1)
        got = round(sum(r["workTime"] for r in rows), 1)
        if len(rows) != len(items) or abs(want - got) > 0.05:
            return False, f"系统里现有 {len(rows)} 条、{got} 小时，和提交的 {len(items)} 条、{want} 小时不一致"
        return True, f"系统里现有 {len(rows)} 条、共 {got} 小时，和提交的一致"

    def last_defaults(self):
        """从本人最近一份有工时的日报，读出上次选的 项目/任务类型/汇报人/优先级 —— 用户不用手填默认值。
        没有历史日报（新同事）返回 {}，由设置页手选。"""
        today = date.today()
        rows = self._call("GET", "/dailymain/list", params={
            "page": 1, "limit": 40, "isself": 1, "start": (today - timedelta(days=45)).isoformat(),
            "end": today.isoformat()})["page"]["list"]
        for m in sorted(rows, key=lambda r: str(r.get("dateTime")), reverse=True):
            if float(m.get("allWorkTime") or 0) <= 0:
                continue  # 系统自动补的空日报、请假日
            rows = self._call("GET", f"/dailymain/info/{m['id']}").get("daily") or []
            if rows:
                d, g = rows[0], rows[0].get("groupId")
                return {"default_project": f"{g}-{d['isProjTaskId']}", "task_type": f"{g}-{d['isProjTaskTypeId']}",
                        "report_user": d["sendUserId"], "priority": int(d.get("priority") or 2)}
        return {}

    @staticmethod
    def _done(main):
        """主表存在且有工时（或请假）才算交过；只有空主表 = 上次半成功"""
        return bool(main) and (float(main.get("allWorkTime") or 0) > 0 or str(main.get("isLeave")) == "1")  # 接口里全是字符串

    def submitted(self, day):
        return self._done(self.find_main(day))

    def submit(self, day, items, defaults, leave=False):
        """两步提交：①主表 ②明细。主表已存在但明细没进去（上次半成功）时复用主表，不新建。

        items: draft 条目 [{workInfo, projectId, workTime, completionDegree}]
        defaults: {taskTypeId, reportUserId, priority}
        返回 "submitted" / "exists"
        """
        main = self.find_main(day)
        if self._done(main):
            return "exists"
        head = {"dateTime": day.isoformat(), "remark": "", "isLeave": 1 if leave else 0}
        r = self._call("POST", "/dailymain/update", {"id": int(main["id"]), **head}) if main else \
            self._call("POST", "/dailymain/save", head)
        if leave:
            return "submitted"
        main_id, group_id = int(r.get("data") or main["id"]), r.get("groupId")
        rows = [{"mainId": main_id, "groupId": group_id,
                 "isProjTaskId": _num(it["projectId"]),
                 "isProjTaskTypeId": _num(defaults["taskTypeId"]),
                 "sendUserId": _num(defaults["reportUserId"]),  # 设置页下拉存的是字符串
                 "priority": defaults.get("priority", 2),
                 "workInfo": it["workInfo"],
                 "completionDegree": it["completionDegree"],
                 "workTime": it["workTime"],
                 "haveQuestion": "", "solution": "", "remark": ""} for it in items]
        self._call("POST", "/daily/saveorupdate", {"mainId": main_id, "list": rows})
        return "submitted"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from collect import default_data_dir

    c = Delta(os.environ["DELTA_USER"], os.environ["DELTA_PASS"])
    print("登录成功")
    projs = c.projects()
    (default_data_dir() / "projects.json").write_text(json.dumps(projs, ensure_ascii=False, indent=1), "utf-8")
    print("项目:", json.dumps(projs, ensure_ascii=False)[:1500])
    print("任务类型:", json.dumps(c.task_types(), ensure_ascii=False)[:800])
    print("汇报人:", json.dumps(c.report_users(), ensure_ascii=False)[:800])
    today = date.today()
    print("今天的主表:", json.dumps(c.find_main(today), ensure_ascii=False))
    if len(sys.argv) > 2 and sys.argv[1] == "submit":
        d = date.fromisoformat(sys.argv[2])
        draft = json.loads((default_data_dir() / d.isoformat() / "draft.json").read_text("utf-8"))
        defaults = json.loads(os.environ["DELTA_DEFAULTS"])  # '{"taskTypeId":"3-5","reportUserId":7,"priority":2}'
        print(c.submit(d, draft["items"], defaults))
