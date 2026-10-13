"""设置读写：%APPDATA%\\daily-prison\\config.json；密码进 Windows 凭据管理器"""
import json
import os
from datetime import date
from pathlib import Path

import keyring

from collect import default_data_dir

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "daily-prison"
CONFIG_FILE = APP_DIR / "config.json"
SERVICE = "daily-prison"

if os.name == "nt":  # PyInstaller 打包后 keyring 靠 entry point 找后端会失败，直接指定
    from keyring.backends.Windows import WinVaultKeyring
    keyring.set_keyring(WinVaultKeyring())

DEFAULTS = {
    "username": "",
    "sources": ["git", "claude", "codex"],
    "extra_repos": [],          # 对话里没出现过、但也要采 git 的仓库目录
    "data_dir": "",             # 空 = D:\工作（没有 D 盘则 ~/daily-prison）
    "collect_every_hours": 4,
    "interrogate_time": "17:30",
    "submit_time": "18:00",
    "hours": 8.0,
    "default_project": None,    # 日报系统的 projectId，如 "7-296"；None = 沿用上次日报（task_type/report_user 同）
    "task_type": None,          # projectTypeId
    "report_user": None,        # 汇报人 id
    "priority": None,           # 1低 2中 3高 4紧急；None = 沿用上次日报
    "holidays": [],             # 法定节假日 "YYYY-MM-DD"（休息）
    "workdays": [],             # 调休上班的周末 "YYYY-MM-DD"
    "leave_days": [],           # 请假 "YYYY-MM-DD"（提交请假记录）
    "repo_projects": {},        # 用户指定「仓库名 → projectId」，该仓库的活一律归这个项目，AI 不再猜
    "confirm_seconds": 60,      # 到点后先弹确认窗口倒计时多少秒，不理它就自动提交；0 = 不确认直接提交
    "fine": 100,                # 漏交一次罚多少钱（元）；界面上的「罚单」「累计罚款」都按它算
    "ai_paths": [],             # 手填的 claude / codex 路径（一行一个），留空自动找；装在特殊位置或用脚本包了一层时用
    "lookback_days": 1,        # 回看几天：1/3/7。>1 时前几天做完没报的活会出现在今天，用来把一天的大量工作分几天报
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
    return cfg


def save(patch):
    cfg = {**load(), **{k: v for k, v in patch.items() if k in DEFAULTS}}
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), "utf-8")
    return cfg


def data_dir(cfg):
    return Path(cfg["data_dir"]) if cfg.get("data_dir") else default_data_dir()


def get_password(username):
    return keyring.get_password(SERVICE, username) if username else None


def set_password(username, password):
    keyring.set_password(SERVICE, username, password)


def day_kind(day, cfg):
    """'leave' 请假 / 'rest' 周末或节假日 / 'work'"""
    d = day.isoformat()
    if d in cfg["leave_days"]:
        return "leave"
    if d in cfg["holidays"] or (day.weekday() >= 5 and d not in cfg["workdays"]):
        return "rest"
    return "work"


if __name__ == "__main__":
    c = dict(DEFAULTS)
    assert day_kind(date(2026, 10, 13), c) == "work"   # 周二
    assert day_kind(date(2026, 10, 17), c) == "rest"   # 周六
    assert day_kind(date(2026, 10, 17), {**c, "workdays": ["2026-10-17"]}) == "work"
    assert day_kind(date(2026, 10, 13), {**c, "holidays": ["2026-10-13"]}) == "rest"
    assert day_kind(date(2026, 10, 13), {**c, "leave_days": ["2026-10-13"]}) == "leave"
    print("ok")
