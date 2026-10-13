"""python tests/test_interrogate.py —— 不调 AI，只测规整/校验逻辑"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from interrogate import (build_prompt, collect_evidence, completion, finalize, fit_hours,  # noqa: E402
                         item_weight, merge_points, parse, sample)


def EV(*specs):
    """造证据：每项 (kind, 文件列表, 是否未收尾)，自动编号"""
    return [{"n": i, "line": f"证据{i}", "kind": k, "files": set(f), "partial": p}
            for i, (k, f, p) in enumerate(specs, 1)]


def test_fit_hours():
    for hours in ([3, 3, 3], [7.3, 0.2], [0, 0, 0], [None, 5], [1] * 6, [100, 1, 1]):
        out = fit_hours(hours, 8.0)
        assert sum(out) == 8.0, (hours, out)
        assert all(h >= 0.5 and h * 2 == int(h * 2) for h in out), (hours, out)
    assert fit_hours([6, 2], 8.0) == [6.0, 2.0]


def test_finalize():
    projects = [{"projectId": p, "projectName": p} for p in ("3-12", "3-13", "3-14")]
    ev = EV(("commit", "abcd", False), ("chat", "ab", False), ("chat", "x", True), ("uncommitted", "y", False), ("note", "", False))
    items = [
        {"workInfo": " 1.改了A ", "projectId": "3-12", "confidence": 0.9, "evidence": [1, 2]},
        {"workInfo": "1.改了B", "projectId": "99", "confidence": 0.9, "evidence": [3]},
        {"workInfo": "1.改了C", "projectId": "3-14", "confidence": 0.3, "evidence": [4, 5]},
    ]
    a, b, c = finalize(items, projects, 8.0, "3-13", ev)
    # A：依据 1、2 的文件并集 {a,b,c,d}=4 个 → √4 + 0.5×2 = 3；有提交且没说待验证 → 100%
    assert a == {"workInfo": "1.改了A", "projectId": "3-12", "workTime": 3.5, "completionDegree": 100, "doubt": False,
                 "basis": ["证据1", "证据2"]}, a
    # B：不存在的项目 → 默认项目 + 存疑；依据只有一轮没提交的对话，且说"待验证" → 50%
    assert b["projectId"] == "3-13" and b["doubt"] and b["completionDegree"] == 50 and b["workTime"] == 1.5, b
    # C：低置信度 → 存疑；没提交 → 70%；工时按权重 √1+0.5×2+手记 1 = 3
    assert c["doubt"] and c["completionDegree"] == 70 and c["workTime"] == 3.0, c
    assert a["workTime"] + b["workTime"] + c["workTime"] == 8.0  # 总工时不变


def test_merge_same_project():
    assert merge_points(["1.改A 2.改B", "1.加C，提速 2.5 倍"]) == "1.改A\n2.改B\n3.加C，提速 2.5 倍"
    projects = [{"projectId": "7-1", "projectName": "甲"}, {"projectId": "7-2", "projectName": "乙"}]
    ev = EV(("chat", "a", False), ("chat", "b", False), ("note", "", False))
    items = [{"workInfo": "1.a", "projectId": "7-1", "confidence": 0.9, "evidence": [1]},
             {"workInfo": "1.b", "projectId": "7-2", "confidence": 0.9, "evidence": [3]},
             {"workInfo": "1.c 2.d", "projectId": "7-1", "confidence": 0.4, "evidence": [2, 1]}]
    got = finalize(items, projects, 8.0, "7-2", ev)
    assert [g["projectId"] for g in got] == ["7-1", "7-2"], got   # 同项目合成一条，依据取并集
    assert got[0]["workInfo"] == "1.a\n2.c\n3.d" and got[0]["doubt"] and got[0]["basis"] == ["证据1", "证据2"]
    assert got[1]["completionDegree"] == 100  # 只有手记 = 用户亲口说做完了
    assert sum(g["workTime"] for g in got) == 8.0 and got[0]["workTime"] > got[1]["workTime"]


def test_weights_and_completion():
    """工时、完成度由证据算：同一批文件的提交和对话不重复计算；说"待验证"的不算完成"""
    # 提交和产生它的那轮对话改的是同一批文件 → 并集 4 个，不是 8 个
    assert item_weight(EV(("commit", "abcd", False), ("chat", "abcd", False)), [1, 2]) == 3.0
    # 改 100 个文件只比改 4 个多一点，不会按文件数线性放大
    assert item_weight(EV(("chat", [f"f{i}" for i in range(100)], False)), [1]) == 10.5
    assert item_weight(EV(("note", "", False)), [1]) == 2.0  # 手记：max(1, 0+0.5)=1，再加手记自身 1
    assert completion(EV(("commit", "a", False)), [1]) == 100
    assert completion(EV(("commit", "a", True)), [1]) == 80   # 有提交，但说没测完
    assert completion(EV(("chat", "a", False)), [1]) == 70    # 改了没提交
    assert completion(EV(("chat", "a", True)), [1]) == 50
    assert completion(EV(("note", "", False)), [1]) == 100
    assert completion(EV(("note", "", False), ("chat", "a", True)), [1, 2]) == 50  # 混了未收尾的就不是纯手记
    # collect_evidence：编号、类型、未收尾检测
    raw = {"date": "2026-10-13", "snapshots": [{"time": "12:00", "project": "dify", "files": ["u.ts"]}], "entries": [
        {"time": "09:00", "source": "git", "project": "dify", "text": "WIP: 登录页", "files": ["a.ts"], "reply": ""},
        {"time": "10:00", "source": "claude", "project": "dify", "text": "做导出", "files": ["b.ts"],
         "reply": "导出做好了，前端测试待验证"},
        {"time": "11:00", "source": "claude", "project": "dify", "text": "改样式", "files": ["c.ts"], "reply": "改好了"}]}
    ev = collect_evidence(raw, [{"time": "15:00", "text": "开了评审会"}], [])
    assert [(x["n"], x["kind"], x["partial"]) for x in ev] == [
        (1, "commit", True), (2, "chat", True), (3, "chat", False), (4, "uncommitted", False), (5, "note", False)], ev


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
    # 那天有手写日报但不知道写了啥：不锁，默认不勾，勾了就算
    mb = annotate("2026-10-13", {"2026-10-12": {"entries": mon[:2]}}, {}, {}, {uid("2026-10-12", mon[1]): True}, {},
                  {uid("2026-10-12", mon[0]): "2026-10-12", uid("2026-10-12", mon[1]): "2026-10-12"})
    assert [(e["why"], e["included"]) for e in mb] == [("maybe:2026-10-12", False), ("picked", True)], mb
    # 同一天的日报重新生成时，自己之前用过的条目不算"报过"
    again = annotate("2026-10-12", {"2026-10-12": {"entries": mon[:1]}}, {}, {}, {},
                     {uid("2026-10-12", mon[0]): "2026-10-12"})
    assert again[0]["included"] and again[0]["why"] == "work"
    # 前几天的条目进提示词时带日期，今天的不带
    p = build_prompt({"date": "2026-10-13", "entries": [e for e in got if e["included"]], "snapshots": []}, [], [], 8.0)
    assert "10-12 10:00 [claude] dify: 需求「页面2」" in p and "】09:00 [claude] dify: 需求「页面3」" in p


def test_find_ai_tools():
    """每个人装的位置都不一样：模拟几种常见布局，确认都能找到；只装了编辑器插件的同事也行"""
    import os
    import tempfile
    import interrogate as I
    touch = lambda p: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text("x"))
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "同事"
        env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PATH")}
        os.environ.update(USERPROFILE=str(home), HOME=str(home), LOCALAPPDATA=str(home / "Local"),
                          APPDATA=str(home / "Roaming"), PATH="")
        real_fresh_path = I._fresh_path
        I._fresh_path = lambda: ""  # 隔离：不读本机真实注册表里的 PATH，免得找到开发者自己装的
        try:
            I._providers_cache.clear()
            assert I.providers() == []  # 什么都没装：空，由上层给出"去设置里填路径"的提示
            # 1) 只装了 VS Code 插件（没有命令行）——很多同事就是这样
            claude_ext = home / ".vscode/extensions/anthropic.claude-code-2.1.0-win32-x64/resources/native-binary/claude.exe"
            touch(claude_ext)
            I._providers_cache.clear()
            assert I.providers() == [("claude", str(claude_ext))], I.providers()
            # 2) 官方安装器的命令行排在插件前面；codex 桌面版排在 npm 老版前面
            native = home / ".local/bin/claude.exe"
            codex_desktop = home / "Local/OpenAI/Codex/bin/abc123/codex.exe"
            codex_npm = home / "Roaming/npm/codex.cmd"
            for p in (native, codex_desktop, codex_npm):
                touch(p)
            I._providers_cache.clear()
            got = I.providers()
            assert got == [("claude", str(native)), ("codex", str(codex_desktop)), ("codex", str(codex_npm))], got
            # 3) 用户手填的路径最优先；文件名含 codex 的按 codex 调，其余按 claude 调；填错的路径忽略
            wrapper = home / "公司工具" / "claude-ds.cmd"  # 先设内网大模型的环境变量再启动 claude 的脚本
            touch(wrapper)
            I._providers_cache.clear()
            got = I.providers([str(wrapper), str(home / "不存在.exe"), ""])
            assert got[0] == ("claude", str(wrapper)) and ("claude", str(native)) in got, got
            assert len([g for g in got if g[0] == "claude"]) == 2  # 手填的 + 自动找到的第一份（不是全部）
        finally:
            for k, v in env.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            I._fresh_path = real_fresh_path  # 还原，别影响后面的测试
            I._providers_cache.clear()


def test_parse():
    good = '好的：\n```json\n{"items":[{"workInfo":"1.x","projectId":null,"confidence":1,"evidence":[2,1,9,"a",2]}]}\n```'
    assert parse(good)[0]["workInfo"] == "1.x"  # 不传 n：不校验依据
    assert parse(good, n=3)[0]["evidence"] == [1, 2]  # 去重、排序、丢掉不存在的编号（9）和非整数
    for bad in ("没有json", '{"items":[]}', '{"items":[{"workInfo":"","evidence":[1]}]}',
                '{"items":[{"workInfo":"1.x","confidence":"很多","evidence":[1]}]}'):
        try:
            parse(bad, n=3)
        except (ValueError, KeyError):
            continue
        raise AssertionError(f"应当拒绝: {bad}")
    # 凭空写的：没有依据 / 依据全是不存在的编号 / 格式不对 → 一律判不合格（会让 AI 重来）
    for evidence in ("缺失", "[]", "[9]", '"1"', "[0, -1]"):
        item = '{"workInfo":"1.凭空写的","projectId":null,"confidence":1' + ("" if evidence == "缺失" else f',"evidence":{evidence}') + "}"
        try:
            parse('{"items":[' + item + "]}", n=3)
        except ValueError as e:
            assert "没有有效依据" in str(e), e
            continue
        raise AssertionError(f"没依据的条目应当拒绝: {evidence}")


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
    assert "不存在的id" not in p and "用户已指定归属" not in build_prompt(raw, [], projs, 8.0, hist, {"x": "7-296"}).split("今日证据（【编号】")[1]
    p = build_prompt(raw, [{"time": "15:00", "text": "开需求评审会"}], [], 8.0, hist)
    assert "【1】09:00 [git]" in p and "【2】15:00 [用户手记]" in p  # 证据带编号，AI 靠编号说明依据


if __name__ == "__main__":
    test_fit_hours()
    test_finalize()
    test_merge_same_project()
    test_weights_and_completion()
    test_find_ai_tools()
    test_skip_private_repo()
    test_annotate_backlog()
    test_parse()
    test_prompt()
    print("ok")
