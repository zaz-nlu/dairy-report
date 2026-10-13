"""界面自动化测试：python tests/ui_test/run.py

用 Edge 无头模式打开 ui_test.html（它加载 ui/ 里的真实代码 + 假后端 mock.js），脚本里真的点击、输入、等待，
把每项检查的 PASS/FAIL 打印出来。不需要 Python 后端，也不需要装任何依赖，只要电脑上有 Edge。
改了 ui/ 里的任何东西，都应该跑一遍这个。
"""
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
CANDIDATES = [os.environ.get("EDGE", ""), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
edge = next((p for p in CANDIDATES if p and Path(p).exists()), None)
if not edge:
    sys.exit("没找到 Edge（msedge.exe）。装了的话设置环境变量 EDGE 指向它。")

budget = sys.argv[1] if len(sys.argv) > 1 else "300000"   # 虚拟时间预算（毫秒）：测试里的等待不会真的花这么久
with tempfile.TemporaryDirectory() as profile:              # 独立的浏览器配置，不碰用户自己的 Edge
    r = subprocess.run([edge, "--headless=new", "--disable-gpu", "--allow-file-access-from-files", f"--user-data-dir={profile}",
                        "--window-size=1000,772", f"--virtual-time-budget={budget}", "--dump-dom",
                        (HERE / "ui_test.html").as_uri() + "?mock&scenario=calm"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=280)
m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
if not m:
    sys.exit("（没有输出：脚本没跑完或页面报错）\n" + r.stdout[:800])
report = html.unescape(m.group(1))
print(report)
sys.exit(1 if "\nFAIL" in "\n" + report else 0)
