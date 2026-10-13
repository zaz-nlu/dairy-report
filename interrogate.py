"""审讯：raw.json(+notes.json) → AI 整理 → draft.json

用法：python interrogate.py [YYYY-MM-DD]（默认今天，需先 collect）
AI 自动选：有 claude 用 `claude -p`，否则 `codex exec`；都沿用本机已配好的后端。
草稿条目：{workInfo, projectId, workTime, completionDegree, doubt, basis}，按项目一条。

分工：AI 只负责「归项目 + 写文字 + 说明每条依据哪几条证据」；工时和完成度由代码按证据体量、状态计算
（可审计、可复现，也让小模型够用）。没有有效依据的条目直接判不合格，不会进日报。
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from collect import NO_WINDOW, default_data_dir

TIMEOUT = 180
MAX_ENTRIES = 200  # 证据条数上限，超出按时间均匀抽样，控制 token
MAX_ITEMS = 6
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["workInfo", "projectId", "confidence", "evidence"],
        "properties": {"workInfo": {"type": "string"}, "projectId": {"type": ["string", "null"]},
                       "confidence": {"type": "number"},
                       "evidence": {"type": "array", "items": {"type": "integer"}}}}}}}

PROMPT = """你是日报整理员。根据下面的「今日证据」替用户写今天的工作日报。

规则：
1. 证据只有「真正产出了改动」的工作：AI 助手改了代码的对话轮次、git 提交、未提交改动、用户手记。
   对话轮次里「需求」是用户原话，口语化、零碎，只帮你理解背景；「结果」是 AI 干完活后的总结，和改动文件一起才是主要依据。
   只依据证据，不编造、不夸大；结果里说"没做完/没跑/待验证"的照实写进度，不要写成已完成。与工作无关的一律忽略。
   时间前带日期（如「10-12 14:50」）的，是前几天做完、还没报过、用户决定放进这份日报的工作，照常写，不要提日期。
2. 按项目归类，每个项目一条；同一件事在对话和 git 里都出现只写一次。最多 {max_items} 条。
3. workInfo：中文编号短句，如「1.修复了知识库上传进度不显示的问题 2.新增导出按钮」。写做成了什么，不写对话过程和口吻。
4. projectId：从「可选项目」里选最匹配的 id（原样照抄字符串）。「最近日报」是用户自己的归类习惯：同类工作（相同的产品、模块、仓库、需求）沿用历史里的项目，
   除非今天的证据明显属于另一个项目；仓库名对不上项目名很正常，以工作内容为准。实在判断不了填 null。
   证据行末尾带「用户已指定归属」的，必须归入所指定的项目（id 照抄），confidence 填 1，不得改动。
5. evidence：这一条日报依据了哪几条证据，填证据行开头【】里的编号（整数数组），每条至少 1 个，且只能引用下面真实存在的编号。
   没有证据支持的内容不要写——宁可少写，也不要写证据里没有的事。
6. 不需要填工时和完成度，程序会按证据自己计算。
7. confidence：0-1，你对 projectId 归属的把握。
8. 不要调用任何工具，直接输出。

只输出一个 JSON 对象，不要任何其他文字：
{{"items":[{{"workInfo":"1.…… 2.……","projectId":"12","confidence":0.9,"evidence":[1,3,4]}}]}}

可选项目（id: 名称）：
{projects}

最近日报（用户自己写的，归类和写法的参考）：
{history}

