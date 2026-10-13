"""前后端契约 —— 前端只依赖这份清单，不碰其他 Python 文件。

调用：await window.pywebview.api.<方法>(参数...)   （等 window 的 'pywebviewready' 事件后再调）
失败：Promise reject，err.message 是给用户看的中文原因。
日期参数一律 "YYYY-MM-DD"，省略 = 今天。

get_state()                       → 首页一次拿全：
    {today, now, kind: "work"|"rest"|"leave", submit_time, interrogate_time,
     result: null | {status: "submitted"|"exists"|"failed"|"empty", at, error, attempts, items},
     draft:  null | {date, generated_at, provider, items: [条目]},
     notes: [{time, text}],
     entries: [{source: "git"|"svn"|"claude"|"codex", date, time, project, cwd, text, files, reply, key, uid, included, why}],
       回看范围（lookback_days 天）内的全部记录，按日期、时间排序。
       text = 用户原话/提交说明；reply = 这轮 AI 干完活的总结；files = 仓库内被改的文件。
       included = 这条进不进今天这份日报（前端画成勾选框）；why = 原因：
         work 有实际改动（默认勾）/ talk 纯聊天（默认不勾）/ picked、unpicked 用户手动勾过 /
         private 私人仓库 / never 永不上报 / reported:YYYY-MM-DD 已在那天报过（锁死，防重复）。
       date 不是今天的 = 前几天做完没报、可以挪到今天报的「存货」
     lookback_days: 1|3|7,
     excluded: [key]（用户单条标了「不上报」的 entries[].key）,
     snapshots: [{time, project, cwd, files}], collected_at, providers: ["claude","codex"],
     project_names: {projectId: 项目名}（条目里只有 projectId，显示名字查这个）,
     recent_projects: [projectId]（最近日报里用过的项目，按次数排序，下拉框里放最前）,
     repo_projects: {仓库名: projectId}（用户指定的归属，entries[].project 就是仓库名）,
     configured: bool（账号密码都填了；项目/任务类型/汇报人留空 = 自动沿用上次日报，不算没配置）}
    条目 = {workInfo, projectId, workTime, completionDegree, doubt}
get_config()                      → config.DEFAULTS 的全部字段 + {has_password, autostart}
save_config(cfg, password=None)   → 同 get_config；password 只在改密码时传
fetch_options(username=None, password=None)
                                  → {projects: [{projectId, projectName}], task_types: [{projectTypeId, projectTypeName}],
                                     report_users: [{id, label}]}；不传账号则用已保存的；顺带验证账号密码
collect_now(date=None)            → raw {date, collected_at, entries, snapshots}
interrogate_now(date=None)        → draft（会先重新采集；AI 调用约 30-60 秒）
save_draft(items, date=None)      → draft（用户在认罪书里改完保存；条目含 workInfo/projectId/workTime/completionDegree/doubt，
                                    改过的草稿 17:30 不会被自动审讯覆盖）
pick_entry(uid, on, date=None)    → picks；勾选/取消某条进 date 这份日报（覆盖默认规则；uid 取自 entries[].uid）
exclude_entry(key, on, date)      → excluded；某条永不上报（on=false 恢复）。date 传 entries[].date（记录是哪天的）
回看范围：save_config({lookback_days: 1|3|7})；改完 get_state 会带上前几天没报的记录
set_repo_project(repo, project_id) → repo_projects；把某仓库固定归到某项目（下次审讯起生效），project_id 空 = 取消；
                                    project_id = "__skip__" 表示私人项目：该仓库的对话/改动完全不上报，也不发给 AI
                                    （前端把这类 entries 置灰加删除线，下拉框里叫「不上报（私人项目）」）
add_note(text, date=None)         → notes（"今天开了需求评审会"之类，作为审讯素材）
remove_note(index, date=None)     → notes
submit_now(date=None)             → result（手动画押/补交；已交过返回 status="exists"）
history(limit=60)                 → [{date, kind, status|null, items, hours}] 新→旧
day_detail(date)                  → {raw, draft, result, notes}
set_leave(date, on)               → config
set_autostart(on)                 → config
open_web()                        → 用默认浏览器打开日报系统
hide_window() / quit_app()

后端主动推送：window.onBackendEvent(event)，event.type:
    "state"   状态变了（采集/审讯/提交完成），前端重新 get_state()
    "notify"  {title, message}，同时已发托盘气泡
"""
import json
import logging
import os
import subprocess
import sys
import threading
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from collect import NO_WINDOW, collect
from delta_client import WEB, Delta, DeltaError
from interrogate import annotate, entry_key, interrogate, providers, uid

