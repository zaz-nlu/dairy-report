"""入口：pywebview 窗口 + pystray 托盘 + 调度线程。python app.py [--tray]（--tray = 开机自启时只进托盘）"""
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pystray
import webview
from PIL import Image

import config
from bridge import Api

PORT = int(os.environ.get("DAILY_PRISON_PORT", 47561))  # 单实例锁：占位 + 接收"唤起窗口"。环境变量只给测试用（同时开两个实例）
log = logging.getLogger("daily-prison")


def resource(rel):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / rel


def single_instance():
    """抢到端口 = 第一个实例；抢不到就通知老实例把窗口弹出来，然后退出（双开会导致重复提交）"""
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", PORT))
        sock.listen()
        return sock
    except OSError:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=2).close()
        except OSError:
            pass
        sys.exit(0)


def main():
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=config.APP_DIR / "app.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if sys.stdout is None or sys.stderr is None:  # 打包成无控制台程序后没有 stdout：任何 print 都会报错，先接到空设备上
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # 没控制台的程序出了错，用户什么都看不到：未捕获的异常（主线程 / 子线程）一律写进日志，朋友电脑上排错全靠它
    sys.excepthook = lambda *e: log.critical("未捕获的异常", exc_info=e)
    threading.excepthook = lambda a: log.critical("线程里未捕获的异常 %s", a.thread, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    sock = single_instance()
    api = Api()
    window = webview.create_window("日报越狱", str(resource("ui/index.html")), js_api=api,
                                   width=1000, height=680, min_size=(860, 600), hidden="--tray" in sys.argv)
    quitting = False

    def show():
        window.show()
        window.restore()

    def quit_app():
        nonlocal quitting
        quitting = True
        icon.stop()
        window.destroy()

    def on_closing():
        if not quitting:  # 关窗 = 进托盘，不退出
            window.hide()
            return False

    def push(event):
        try:
            window.evaluate_js(f"window.onBackendEvent && window.onBackendEvent({json.dumps(event, ensure_ascii=False)})")
        except Exception:
            pass  # 页面还没加载好

    def listen():  # 第二个实例连进来 = 唤起窗口
        while True:
            sock.accept()[0].close()
            show()

    def loop():
        while True:
            try:
                api.tick()
                icon.title = api._tray_title()
            except Exception:
                log.exception("调度出错")
            time.sleep(5 if api._pending else 30)  # 确认倒计时进行中，查得勤一点，不然 60 秒会拖成 90 秒

    icon = pystray.Icon("daily-prison", Image.open(resource("ui/img/icon.png")), "日报越狱", menu=pystray.Menu(
        pystray.MenuItem("打开", show, default=True),
        pystray.MenuItem("立即搜身", lambda: threading.Thread(target=api._safe, args=(api.collect_now,)).start()),
        pystray.MenuItem("签字画押（立即提交）", lambda: threading.Thread(target=api.submit_now).start()),
        pystray.MenuItem("保外就医（退出）", quit_app)))
    window.events.closing += on_closing
    api._notify_cb = lambda title, message: icon.notify(message, title)
    api._push_cb, api._show_cb, api._hide_cb, api._quit_cb = push, show, window.hide, quit_app

    icon.run_detached()
    threading.Thread(target=listen, daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    log.info("启动（%s，Python %s）", "打包版" if getattr(sys, "frozen", False) else "源码", sys.version.split()[0])
    webview.start()


if __name__ == "__main__":
    main()