今日证据（【编号】时间 [来源] 仓库: 需求 → 结果 | 改动文件）：
{evidence}
"""

# 结果/提交说明里出现这些，说明工作没收尾：完成度要打折，不能当成已完成
PARTIAL = re.compile(r"待验证|待测试|没跑|未跑|没测|未测试|还没提交|没做完|未完成|进行中|WIP|TODO", re.I)
# 完成度（按证据状态，不靠模型估）：{(有提交, 有未收尾标记): %}；只有手记的算 100（用户亲口说做完的）
COMPLETION = {(True, False): 100, (True, True): 80, (False, False): 70, (False, True): 50}


SKIP = "__skip__"  # repo_projects 里的特殊值：这个仓库是私人项目，一律不上报（连 AI 都不给看）


def entry_key(e):
    """一条采集记录的标识，用户单条「不上报」靠它认人（key 由后端算，前端原样回传）"""
    return f'{e["source"]}|{e["time"]}|{e["text"][:40]}'


def is_work(e):
    """有实际产出才算工作：git/SVN 提交，或 AI 在仓库里改了文件的那轮对话。纯聊天/提问/私事不进日报"""
    return e["source"] in ("git", "svn") or bool(e["files"])


def uid(day, e):
    """跨天唯一标识：哪天的哪条记录。分天上报的去重账本靠它"""
    return f"{day}|{entry_key(e)}"


def annotate(day, raws, repo_projects, excluded, picks, reported, maybe=None):
    """决定范围内每条记录进不进 day 这份日报（「存货」模型：做完没报的活可以挪到后面几天报）。

    raws: {日期: raw}（回看范围内每天的采集）；excluded: {日期: [entry_key]}（永不上报）
    picks: {uid: bool}（用户对这份日报的手动勾选）；reported: {uid: 已报在哪天}；maybe: {uid: 日期}（那天手写过日报、但不知道写了啥：不锁，默认不勾）
    返回 entries 加上 date / uid / included / why；why ∈ private|never|reported:日期|maybe:日期|picked|unpicked|work|talk
    默认规则：有实际改动的（今天的、或前几天没报的）算进去，纯聊天不算；用户勾选优先；报过的锁死防重复
    """
    skip = {r for r, v in (repo_projects or {}).items() if v == SKIP}
    out = []
    for d, raw in sorted(raws.items()):
        never = set(excluded.get(d, []))
        for e in raw.get("entries", []):
            u = uid(d, e)
            if e["project"] in skip:
                why, inc = "private", False
            elif entry_key(e) in never:
                why, inc = "never", False
            elif u in reported and reported[u] != day:
                why, inc = f"reported:{reported[u]}", False
            elif u in picks:
                why, inc = ("picked" if picks[u] else "unpicked"), bool(picks[u])
            elif u in (maybe or {}) and maybe[u] != day:
                why, inc = f"maybe:{maybe[u]}", False
            else:
                why, inc = ("work", True) if is_work(e) else ("talk", False)
            out.append({**e, "date": d, "uid": u, "included": inc, "why": why})
    return sorted(out, key=lambda e: (e["date"], e["time"]))


def drop_skipped(raw, repo_projects, excluded=()):
    """去掉：标成私人项目的仓库的所有内容 + 用户单条标了「不上报」的对话"""
    skip = {r for r, v in (repo_projects or {}).items() if v == SKIP}
    ex = set(excluded)
    return {**raw, "entries": [e for e in raw["entries"] if e["project"] not in skip and entry_key(e) not in ex],
            "snapshots": [s for s in raw["snapshots"] if s["project"] not in skip]}


def sample(items, limit):
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def short_path(f, parts=3):
    """保留末尾几层目录，模块名（如 xiaozhi/components）能帮 AI 判断项目；只留文件名看不出来"""
    return "/".join(Path(f).parts[-parts:])


def collect_evidence(raw, notes, projects, repo_projects=None):
    """编号证据 [{n, line, files, kind, partial}]。提示词给 AI 看的和后面算工时、完成度用的是同一份，
    AI 引用的编号才对得上。kind：commit（git/svn 提交）/ chat（AI 对话里改了代码）/ uncommitted / note"""
    names = {p["projectId"]: p["projectName"] for p in projects}
    fixed = {r: pid for r, pid in (repo_projects or {}).items() if pid in names}
    pin = lambda proj: f' 【用户已指定归属：{names[fixed[proj]]}（id {fixed[proj]}）】' if proj in fixed else ""
    ev = []
    for e in sample(raw.get("entries", []), MAX_ENTRIES):
        commit = e["source"] in ("git", "svn")
        files = ", ".join(short_path(f) for f in e["files"][:5])
        what = (e["text"] if commit  # 提交说明本身就是结果
                else f'需求「{e["text"][:120]}」→ 结果「{e.get("reply") or "（无总结）"}」')
        when = e["time"] if e.get("date", raw.get("date")) == raw.get("date") else f'{e["date"][5:]} {e["time"]}'
        ev.append({"line": f'{when} [{e["source"]}] {e["project"]}: {what}'.replace("\n", " ")
                           + (f" | {files}" if files else "") + pin(e["project"]),
                   "files": set(e["files"]), "kind": "commit" if commit else "chat",
                   "partial": bool(PARTIAL.search(e["text"] if commit else e.get("reply") or ""))})
    for s in raw.get("snapshots", [])[-5:]:
        ev.append({"line": f'{s["time"]} [未提交改动] {s["project"]}: '
                           + ", ".join(short_path(f) for f in s["files"][:10]) + pin(s["project"]),
                   "files": set(s["files"]), "kind": "uncommitted", "partial": False})
    for n in notes:
        ev.append({"line": f'{n["time"]} [用户手记] {n["text"]}', "files": set(), "kind": "note", "partial": False})
    for i, x in enumerate(ev, 1):
        x["n"] = i
    return ev


def item_weight(ev, ids):
    """一条日报的工作量权重 = 去重后的改动文件数开方 + 每条依据 0.5 + 每条手记 1。
    按文件并集算，同一批文件的提交和对话不会被算两遍；开方是为了改 100 个文件不至于比改 10 个多十倍工时。
    ponytail: 文件数只是体量的粗略代理，要更准可以给 git 采 --numstat 的增删行数"""
    picked = [ev[i - 1] for i in ids]
    files = set().union(*[x["files"] for x in picked]) if picked else set()
    return max(1.0, math.sqrt(len(files)) + 0.5 * len(picked)) + sum(1 for x in picked if x["kind"] == "note")


def completion(ev, ids):
    """完成度按证据状态定：有提交且没说待验证 100；有提交但说没测完 80；只改了没提交 70（说没收尾 50）；纯手记 100"""
    picked = [ev[i - 1] for i in ids]
    if all(x["kind"] == "note" for x in picked):
        return 100
    return COMPLETION[(any(x["kind"] == "commit" for x in picked), any(x["partial"] for x in picked))]


def build_prompt(raw, notes, projects, hours, history=(), repo_projects=None):
    ev = collect_evidence(raw, notes, projects, repo_projects)
    proj = "\n".join(f'- {p["projectId"]}: {p["projectName"]}' for p in projects) or "（无，projectId 一律填 null）"
    past = "\n".join(f'{d["date"]} 【{i["project"]}】{i["text"][:200]}'.replace("\n", " ")
                     for d in history for i in d["items"]) or "（无）"
    return PROMPT.format(max_items=MAX_ITEMS, projects=proj, history=past,
                         evidence="\n".join(f'【{x["n"]}】{x["line"]}' for x in ev))


def _newest(root, pattern):
    found = sorted(Path(root).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(found[0])] if found else []


def _fresh_path():
    """进程启动后才装的工具，不在当前进程的 PATH 里（装完要重启才生效）：直接读注册表里最新的用户 + 系统 PATH"""
    parts = []
    if os.name == "nt":
        import winreg
        for root, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, sub) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
    return os.pathsep.join(parts + [os.environ.get("PATH", "")])


def _locate(name):
    """某个 AI 工具所有可能的可执行文件，按可靠程度排序。每个人装的位置都不一样：
    命令行（PATH / 官方安装器 / npm）、桌面版、VS Code / Cursor / Windsurf 插件自带的二进制——
    只装了编辑器插件的同事 PATH 里根本没有 claude，必须去插件目录找"""
    home, local, appdata = Path.home(), Path(os.environ.get("LOCALAPPDATA", "")), Path(os.environ.get("APPDATA", ""))
    on_path = shutil.which(name, path=_fresh_path())
    if name == "claude":  # 用户平时在命令行里用的那份最可信，排第一；编辑器插件自带的兜底
        found = [on_path, home / ".local/bin/claude.exe", appdata / "npm/claude.cmd"]
        found += _newest(home, ".*/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe")
    else:  # codex 相反：桌面版 / 插件自带的比较新，PATH 里常是老版 npm 装的（不认新模型），放最后
        found = _newest(local / "OpenAI/Codex/bin", "*/codex.exe")
        found += _newest(home, ".*/extensions/openai.chatgpt-*/bin/*/codex.exe")
        found += [on_path, appdata / "npm/codex.cmd"]
    seen, out = set(), []
    for p in found:
        if p and Path(p).is_file() and os.path.normcase(str(p)) not in seen:  # Windows 路径不分大小写，别重复列
            seen.add(os.path.normcase(str(p)))
            out.append(str(p))
    return out


_providers_cache = {}


def providers(extra=()):
    """[(名字, exe 路径)]，按优先级；结果缓存 30 秒（界面刷新很频繁，别每次都扫磁盘和注册表）。
    extra：用户在设置里手填的路径，最优先；文件名含 codex 的按 codex 调，其余按 claude 调
    （比如公司给同事做了个 claude-ds.cmd，里面先设内网大模型的环境变量再启动 claude，填它就行）。
    claude 只取找到的第一份——几份用的是同一个账号和配置，重试没意义；codex 保留全部，因为 PATH 里常是
    老版 npm 装的（不认新模型），桌面版 / 插件自带的更新，挂了换下一个"""
    key = tuple(extra)
    hit = _providers_cache.get(key)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    mine = [os.path.expandvars(p.strip().strip('"')) for p in extra if p.strip()]
    found = [("codex" if "codex" in Path(p).name.lower() else "claude", p) for p in mine if Path(p).is_file()]
    found += [("claude", p) for p in _locate("claude")[:1]] + [("codex", p) for p in _locate("codex")]
    result = list(dict.fromkeys(found))
    _providers_cache[key] = (time.time(), result)
    return result


def version_of(exe):
    """exe --version 的第一行；跑不起来返回 ''。检测时用，快（15 秒封顶）"""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=15, creationflags=NO_WINDOW)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80] if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def ask_parsed(prompt, provider, exe, n=None):
    try:
        return parse(ask_ai(prompt, provider, exe), n)
    except (ValueError, KeyError, json.JSONDecodeError) as e:  # 格式不对 / 没依据，重试 1 次，把错误告诉它
        return parse(ask_ai(prompt + f"\n\n上次输出不合格（{e}），请严格只输出 JSON，且每条都要有有效的 evidence 编号。",
                            provider, exe), n)


def ask_ai(prompt, provider, exe):
    """调本机 CLI，返回模型输出的文本（应含 JSON）"""
    with tempfile.TemporaryDirectory() as tmp:  # 空目录做 cwd：不加载任何项目的 CLAUDE.md / AGENTS.md
        if provider == "claude":
            # --no-session-persistence：审讯本身不能被记成"工作"，否则下次会被采回来
            args = [exe, "-p", "--no-session-persistence", "--tools", "", "--output-format", "json",
                    "--json-schema", json.dumps(SCHEMA)]
        else:
            schema = Path(tmp) / "schema.json"
            schema.write_text(json.dumps(SCHEMA), "utf-8")
            out = Path(tmp) / "out.json"
            args = [exe, "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
                    "--output-schema", str(schema), "-o", str(out), "-"]
        r = subprocess.run(args, input=prompt, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(f"{provider} 退出码 {r.returncode}: {(r.stderr or r.stdout)[-500:]}")
        if provider == "codex":
            return out.read_text("utf-8")
    res = json.loads(r.stdout)  # claude --output-format json 的外层结果
    if res.get("is_error"):
        raise RuntimeError(f"claude 报错: {str(res.get('result'))[:500]}")
    return json.dumps(res["structured_output"]) if res.get("structured_output") else res.get("result", "")


def parse(text, n=None):
    """从模型输出里抠出 {"items": [...]} 并校验；不合格抛 ValueError。
    n = 证据条数：传了就要求每条日报的 evidence 至少引用 1 个真实存在的编号（1..n），无效编号去掉，
    一个有效依据都没有的条目 = 凭空写的，整体判不合格（让 AI 重来，而不是放进日报）"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        raise ValueError("输出里没有 JSON")
    items = json.loads(text[start:end + 1])["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("items 为空")
    for it in items:
        if not (isinstance(it.get("workInfo"), str) and it["workInfo"].strip()):
            raise ValueError(f"workInfo 缺失: {it}")
        float(it.get("confidence") or 0)  # 非数字直接抛
        if n is not None:
            raw_ids = it.get("evidence")
            ids = sorted({i for i in raw_ids if isinstance(i, int) and 1 <= i <= n}) if isinstance(raw_ids, list) else []
            if not ids:
                raise ValueError(f"没有有效依据（evidence 必须是 1..{n} 里的编号）: {it['workInfo'][:40]}")
            it["evidence"] = ids
    return items


def fit_hours(hours, total):
    """按比例缩放到 total，每项 0.5 的倍数且 ≥0.5，尾差补到最大项"""
    hours = [max(float(h or 0), 0) for h in hours]
    if not sum(hours):
        hours = [1.0] * len(hours)
    out = [max(0.5, round(h / sum(hours) * total * 2) / 2) for h in hours]
    out[out.index(max(out))] += total - sum(out)
    return out


POINT = re.compile(r"(?:^|\s)\d{1,2}[.、．](?!\d)")  # "1.修bug 2.加按钮" 的序号，不误伤 "2.5 倍"


def merge_points(texts):
    """多段「1.xx 2.yy」合并成一段并连续重编号"""
    points = [p.strip() for t in texts for p in POINT.split(t) if p.strip()]
    return "\n".join(f"{i}.{p}" for i, p in enumerate(points, 1))


def finalize(items, projects, hours, default_project, ev):
    """同项目合并、工时、完成度都在代码里算，不靠 AI：
    工时 = 总工时按各条依据的体量权重分配；完成度 = 按依据的状态定；拿不准的项目 → 默认项目并标 doubt。
    每条带 basis（依据原文），界面可展开核对"""
    valid = {str(p["projectId"]) for p in projects}
    merged = {}  # projectId → {texts, ids, doubt}，保持首次出现顺序
    for it in items:
        pid = None if it.get("projectId") is None else str(it["projectId"])
        m = merged.setdefault(default_project if pid not in valid else pid, {"texts": [], "ids": set(), "doubt": False})
        m["texts"].append(it["workInfo"].strip())
        m["ids"] |= set(it["evidence"])
        m["doubt"] |= pid not in valid or float(it.get("confidence") or 0) < 0.6
    rows = [(pid, m, sorted(m["ids"])) for pid, m in list(merged.items())[:MAX_ITEMS]]
    times = fit_hours([item_weight(ev, ids) for _, _, ids in rows], hours)
    return [{"workInfo": merge_points(m["texts"]), "projectId": pid, "workTime": t,
             "completionDegree": completion(ev, ids), "doubt": m["doubt"],
             "basis": [ev[i - 1]["line"] for i in ids][:12]}
            for (pid, m, ids), t in zip(rows, times)]


def interrogate(day, projects=(), hours=8.0, default_project=None, data_dir=None, provider=None, history=(),
                repo_projects=None, evidence=None, ai_paths=()):
    """返回并写入 draft.json；没有证据返回 items=[]（不编造，由调用方提醒用户手填）。
    evidence：调用方（bridge）按回看范围 + 用户勾选挑好的条目（annotate 里 included 的）；
    不传 = 命令行老路径：只用当天、按默认规则（有实际改动才算）"""
    folder = Path(data_dir or default_data_dir()) / day.isoformat()
    raw = json.loads((folder / "raw.json").read_text("utf-8"))
    if evidence is None:
        excluded_file = folder / "excluded.json"
        excluded = json.loads(excluded_file.read_text("utf-8")) if excluded_file.exists() else []
        raw = drop_skipped(raw, repo_projects, excluded)
        evidence = [{**e, "date": day.isoformat(), "uid": uid(day.isoformat(), e)} for e in raw["entries"] if is_work(e)]
    else:
        raw = drop_skipped({**raw, "entries": []}, repo_projects)  # 只为过滤私人仓库的未提交快照
    raw["entries"] = evidence
    notes_file = folder / "notes.json"
    notes = json.loads(notes_file.read_text("utf-8")) if notes_file.exists() else []
    notes = [n for n in notes if n.get("text", "").strip()]  # 空手记不算证据
    draft = {"date": day.isoformat(), "generated_at": datetime.now().isoformat(timespec="seconds"),
             "provider": None, "items": [],
             "used": [e["uid"] for e in evidence]}  # 提交成功后记账：这些条目已报，以后不会再被挪进别天的日报
    ev = collect_evidence(raw, notes, list(projects), repo_projects)
    if ev:
        candidates = [c for c in providers(ai_paths) if c[0] == provider or not provider]
        if not candidates:
            raise RuntimeError("没找到 claude 或 codex（命令行、桌面版、VS Code/Cursor 插件里都没有）。"
                               "装了的话，去设置里「AI 工具」填上它的完整路径，点「检测」确认")
        prompt = build_prompt(raw, notes, list(projects), hours, history, repo_projects)
        errors = []
        for p, exe in candidates:  # 一个挂了（额度/配置/网络/版本旧）换下一个，18:00 前不能断
            try:
                items = ask_parsed(prompt, p, exe, n=len(ev))
                break
            except Exception as e:
                errors.append(f"{exe}: {e}")
        else:
            raise RuntimeError("审讯失败\n" + "\n".join(errors))
        draft["provider"] = p
        draft["items"] = finalize(items, list(projects), hours, default_project, ev)
    (folder / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1), "utf-8")
    return draft


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    cache = default_data_dir() / "projects.json"  # P3 登录后由 delta_client 缓存
    projs = json.loads(cache.read_text("utf-8")) if cache.exists() else []
    result = interrogate(d, projs, provider=sys.argv[2] if len(sys.argv) > 2 else None)
    print(f'provider={result["provider"]}')
    for it in result["items"]:
        print(f'[{it["projectId"]}] {it["workTime"]}h {it["completionDegree"]}%{" 存疑" if it["doubt"] else ""}\n  {it["workInfo"]}')