log = logging.getLogger("daily-prison")
RETRY_MINUTES = [5, 10]       # 失败后 +5min、再 +10min 各重试一次（18:05、18:15）
INTERROGATE_BACKOFF = timedelta(minutes=10)
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/日报越狱.lnk"


def _read(path, default=None):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")


def _minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _day(d):
    return date.fromisoformat(d) if d else date.today()


class Api:
    def __init__(self):
        # ponytail: 一把全局锁串行化采集/审讯/提交（调度线程 + 前端调用），一天就几次操作，够用
        self._lock = threading.RLock()
        self._notify_cb = lambda title, message: None
        self._push_cb = lambda event: None
        self._show_cb = self._hide_cb = self._quit_cb = lambda: None
        self._last_collect = None
        self._interrogate_failed_at = None

    # ---------- 内部 ----------
    def _folder(self, day, cfg=None):
        return config.data_dir(cfg or config.load()) / day.isoformat()

    def _client(self, cfg, username=None, password=None):
        username = username or cfg["username"]
        password = password or config.get_password(username)
        if not username or not password:
            raise DeltaError("还没填日报系统账号密码，去典狱长办公室登记")
        return Delta(username, password)

    def _notify(self, title, message):
        log.info("通知 %s：%s", title, message)
        self._notify_cb(title, message)
        self._push_cb({"type": "notify", "title": title, "message": message})

    def _changed(self):
        self._push_cb({"type": "state"})

    # ---------- 状态 / 设置 ----------
    def _annotated(self, day, cfg):
        """回看范围内的所有记录，标好进不进 day 这份日报（规则见 interrogate.annotate）"""
        root = config.data_dir(cfg)
        raws, excluded = {}, {}
        for i in range(max(1, int(cfg["lookback_days"] or 1))):
            d = day - timedelta(days=i)
            folder = root / d.isoformat()
            raw = _read(folder / "raw.json")
            # 过去的日子：如果是当天采的，可能漏了那天晚上的活，补采一次；之后就是定稿，不再重采
            if d < day and (raw is None or str(raw.get("collected_at", ""))[:10] <= d.isoformat()):
                raw = collect(d, cfg["sources"], cfg["extra_repos"], root)
            raws[d.isoformat()] = raw or {"entries": []}
            excluded[d.isoformat()] = _read(folder / "excluded.json", [])
        picks = _read(root / day.isoformat() / "picks.json", {})
        return annotate(day.isoformat(), raws, cfg["repo_projects"], excluded, picks, self._reported(day, cfg, raws))

    def _reported(self, day, cfg, raws):
        """{uid: 报在哪天}。来源：① 本软件提交时记的账（result.used）；
        ② 没有账、但那天日报系统里有记录（手写的、或软件上线前交的）→ 当作那天的记录全报过了，防止翻旧账重复上报"""
        root = config.data_dir(cfg)
        rep = {}
        for folder in sorted(root.glob("????-??-??"))[-30:]:
            r = _read(folder / "result.json") or {}
            if folder.name != day.isoformat() and r.get("status") == "submitted":
                rep.update({u: folder.name for u in r.get("used", [])})
        submitted = {h["date"] for h in _read(root / "options.json", {}).get("history", [])}
        for d, raw in raws.items():
            r = _read(root / d / "result.json") or {}
            manual = r.get("status") == "exists" or ("used" not in r and (d in submitted or r.get("status") == "submitted"))
            if d != day.isoformat() and manual:
                rep.update({uid(d, e): d for e in raw.get("entries", [])})
        return rep

    def pick_entry(self, entry_uid, on, date=None):
        """用户勾选/取消某条记录进这份日报（覆盖默认规则）"""
        path = self._folder(_day(date)) / "picks.json"
        picks = {**_read(path, {}), entry_uid: bool(on)}
        _write(path, picks)
        return picks

    def get_state(self):
        cfg, today = config.load(), date.today()
        folder = self._folder(today, cfg)
        raw = _read(folder / "raw.json", {})
        opts = _read(config.data_dir(cfg) / "options.json", {})
        names = {p["projectId"]: p["projectName"] for p in opts.get("projects", [])}
        by_name = {v: k for k, v in names.items()}
        freq = Counter(i["project"] for d in opts.get("history", []) for i in d["items"])
        recent = [by_name[n] for n, _ in freq.most_common() if n in by_name]  # 你最近交过的项目，下拉框里排前面
        return {"today": today.isoformat(), "now": datetime.now().isoformat(timespec="seconds"),
                "kind": config.day_kind(today, cfg),
                "submit_time": cfg["submit_time"], "interrogate_time": cfg["interrogate_time"],
                "result": _read(folder / "result.json"), "draft": _read(folder / "draft.json"),
                "notes": _read(folder / "notes.json", []),
                "entries": [{**e, "key": entry_key(e)} for e in self._annotated(today, cfg)],
                "lookback_days": cfg["lookback_days"],
                "excluded": _read(folder / "excluded.json", []), "snapshots": raw.get("snapshots", []),
                "collected_at": raw.get("collected_at"), "providers": sorted({n for n, _ in providers()}),
                "project_names": names, "recent_projects": recent, "repo_projects": cfg["repo_projects"],
                "configured": bool(cfg["username"] and config.get_password(cfg["username"]))}

    def get_config(self):
        cfg = config.load()
        return {**cfg, "has_password": bool(config.get_password(cfg["username"])),
                "autostart": STARTUP_LNK.exists()}

    def save_config(self, cfg, password=None):
        saved = config.save(cfg)
        if password:
            config.set_password(saved["username"], password)
        self._changed()
        return self.get_config()

    def fetch_options(self, username=None, password=None):
        cfg = config.load()
        c = self._client(cfg, username, password)
        path = config.data_dir(cfg) / "options.json"
        # 合并写入，且带上 history：以前这里整个覆盖，把 history 冲掉了 → 回看多天时认不出哪天交过 → 会把旧活重报
        opts = {**(_read(path) or {}), "projects": c.projects(), "task_types": c.task_types(),
                "report_users": c.report_users(), "auto": c.last_defaults(),  # auto：上次日报里的选择，设置页留空时就用它
                "history": c.recent_reports()}
        _write(path, opts)
        return opts

    def _options(self, cfg, client=None):
        """自动流程用：登录日报系统取项目列表 + 上次选择，落盘缓存；断网/登录失败退回缓存，不让 17:30 审讯因此断掉"""
        path = config.data_dir(cfg) / "options.json"
        try:
            c = client or self._client(cfg)
            opts = {**(_read(path) or {}), "projects": c.projects(), "auto": c.last_defaults(),
                    "history": c.recent_reports()}
            _write(path, opts)
        except DeltaError:
            log.exception("取项目列表失败，用缓存")
            opts = _read(path) or {}
        return {"projects": opts.get("projects", []), "auto": opts.get("auto", {}), "history": opts.get("history", [])}

    def _default_project(self, cfg, opts):
        return cfg["default_project"] or opts["auto"].get("default_project")

    # ---------- 搜身 / 审讯 / 画押 ----------
    def collect_now(self, date=None):
        with self._lock:
            cfg, day = config.load(), _day(date)
            raw = collect(day, cfg["sources"], cfg["extra_repos"], config.data_dir(cfg))
            if day == datetime.now().date():
                self._last_collect = datetime.now()
            self._changed()
            return raw

    def interrogate_now(self, date=None):
        with self._lock:
            self.collect_now(date)
            cfg = config.load()
            opts = self._options(cfg)  # 顺带刷新 history，_reported 要用它判断哪些天已经交过
            evidence = [e for e in self._annotated(_day(date), cfg) if e["included"]]
            draft = interrogate(_day(date), opts["projects"], cfg["hours"], self._default_project(cfg, opts),
                                config.data_dir(cfg), history=opts["history"], repo_projects=cfg["repo_projects"],
                                evidence=evidence)
            self._changed()
            return draft

    def save_draft(self, items, date=None):
        with self._lock:
            path = self._folder(_day(date)) / "draft.json"
            draft = _read(path) or {"date": _day(date).isoformat(), "provider": "manual"}
            draft.update(items=items, edited_at=datetime.now().isoformat(timespec="seconds"))
            _write(path, draft)
            self._changed()
            return draft

    def add_note(self, text, date=None):
        if not (text or "").strip():
            raise ValueError("手记是空的")  # 空手记会让审讯以为有证据，去让 AI 硬编
        path = self._folder(_day(date)) / "notes.json"
        notes = _read(path, []) + [{"time": datetime.now().strftime("%H:%M"), "text": text.strip()}]
        _write(path, notes)
        return notes

    def remove_note(self, index, date=None):
        path = self._folder(_day(date)) / "notes.json"
        notes = _read(path, [])
        notes.pop(int(index))
        _write(path, notes)
        return notes

    def submit_now(self, date=None):
        return self._submit(_day(date), auto=False)

    def _submit(self, day, auto):
        with self._lock:
            cfg = config.load()
            path = self._folder(day, cfg) / "result.json"
            attempts = (_read(path) or {}).get("attempts", 0) + 1
            items, used = [], []
            try:
                client = self._client(cfg)
                if config.day_kind(day, cfg) == "leave":
                    status = client.submit(day, [], {}, leave=True)
                else:
                    draft = _read(self._folder(day, cfg) / "draft.json") or self.interrogate_now(day.isoformat())
                    items, used = draft["items"], draft.get("used", [])
                    if not items:
                        result = {"status": "empty", "at": datetime.now().isoformat(timespec="seconds"),
                                  "error": "今天没采到任何工作痕迹，去认罪书手填后再画押", "attempts": attempts, "items": []}
                        _write(path, result)
                        self._notify("越狱警报：认罪书是空的", result["error"])
                        self._changed()
                        return result
                    opts = self._options(cfg, client)
                    auto = opts["auto"]
                    defaults = {"taskTypeId": cfg["task_type"] or auto.get("task_type"),
                                "reportUserId": cfg["report_user"] or auto.get("report_user"),
                                "priority": cfg["priority"] or auto.get("priority") or 2}
                    project = self._default_project(cfg, opts)
                    items = [{**it, "projectId": it.get("projectId") or project} for it in items]  # 草稿生成时没取到默认值的补上
                    if not (defaults["taskTypeId"] and defaults["reportUserId"]) or not all(it["projectId"] for it in items):
                        raise DeltaError("没有历史日报可沿用，请在设置里选默认项目 / 任务类型 / 汇报人")
                    status = client.submit(day, items, defaults)
                result = {"status": status, "at": datetime.now().isoformat(timespec="seconds"),
                          "error": None, "attempts": attempts, "items": items,
                          "used": used}  # 记账：这些记录已报，分天上报时不会再被挪进别天
                if status == "exists":
                    self._notify("今日已画押", "日报系统里已经有今天的日报，没有重复提交")
                else:
                    doubt = sum(1 for it in items if it.get("doubt"))
                    self._notify("画押成功，今日刑满释放",
                                 f"已交 {len(items)} 条，共 {sum(it['workTime'] for it in items)} 小时"
                                 + (f"；{doubt} 条存疑，去网页核对一下" if doubt else ""))
            except Exception as e:
                log.exception("提交失败")
                result = {"status": "failed", "at": datetime.now().isoformat(timespec="seconds"),
                          "error": str(e), "attempts": attempts, "items": items}
                last = attempts > len(RETRY_MINUTES)
                self._notify("越狱失败！¥200 罚单警告" if last else "画押失败，稍后自动重试", str(e))
            _write(path, result)
            if auto:
                self._show_cb()  # 自动提交后弹出窗口给用户看交了什么
            self._changed()
            return result

    def tick(self, now=None):
        """调度一步（app 每 30 秒调一次；测试可传假时间）。睡眠/关机错过 18:00 的，醒来后当天内补交。"""
        now = now or datetime.now()
        day, cfg = now.date(), config.load()
        kind = config.day_kind(day, cfg)
        if kind == "rest":
            return
        folder, minute = self._folder(day, cfg), now.hour * 60 + now.minute
        if kind == "work":
            if not self._last_collect or now - self._last_collect >= timedelta(hours=cfg["collect_every_hours"]):
                self._safe(self.collect_now)
            draft = _read(folder / "draft.json")
            # 白天手动审讯的草稿会漏掉下午的活，到点重审；用户改过的不动
            stale = draft is None or (not draft.get("edited_at")
                                      and draft.get("generated_at", "") < f"{day}T{cfg['interrogate_time']}")
            if (minute >= _minutes(cfg["interrogate_time"]) and stale
                    and not (self._interrogate_failed_at and now - self._interrogate_failed_at < INTERROGATE_BACKOFF)):
                draft = self._safe(self.interrogate_now)
                if draft is None:
                    self._interrogate_failed_at = now
                elif draft["items"]:
                    self._notify("典狱长：还有 30 分钟查房",
                                 f"认罪书已拟好 {len(draft['items'])} 条，{cfg['submit_time']} 自动画押，可以先去看看")
                else:
                    self._notify("典狱长：还有 30 分钟查房", "今天没搜到任何工作痕迹，去认罪书手填，不然交不上")
        if minute >= _minutes(cfg["submit_time"]):
            r = _read(folder / "result.json")
            if r is None or (r["status"] == "failed" and r["attempts"] <= len(RETRY_MINUTES)
                             and now >= datetime.fromisoformat(r["at"]) + timedelta(minutes=RETRY_MINUTES[r["attempts"] - 1])):
                self._submit(day, auto=True)

    def _safe(self, fn):
        try:
            return fn()
        except Exception:
            log.exception("%s 失败", fn.__name__)
            return None

    def _tray_title(self):
        cfg, now = config.load(), datetime.now()
        kind = config.day_kind(now.date(), cfg)
        r = _read(self._folder(now.date(), cfg) / "result.json") or {}
        if kind == "rest":
            return "日报越狱 · 今日放风"
        if r.get("status") in ("submitted", "exists"):
            return "日报越狱 · 今日已画押"
        left = _minutes(cfg["submit_time"]) * 60 - (now.hour * 3600 + now.minute * 60 + now.second)
        if left <= 0:
            return "日报越狱 · 越狱失败，快补交！"
        return f"服刑中 · 剩 {left // 3600:02d}:{left % 3600 // 60:02d}:{left % 60:02d}"

    # ---------- 历史 ----------
    def history(self, limit=60):
        cfg = config.load()
        root = config.data_dir(cfg)
        out = []
        for folder in sorted((p for p in root.glob("????-??-??") if p.is_dir()), reverse=True)[:limit]:
            r = _read(folder / "result.json") or {}
            items = r.get("items") or (_read(folder / "draft.json") or {}).get("items", [])
            out.append({"date": folder.name, "kind": config.day_kind(date.fromisoformat(folder.name), cfg),
                        "status": r.get("status"), "items": len(items),
                        "hours": sum(it.get("workTime", 0) for it in items)})
        return out

    def day_detail(self, date):
        folder = self._folder(_day(date))
        return {"raw": _read(folder / "raw.json"), "draft": _read(folder / "draft.json"),
                "result": _read(folder / "result.json"), "notes": _read(folder / "notes.json", [])}

    # ---------- 杂项 ----------
    def exclude_entry(self, key, on, date=None):
        """某一条对话/提交单独标为「不上报」（key 取自 get_state().entries[].key）；on=False 恢复"""
        path = self._folder(_day(date)) / "excluded.json"
        keys = [k for k in _read(path, []) if k != key] + ([key] if on else [])
        _write(path, keys)
        return keys

    def set_repo_project(self, repo, project_id):
        """把某个仓库（entries[].project）固定归到某个项目；project_id 为空 = 取消，交回 AI 判断"""
        m = {k: v for k, v in config.load()["repo_projects"].items() if k != repo}
        if project_id:
            m[repo] = project_id
        config.save({"repo_projects": m})
        return m

    def set_leave(self, date, on):
        cfg = config.load()
        days = set(cfg["leave_days"]) - {date} | ({date} if on else set())
        config.save({"leave_days": sorted(days)})
        self._changed()
        return self.get_config()

    def set_autostart(self, on):
        if on:
            target, args = (sys.executable, "--tray") if getattr(sys, "frozen", False) else \
                (str(Path(sys.executable).with_name("pythonw.exe")), f'"{Path(__file__).with_name("app.py")}" --tray')
            STARTUP_LNK.parent.mkdir(parents=True, exist_ok=True)
            ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{STARTUP_LNK}');"
                  f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.Save()")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=NO_WINDOW)
        else:
            STARTUP_LNK.unlink(missing_ok=True)
        return self.get_config()

    def open_web(self):
        os.startfile(WEB)

    def hide_window(self):
        self._hide_cb()

    def quit_app(self):
        self._quit_cb()
