"""搜身：采集某天的 git / SVN / Claude Code / Codex 工作痕迹 → <数据目录>/YYYY-MM-DD/raw.json

用法：python collect.py [YYYY-MM-DD]（默认今天）
统一条目：{source, time(本地 HH:MM), project, cwd, text, files[], reply}
"""
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

TEXT_LIMIT = 300
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 打包成窗口程序后调 git 不弹黑框
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Codex 会话压缩后回灌的转录行，如 "[12] tool exec call: ..."
TRANSCRIPT_LINE = re.compile(r"^\[\d+\] ")
MY_REQUEST = re.compile(r"^## My request[^\n]*:\n", re.M)
PASTED_TAG = re.compile(r"</?pasted_content[^>]*>")


def default_data_dir():
    return Path("D:/工作") if Path("D:/").exists() else Path.home() / "daily-prison"


def local_dt(ts):
    """'2026-10-13T01:36:06.193Z' → 本地时区 aware datetime"""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


def clean(text):
    """去掉工具包装，返回人话；纯包装/系统注入返回 ''"""
    text = PASTED_TAG.sub("", text or "").strip()
    if MY_REQUEST.search(text):  # Codex IDE/附件上下文：只要 "## My request" 之后的部分
        text = MY_REQUEST.split(text)[-1].strip()
    if (not text or text[0] == "<" or text.startswith(("# AGENTS.md", "[Request interrupted", "[Image"))
            or TRANSCRIPT_LINE.match(text)):
        return ""
    return text[:TEXT_LIMIT]


SVN = shutil.which("svn")


def run(args, cwd=None, timeout=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""  # SVN 服务器连不上时别卡住整个采集
    return r.stdout if r.returncode == 0 else ""


def _xml(text):
    try:
        return ET.fromstring(text) if text.strip() else None
    except ET.ParseError:
        return None


@lru_cache(maxsize=None)
def repo_root(cwd):
    """cwd 所属仓库根目录（git 优先，其次 SVN 工作副本）；都不是或目录已不存在返回 None"""
    if not cwd or not Path(cwd).is_dir():
        return None
    out = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd).strip()
    if out:
        return str(Path(out))
    if SVN:  # svn info 只读本地 .svn，不连服务器；用 --xml 因为普通输出是 GBK，中文路径会乱码
        root = _xml(run([SVN, "info", "--xml", cwd]))
        wc = root is not None and root.findtext(".//wcroot-abspath")
        if wc:
            return str(Path(wc))
    return None


def is_svn(root):
    return not (Path(root) / ".git").exists()


def project_of(cwd):
    root = repo_root(cwd)
    return Path(root or cwd or "").name or "未知"


def _in_day(dt, day):
    return dt.date() == day


