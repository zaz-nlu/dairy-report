"""审讯：raw.json(+notes.json) → AI 整理 → draft.json

用法：python interrogate.py [YYYY-MM-DD]（默认今天，需先 collect）
AI 自动选：有 claude 用 `claude -p`，否则 `codex exec`；都沿用本机已配好的后端。
草稿条目：{workInfo, projectId, workTime, completionDegree, doubt}，按项目一条。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
        "required": ["workInfo", "projectId", "workTime", "completionDegree", "confidence"],
        "properties": {"workInfo": {"type": "string"}, "projectId": {"type": ["string", "null"]},
                       "workTime": {"type": "number"}, "completionDegree": {"type": "number"},
                       "confidence": {"type": "number"}}}}}}

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
5. workTime：各条之和 = {hours} 小时，按工作量分配。
6. completionDegree：0-100，该项工作到今天结束的完成度估计。
7. confidence：0-1，你对 projectId 归属的把握。
8. 不要调用任何工具，直接输出。

只输出一个 JSON 对象，不要任何其他文字：
{{"items":[{{"workInfo":"1.…… 2.……","projectId":"12","workTime":4,"completionDegree":80,"confidence":0.9}}]}}

可选项目（id: 名称）：
{projects}

最近日报（用户自己写的，归类和写法的参考）：
{history}

今日证据（时间 [来源] 仓库: 需求 → 结果 | 改动文件）：
{evidence}
"""


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


def annotate(day, raws, repo_projects, excluded, picks, reported):
    """决定范围内每条记录进不进 day 这份日报（「存货」模型：做完没报的活可以挪到后面几天报）。

    raws: {日期: raw}（回看范围内每天的采集）；excluded: {日期: [entry_key]}（永不上报）
    picks: {uid: bool}（用户对这份日报的手动勾选）；reported: {uid: 已报在哪天}
    返回 entries 加上 date / uid / included / why；why ∈ private|never|reported:日期|picked|unpicked|work|talk
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


def build_prompt(raw, notes, projects, hours, history=(), repo_projects=None):
    names = {p["projectId"]: p["projectName"] for p in projects}
    fixed = {r: pid for r, pid in (repo_projects or {}).items() if pid in names}
    lines = []
    for e in sample(raw.get("entries", []), MAX_ENTRIES):
        files = ", ".join(short_path(f) for f in e["files"][:5])
        pin = f' 【用户已指定归属：{names[fixed[e["project"]]]}（id {fixed[e["project"]]}）】' if e["project"] in fixed else ""
        what = (f'{e["text"]}' if e["source"] in ("git", "svn")  # 提交说明本身就是结果
                else f'需求「{e["text"][:120]}」→ 结果「{e.get("reply") or "（无总结）"}」')
        when = e["time"] if e.get("date", raw.get("date")) == raw.get("date") else f'{e["date"][5:]} {e["time"]}'
        lines.append(f'{when} [{e["source"]}] {e["project"]}: {what}'.replace("\n", " ")
                     + (f" | {files}" if files else "") + pin)
    for s in raw.get("snapshots", [])[-5:]:
        pin = f' 【用户已指定归属：{names[fixed[s["project"]]]}（id {fixed[s["project"]]}）】' if s["project"] in fixed else ""
        lines.append(f'{s["time"]} [未提交改动] {s["project"]}: ' + ", ".join(short_path(f) for f in s["files"][:10]) + pin)
    for n in notes:
        lines.append(f'{n["time"]} [用户手记] {n["text"]}')
    proj = "\n".join(f'- {p["projectId"]}: {p["projectName"]}' for p in projects) or "（无，projectId 一律填 null）"
    past = "\n".join(f'{d["date"]} 【{i["project"]}】{i["text"][:200]}'.replace("\n", " ")
                     for d in history for i in d["items"]) or "（无）"
    return PROMPT.format(max_items=MAX_ITEMS, hours=hours, projects=proj, history=past, evidence="\n".join(lines))


def _newest(root, pattern):
    found = sorted(Path(root).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(found[0])] if found else []


def providers():
    """[(名字, exe 路径)]，按优先级。codex 常装了好几份：PATH 里可能是老的 npm 版（不认新模型），
    桌面版 / VS Code 插件自带的更新，所以都列上，挂了换下一个"""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    codex = (_newest(local / "OpenAI/Codex/bin", "*/codex.exe")
             + _newest(Path.home() / ".vscode/extensions", "openai.chatgpt-*/bin/*/codex.exe")
             + [p for p in [shutil.which("codex")] if p])
    found = [("claude", p) for p in [shutil.which("claude")] if p] + [("codex", p) for p in codex]
    return list(dict.fromkeys(found))


def ask_parsed(prompt, provider, exe):
    try:
        return parse(ask_ai(prompt, provider, exe))
    except (ValueError, KeyError, json.JSONDecodeError) as e:  # 格式不对重试 1 次，把错误告诉它
        return parse(ask_ai(prompt + f"\n\n上次输出不合格（{e}），请严格只输出 JSON。", provider, exe))


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


def parse(text):
    """从模型输出里抠出 {"items": [...]} 并校验字段类型；不合格抛 ValueError"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        raise ValueError("输出里没有 JSON")
    items = json.loads(text[start:end + 1])["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("items 为空")
    for it in items:
        if not (isinstance(it.get("workInfo"), str) and it["workInfo"].strip()):
            raise ValueError(f"workInfo 缺失: {it}")
        for k in ("workTime", "completionDegree", "confidence"):
            float(it.get(k) or 0)  # 非数字直接抛
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


def finalize(items, projects, hours, default_project):
    """数值规整、同项目合并都在代码里做，不靠 AI；拿不准的项目 → 默认项目并标 doubt"""
    valid = {str(p["projectId"]) for p in projects}
    merged = {}  # projectId → {texts, time, done, doubt}，保持首次出现顺序
    for it in items:
        pid = None if it.get("projectId") is None else str(it["projectId"])
        m = merged.setdefault(default_project if pid not in valid else pid,
                              {"texts": [], "time": 0.0, "done": 0.0, "doubt": False})
        m["texts"].append(it["workInfo"].strip())
        m["time"] += max(float(it.get("workTime") or 0), 0)
        m["done"] = max(m["done"], float(it.get("completionDegree") or 0))
        m["doubt"] |= pid not in valid or float(it.get("confidence") or 0) < 0.6
    rows = list(merged.items())[:MAX_ITEMS]
    times = fit_hours([m["time"] for _, m in rows], hours)
    return [{"workInfo": merge_points(m["texts"]), "projectId": pid, "workTime": t,
             "completionDegree": min(100, max(0, round(m["done"] / 5) * 5)), "doubt": m["doubt"]}
            for (pid, m), t in zip(rows, times)]


def interrogate(day, projects=(), hours=8.0, default_project=None, data_dir=None, provider=None, history=(),
                repo_projects=None, evidence=None):
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
    if raw["entries"] or raw["snapshots"] or notes:
        candidates = [c for c in providers() if c[0] == provider or not provider]
        if not candidates:
            raise RuntimeError("没找到 claude 或 codex 命令，无法审讯")
        prompt = build_prompt(raw, notes, list(projects), hours, history, repo_projects)
        errors = []
        for p, exe in candidates:  # 一个挂了（额度/配置/网络/版本旧）换下一个，18:00 前不能断
            try:
                items = ask_parsed(prompt, p, exe)
                break
            except Exception as e:
                errors.append(f"{exe}: {e}")
        else:
            raise RuntimeError("审讯失败\n" + "\n".join(errors))
        draft["provider"] = p
        draft["items"] = finalize(items, list(projects), hours, default_project)
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
