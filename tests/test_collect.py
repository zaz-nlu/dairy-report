"""python tests/test_collect.py —— 用假的 ~/.claude、~/.codex 样本断言过滤逻辑"""
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect  # noqa: E402

DAY = date(2026, 10, 13)


def ts(h, m, day=DAY):
    """本地时间 → 日志里的 UTC 'Z' 格式"""
    return datetime(day.year, day.month, day.day, h, m).astimezone().astimezone(timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n{半行", "utf-8")


def make_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_claude(home):
    repo = make_repo(home / "仓库甲")

    def user(h, m, content, **kw):
        return {"type": "user", "timestamp": ts(h, m), "cwd": str(repo), "sessionId": "s1",
                "message": {"role": "user", "content": content}, **kw}

    def assistant(h, m, *blocks):
        return {"type": "assistant", "timestamp": ts(h, m), "message": {"content": list(blocks)}}

    write_jsonl(home / ".claude/projects/D----------/s1.jsonl", [
        {"type": "queue-operation", "timestamp": ts(9, 0)},
        user(9, 1, "<local-command-caveat>Caveat</local-command-caveat>", isMeta=True),
        user(9, 2, "<command-name>/model</command-name>"),
        user(9, 3, [{"type": "text", "text": "<ide_opened_file>x</ide_opened_file>"},
                    {"type": "text", "text": "修复登录页 bug"}]),
        assistant(9, 4, {"type": "text", "text": "我先看看"},
                  {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.ts"}},
                  {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.ts"}},
                  {"type": "tool_use", "name": "Write", "input": {"file_path": str(home / "草稿" / "x.js")}},  # 仓库外
                  {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}),
        user(9, 5, [{"type": "tool_result", "content": "ok"}]),
        assistant(9, 5, {"type": "text", "text": "改好了：登录页密码错误时提示剩余次数"}),
        user(9, 6, [{"type": "text", "text": "[Request interrupted by user]"}]),
        user(9, 7, [{"type": "text", "text": "[Image: source: C:\\x.png]"}], isMeta=True),
        user(9, 8, "\n<pasted_content id=\"1\">\n需求文档内容\n</pasted_content id=\"1\">"),
        assistant(9, 8, {"type": "text", "text": "这个需求是说……"}),  # 只聊没改
        user(9, 9, "子代理的话", isSidechain=True),
        user(9, 10, [{"type": "text", "text": "修复登录页 bug"}]),  # resume 重复
        {**user(9, 0, "昨天的事"), "timestamp": ts(23, 0, date(2026, 10, 12))},
    ])
    got = collect.collect_claude(DAY, home)
    assert [e["text"] for e in got] == ["修复登录页 bug", "需求文档内容"], got
    fix, talk = got
    assert fix["files"] == [str(repo / "a.ts")], fix["files"]  # 仓库外的草稿文件不算改动
    assert fix["project"] == "仓库甲" and fix["time"] == "09:03"
    assert fix["reply"] == "改好了：登录页密码错误时提示剩余次数"  # 一轮里最后一段话 = 结果
    assert talk["files"] == [] and talk["reply"] == "这个需求是说……"


def test_codex(home):
    repo = make_repo(home / "仓库乙")
    base = home / ".codex/sessions"
    msg = lambda h, m, text, day=DAY: {"type": "response_item", "timestamp": ts(h, m, day), "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}
    reply = lambda h, m, text: {"type": "response_item", "timestamp": ts(h, m), "payload": {
        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}}
    # 补丁嵌在 JSON 参数的 JS 代码字符串里，换行是字面 \n
    patch = {"code": f'tools.apply_patch("*** Begin Patch\\n*** Update File: {(repo / "b.ts").as_posix()}\\n@@\\n-x\\n+y\\n'
                     f'*** Add File: {(home / "临时" / "t.py").as_posix()}\\n+1\\n*** End Patch")'}
    meta = {"type": "session_meta", "timestamp": ts(9, 0), "payload": {"cwd": "D:\\不存在\\项目乙", "source": "vscode"}}
    write_jsonl(base / "2026/10/13/rollout-a.jsonl", [
        meta,
        msg(9, 1, "<environment_context>\n<cwd>x</cwd>\n</environment_context>"),
        msg(9, 2, "# AGENTS.md instructions for D:\\x\n..."),
        msg(9, 3, "# Context from my IDE setup:\n\n## Active file: a.ts\n\n## My request for Codex:\n加导出按钮"),
        {"type": "response_item", "timestamp": ts(9, 3), "payload": {
            "type": "function_call", "name": "exec", "arguments": json.dumps(patch)}},
        reply(9, 4, "导出按钮已加上"),
        msg(9, 4, "[12] tool exec call: text(...)"),
        msg(9, 5, "接着改样式"),
        reply(9, 6, "好的"),
    ])
    write_jsonl(base / "2026/10/13/rollout-guardian.jsonl", [
        {"type": "session_meta", "payload": {"cwd": "x", "parent_thread_id": "p", "source": {"subagent": {}}}},
        msg(9, 7, "The following is the Codex agent history"),
    ])
    write_jsonl(base / "2026/10/12/rollout-night.jsonl", [  # 前一晚开、跨过午夜
        meta, msg(23, 50, "昨晚的事", date(2026, 10, 12)), msg(0, 10, "过了午夜继续"),
    ])
    got = sorted(collect.collect_codex(DAY, home), key=lambda e: e["time"])
    assert [e["text"] for e in got] == ["过了午夜继续", "加导出按钮", "接着改样式"], got
    export = got[1]
    assert export["files"] == [str(repo / "b.ts")], export["files"]  # 仓库外的临时脚本不算
    assert export["project"] == "仓库乙" and export["reply"] == "导出按钮已加上"  # cwd 不是仓库，按改动所在仓库归
    assert got[2]["files"] == [] and got[2]["project"] == "项目乙"


def test_git_only_today(tmp):
    """只算当天：昨天写、今天 rebase 的提交不算；上周改完没提交的文件不算"""
    import os
    import time
    repo = make_repo(tmp / "仓库丙")
    git = lambda *a, **env: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True,
                                           env={**os.environ, **env})
    git("config", "user.email", "me@x.com")
    git("config", "user.name", "me")
    (repo / "旧.txt").write_text("1", "utf-8")
    yesterday = (datetime.now() - timedelta(days=1)).replace(hour=10).isoformat(timespec="seconds")
    git("add", "-A")
    git("commit", "-q", "-m", "昨天写的", GIT_AUTHOR_DATE=yesterday)  # 提交时间是现在（像 rebase 过）
    (repo / "新.txt").write_text("1", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "今天写的")
    (repo / "旧.txt").write_text("2", "utf-8")  # 未提交，但把修改时间改回昨天 = 早就改完没交
    old = time.time() - 86400 * 2
    os.utime(repo / "旧.txt", (old, old))
    (repo / "新.txt").write_text("2", "utf-8")  # 未提交，今天改的
    collect.repo_root.cache_clear()
    entries, snaps = collect.collect_git(date.today(), {str(repo)})
    assert [e["text"] for e in entries] == ["今天写的"], entries
    assert snaps and snaps[0]["files"] == ["新.txt"], snaps


def test_svn(tmp):
    """本地临时 SVN 仓库（file://，不碰公司服务器）；工作副本用中文名，防 GBK 乱码"""
    if not collect.SVN or not shutil.which("svnadmin"):
        print("跳过 SVN 测试：没装 svn/svnadmin")
        return
    repo, wc = tmp / "svnrepo", tmp / "工作副本"
    cfg = ["--config-dir", str(tmp / "svncfg")]  # 独立配置目录：别把 tester 写进用户真实的 SVN 登录缓存
    subprocess.run(["svnadmin", "create", str(repo)], check=True)
    subprocess.run(["svn", "checkout", "-q", *cfg, repo.as_uri(), str(wc)], check=True)
    (wc / "登录.ts").write_text("a", "utf-8")
    subprocess.run(["svn", "add", "-q", *cfg, str(wc / "登录.ts")], check=True)
    subprocess.run(["svn", "commit", "-q", *cfg, "--username", "tester", "-m", "修了登录页", str(wc)], check=True)
    (wc / "登录.ts").write_text("b", "utf-8")  # 未提交改动
    (wc / "垃圾.tmp").write_text("x", "utf-8")  # 没纳入版本控制：不算
    collect.repo_root.cache_clear()
    root = collect.repo_root(str(wc))
    assert root == str(wc) and collect.is_svn(root), root
    entries, snaps = collect.collect_svn(date.today(), {root}, users={"tester"})
    assert [e["text"] for e in entries] == ["修了登录页"] and entries[0]["source"] == "svn", entries
    assert entries[0]["project"] == "工作副本" and any("登录.ts" in f for f in entries[0]["files"])
    assert snaps and snaps[0]["files"] == ["登录.ts"], snaps
    others, _ = collect.collect_svn(date.today(), {root}, users={"同事"})
    assert others == []  # 别人的提交不算


def test_clean():
    assert collect.clean("x" * 500) == "x" * collect.TEXT_LIMIT
    assert collect.clean(None) == ""
    assert collect.patch_files(None) == [] and collect.patch_files("*** Update File: a.py\n") == ["a.py"]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_claude(Path(d))
        test_codex(Path(d))
        test_git_only_today(Path(d))
        test_svn(Path(d))
    test_clean()
    print("ok")