def _jsonl(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue  # 正在写入的半行


def collect_claude(day, home=None):
    home = Path(home or Path.home())
    since = datetime.combine(day, datetime.min.time()).timestamp()
    entries, seen = [], set()
    for path in (home / ".claude" / "projects").glob("*/*.jsonl"):
        if path.stat().st_mtime < since:  # 当天没动过的会话不读
            continue
        last = None
        for o in _jsonl(path):
            if o.get("isSidechain") or "timestamp" not in o:
                continue
            content = (o.get("message") or {}).get("content")
            if o.get("type") == "assistant" and last is not None and isinstance(content, list):
                for b in content:
                    inp = b.get("input") or {}
                    f = b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS and (
                        inp.get("file_path") or inp.get("notebook_path"))
                    if f and f not in last["files"]:
                        last["files"].append(f)
                    if b.get("type") == "text" and b.get("text", "").strip():
                        last["reply"] = b["text"].strip()[:TEXT_LIMIT]  # 一轮里最后一段话 = AI 干完活的总结
                continue
            if o.get("type") != "user" or o.get("isMeta"):
                continue
            dt = local_dt(o["timestamp"])
            if not _in_day(dt, day):
                continue
            blocks = [content] if isinstance(content, str) else [
                b.get("text", "") for b in content or [] if b.get("type") == "text"]
            text = "\n".join(t for t in map(clean, blocks) if t)
            if not text or (o.get("sessionId"), text) in seen:
                continue  # tool_result / 纯包装 / resume 带来的重复
            seen.add((o.get("sessionId"), text))
            cwd = o.get("cwd", "")  # 目录名对中文有损，必须用行内 cwd
            last = {"source": "claude", "time": dt.strftime("%H:%M"), "project": project_of(cwd),
                    "cwd": cwd, "text": text, "files": [], "reply": ""}
            entries.append(last)
    return [keep_repo_files(e) for e in entries]


def collect_codex(day, home=None):
    home = Path(home or Path.home())
    entries = []
    for d in (day - timedelta(days=1), day):  # 前一晚开的会话会写进前一天目录
        folder = home / ".codex" / "sessions" / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"
        for path in folder.glob("rollout-*.jsonl"):
            cwd, last = "", None
            for o in _jsonl(path):
                p = o.get("payload") or {}
                kind = o.get("type") == "response_item" and p.get("type")
                if o.get("type") == "session_meta":
                    if p.get("parent_thread_id") or isinstance(p.get("source"), dict):
                        break  # guardian 审批 / 子代理会话：prompt 是 AI 写的，不是人
                    cwd = p.get("cwd", "")
                elif kind in ("function_call", "custom_tool_call") and last is not None:
                    for f in patch_files(p.get("input") or p.get("arguments")):
                        if f not in last["files"]:
                            last["files"].append(f)
                elif kind == "message" and p.get("role") == "assistant" and last is not None:
                    reply = "".join(b.get("text", "") for b in p.get("content") or []).strip()
                    if reply:
                        last["reply"] = reply[:TEXT_LIMIT]
                elif kind == "message" and p.get("role") == "user" and "timestamp" in o:
                    dt = local_dt(o["timestamp"])
                    text = "\n".join(t for t in (clean(b.get("text")) for b in p.get("content") or []
                                                 if b.get("type") == "input_text") if t)
                    if not text:
                        continue  # 纯包装：不开新一轮，后面的改动仍算上一轮的
                    last = {"source": "codex", "time": dt.strftime("%H:%M"), "project": project_of(cwd),
                            "cwd": cwd, "text": text, "files": [], "reply": ""}
                    if _in_day(dt, day):
                        entries.append(last)
    return [keep_repo_files(e) for e in entries]


PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$", re.M)


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def patch_files(body):
    """Codex 改文件留下的 apply_patch 文本里抠出路径。补丁可能嵌在 JSON 参数或 JS 字符串里，
    所以先拆 JSON、再把字面 \\n 当换行。ponytail: 含字面 \\n 的 Windows 路径（如 D:\\new）会被拆坏，罕见，先不管"""
    if not body:
        return []
    try:
        text = "\n".join(_strings(json.loads(body)))
    except (ValueError, TypeError):
        text = str(body)
    return PATCH_FILE.findall(text.replace("\\n", "\n"))


def keep_repo_files(e):
    """只保留落在 git 仓库里的改动文件——临时脚本、AI 自己的草稿、清理 C 盘的工具脚本都不算工作。
    有改动时，项目名以改动所在仓库为准（在家目录开的会话改了 D:\\dify 也能归对）"""
    base, files, roots = Path(e["cwd"] or "."), [], []
    for f in e["files"]:
        p = Path(f) if Path(f).is_absolute() else base / f
        root = repo_root(str(p.parent))
        if root:
            files.append(str(p))
            roots.append(root)
    e["files"] = files
    if roots:
        e["project"] = Path(roots[0]).name
    return e


def collect_git(day, repos):
    """返回 (entries, snapshots)；只收本人（该仓库 user.email）的提交。snapshot 只在采今天时有意义"""
    entries, snapshots = [], []
    start = datetime.combine(day, datetime.min.time()).astimezone()
    end = start + timedelta(days=1)
    for repo in sorted(repos):
        email = run(["git", "config", "user.email"], cwd=repo).strip()
        if not email:
            continue  # 不知道谁是"本人"，宁可不采也不把同事的提交算进来
        log = run(["git", "-c", "core.quotepath=false", "log", "--all", "--no-merges", "--name-only",
                   f"--since={start.isoformat()}", f"--until={end.isoformat()}", f"--author={email}",
                   "--date=iso-strict", "--format=%x1e%ad%x1f%s"], cwd=repo)
        for rec in log.split("\x1e")[1:]:
            head, _, files = rec.partition("\n")
            ad, _, subject = head.partition("\x1f")
            written = datetime.fromisoformat(ad).astimezone()
            if not _in_day(written, day):
                continue  # --since 按提交时间筛；昨天写的今天 rebase/amend/cherry-pick 过的，按写代码的时间算回昨天
            entries.append({"source": "git", "time": written.strftime("%H:%M"),
                            "project": Path(repo).name, "cwd": repo, "text": subject[:TEXT_LIMIT],
                            "files": [f for f in files.splitlines() if f]})
        if day == date.today():
            status = run(["git", "-c", "core.quotepath=false", "status", "--porcelain"], cwd=repo)
            files = touched_today(repo, [l[3:].split(" -> ")[-1].strip('"') for l in status.splitlines()], day)
            if files:
                snapshots.append({"time": datetime.now().strftime("%H:%M"), "project": Path(repo).name,
                                  "cwd": repo, "files": files})
    return entries, snapshots


def touched_today(repo, files, day):
    """未提交改动里只留当天动过的文件——上周改完一直没提交的，不算今天的活。
    ponytail: 按文件修改时间判断；当天删除的文件没有修改时间，算不进来"""
    out = []
    for f in files:
        try:
            if datetime.fromtimestamp((Path(repo) / f).stat().st_mtime).date() == day:
                out.append(f)
        except OSError:
            pass
    return out


def svn_users():
    """本机 SVN 登录缓存里的用户名 = "本人"。没缓存过（从没登录）返回空，宁可不采也不算同事的提交"""
    return {line.split(":", 1)[1].strip() for line in run([SVN, "auth"]).splitlines()
            if line.startswith("Username:")} if SVN else set()


def collect_svn(day, repos, users=None):
    """返回 (entries, snapshots)，结构同 collect_git。svn log 要连服务器，超时 30 秒就跳过该仓库"""
    entries, snapshots = [], []
    if not SVN:
        return entries, snapshots
    users = svn_users() if users is None else users
    for repo in sorted(repos):
        # -r {日期} 取的是"该时刻之前最后一个版本"，会多带出前一天的提交，下面按时间再过滤
        log = _xml(run([SVN, "log", "--xml", "-v", "-r", f"{{{day}}}:{{{day + timedelta(days=1)}}}", repo], timeout=30))
        for e in (log.iter("logentry") if log is not None else []):
            dt = local_dt(e.findtext("date") or "1970-01-01T00:00:00Z")
            if (e.findtext("author") or "") in users and _in_day(dt, day):
                entries.append({"source": "svn", "time": dt.strftime("%H:%M"), "project": Path(repo).name,
                                "cwd": repo, "text": (e.findtext("msg") or "").strip()[:TEXT_LIMIT],
                                "files": [p.text for p in e.iter("path") if p.text], "reply": ""})
        if day == date.today():  # 未提交改动；--xml 保证中文路径不乱码，只看已纳入版本控制的（忽略 ? 未加入的文件）
            st = _xml(run([SVN, "status", "--xml", "-q", repo], timeout=30))
            files = [str(Path(x.get("path")).relative_to(repo)) if Path(x.get("path")).is_absolute() else x.get("path")
                     for x in (st.iter("entry") if st is not None else [])
                     if x.find("wc-status") is not None  # --xml 下 -q 不管用，自己滤掉未纳入版本控制的
                     and x.find("wc-status").get("item") not in ("unversioned", "ignored", "external", "normal", "none")]
            files = touched_today(repo, files, day)
            if files:
                snapshots.append({"time": datetime.now().strftime("%H:%M"), "project": Path(repo).name,
                                  "cwd": repo, "files": files})
    return entries, snapshots


def collect(day, sources=("git", "claude", "codex"), extra_repos=(), data_dir=None, home=None):
    """重采当天全量（幂等）写 raw.json；git status 快照追加保留（未提交的工作之后 git log 查不到）"""
    entries = []
    if "claude" in sources:
        entries += collect_claude(day, home)
    if "codex" in sources:
        entries += collect_codex(day, home)
    out = Path(data_dir or default_data_dir()) / day.isoformat() / "raw.json"
    old = json.loads(out.read_text("utf-8")) if out.exists() else {}
    snapshots = old.get("snapshots", [])
    if "git" in sources:  # "git" 代表版本控制，git 和 SVN 都在这里
        repos = {r for r in map(repo_root, [e["cwd"] for e in entries] + list(extra_repos)) if r}
        git_entries, new_snaps = collect_git(day, {r for r in repos if not is_svn(r)})
        svn_entries, svn_snaps = collect_svn(day, {r for r in repos if is_svn(r)})
        entries += git_entries + svn_entries
        new_snaps += svn_snaps
        for s in new_snaps:  # 同一仓库状态没变就不重复记
            if not any(o["cwd"] == s["cwd"] and o["files"] == s["files"] for o in snapshots):
                snapshots.append(s)
    entries.sort(key=lambda e: e["time"])
    raw = {"date": day.isoformat(), "collected_at": datetime.now().isoformat(timespec="seconds"),
           "entries": entries, "snapshots": snapshots}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=1), "utf-8")
    return raw


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    raw = collect(d)
    for e in raw["entries"]:
        print(f'{e["time"]} [{e["source"]:6}] {e["project"]}: {e["text"][:80]!r} {len(e["files"])} files')
    print(f'{len(raw["entries"])} 条, {len(raw["snapshots"])} 个未提交快照 → {default_data_dir() / d.isoformat()}')
