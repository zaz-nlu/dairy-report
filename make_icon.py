"""生成手铐图标：python make_icon.py → ui/img/icon.png + icon.ico（exe、安装包、托盘共用）"""
from pathlib import Path
from PIL import Image, ImageDraw

S = 1024  # 大画布绘制再缩小，靠缩放抗锯齿
BLACK, ORANGE, STEEL, SHINE = "#1a1a1a", "#ff7a00", "#c9ced6", "#ffffff"


def ring(d, cx, cy, r, w):
    """一只手铐圈：黑外描边 + 钢色圈 + 黑内描边，中间透出底色"""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLACK)
    d.ellipse((cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22), fill=STEEL)
    d.ellipse((cx - r + w, cy - r + w, cx + r - w, cy + r - w), fill=BLACK)
    d.ellipse((cx - r + w + 22, cy - r + w + 22, cx + r - w - 22, cy + r - w - 22), fill=ORANGE)
    d.arc((cx - r + 44, cy - r + 44, cx + r - 44, cy + r - 44), 200, 250, fill=SHINE, width=18)


def lockbox(d, cx, top):
    d.rounded_rectangle((cx - 70, top, cx + 70, top + 120), 18, fill=STEEL, outline=BLACK, width=22)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 漫画风底板：硬投影 + 粗描边圆角方块
    d.rounded_rectangle((60, 60, 1000, 1000), 170, fill=BLACK)
    d.rounded_rectangle((24, 24, 964, 964), 170, fill=ORANGE, outline=BLACK, width=30)
    # 链子：三节椭圆环，从左锁盒连到右锁盒
    for x0, y0, x1, y1 in [(300, 250, 450, 360), (420, 210, 580, 320), (550, 250, 700, 360)]:
        d.ellipse((x0, y0, x1, y1), outline=BLACK, width=46)
        d.ellipse((x0 + 12, y0 + 12, x1 - 12, y1 - 12), outline=STEEL, width=20)
    lockbox(d, 300, 320)
    lockbox(d, 700, 320)
    ring(d, 300, 640, 210, 92)
    ring(d, 700, 640, 210, 92)
    lockbox(d, 300, 320)  # 锁盒压在圈上面
    lockbox(d, 700, 320)

    out = Path(__file__).parent / "ui" / "img"
    out.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
