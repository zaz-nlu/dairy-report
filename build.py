"""一键打包：python build.py
1) PyInstaller 把程序打成不依赖 Python 的文件夹（dist/DailyPrison）
2) 组装安装包文件夹（程序 + 安装 / 卸载脚本 + 使用说明）
3) 压成 zip（dist/日报越狱-安装包-<版本>.zip），发给别人解压后双击「安装.bat」就行
"""
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.0"
ROOT = Path(__file__).parent
DIST = ROOT / "dist"
PKG = DIST / "日报越狱-安装包"


def run(args):
    print(">", " ".join(map(str, args)))
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    # --windowed：不弹黑色命令行窗口；--collect-all：pywebview / pythonnet 带着自己的原生组件，必须整包收进去
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "DailyPrison",
         "--icon", "ui/img/icon.ico", "--add-data", "ui;ui",
         "--collect-all", "webview", "--collect-all", "pythonnet", "--collect-all", "clr_loader",
         "--hidden-import", "keyring.backends.Windows", "--hidden-import", "win32ctypes.pywin32.win32cred",
         "--hidden-import", "pystray._win32", "app.py"])
    PKG.mkdir(parents=True)
    shutil.copytree(DIST / "DailyPrison", PKG / "DailyPrison")
    for f in (ROOT / "installer").iterdir():
        shutil.copy2(f, PKG / f.name)
    (PKG / "version.txt").write_text(VERSION + "\n", "utf-8")
    zip_path = shutil.make_archive(str(DIST / f"日报越狱-安装包-{VERSION}"), "zip", DIST, PKG.name)
    print(f"\n完成：{zip_path}（{Path(zip_path).stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
