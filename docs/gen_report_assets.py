"""Generate PNG assets for the Word report:
- terminal.png : renders the agent mission log like a terminal screenshot
- arch.png     : system architecture diagram
Run: /home/pc/miniconda3/envs/unitree_sim_env/bin/python docs/gen_report_assets.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_assets")
os.makedirs(OUT, exist_ok=True)

CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
CJK_B = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def font(path, size, index=2):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        return ImageFont.truetype(path, size)


# ---------------------------------------------------------------- terminal
def terminal_png(log_path="/tmp/mission_demo2.log"):
    lines = []
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip()
            if ln.startswith("> ") or ln.startswith("status:") or ln.startswith("steps:") or ln.startswith("report:"):
                lines.append(ln[:110])
    title = "Terminal - MOBILE_MANIP_BACKEND=isaac python3 -m agent.execution.cli"
    pad, lh = 18, 30
    w = 1180
    h = pad * 2 + 46 + lh * (len(lines) + 1)
    img = Image.new("RGB", (w, h), (18, 18, 22))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, w - 5, h - 5], 10, outline=(70, 70, 80), width=2)
    d.rectangle([5, 5, w - 6, 44], fill=(45, 45, 52))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([14 + i * 22, 14, 30 + i * 22, 30], fill=c)
    d.text((w // 2 - 330, 14), title, font=font(MONO, 15), fill=(160, 160, 170))
    f = font(MONO, 17)
    y = 58
    for ln in lines:
        col = (80, 210, 100) if ln.startswith("> step") else (200, 200, 205)
        if ln.startswith("status:"):
            col = (255, 200, 80)
        d.text((pad, y), ln, font=f, fill=col)
        y += lh
    img.save(os.path.join(OUT, "terminal.png"))
    print("terminal.png", img.size)


# ------------------------------------------------------------- architecture
BOX = dict()
def box(d, xy, text, fill, outline, f, sub=None, sub_f=None):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, 12, fill=fill, outline=outline, width=3)
    lines = text.split("\n")
    ty = y0 + ((y1 - y0) - len(lines) * 26 - (18 if sub else 0)) / 2
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text((x0 + (x1 - x0 - tw) / 2, ty), ln, font=f, fill=(20, 20, 30))
        ty += 26
    if sub:
        for ln in sub.split("\n"):
            tw = d.textlength(ln, font=sub_f)
            d.text((x0 + (x1 - x0 - tw) / 2, ty + 4), ln, font=sub_f, fill=(70, 75, 90))
            ty += 20


def arrow(d, x0, y0, x1, y1, label=None, f=None, color=(40, 60, 120)):
    d.line([x0, y0, x1, y1], fill=color, width=3)
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    L = 12
    for a in (ang + 2.6, ang - 2.6):
        d.line([x1, y1, x1 + L * math.cos(a), y1 + L * math.sin(a)], fill=color, width=3)
    if label:
        tw = d.textlength(label, font=f)
        d.text(((x0 + x1) / 2 - tw / 2, (y0 + y1) / 2 - 22), label, font=f, fill=color)


def arch_png():
    W, H = 1280, 980
    img = Image.new("RGB", (W, H), (250, 250, 253))
    d = ImageDraw.Draw(img)
    f_t = font(CJK_B, 30)
    f = font(CJK, 20)
    f_s = font(CJK, 16)
    f_m = font(MONO, 15)
    d.text((W // 2 - 260, 22), "Isaac Sim G1 Agent 系统架构", font=f_t, fill=(15, 20, 40))

    box(d, (60, 90, 400, 170), "用户指令\n(自然语言任务)", (215, 228, 250), (60, 90, 170), f)
    box(d, (500, 90, 900, 170), "agent.execution.cli\n规划-执行循环", (255, 230, 190), (190, 120, 30), f,
        "LLM (MiniMax) 逐步选工具 -> 执行 -> 读结果", f_s)
    arrow(d, 400, 130, 500, 130, "goal", f_m)

    box(d, (60, 230, 400, 330), "工具注册表\nTool Registry", (225, 240, 220), (60, 140, 70), f,
        "robot_get_status / nav_list_places\nnav_go_to_place / vla_run_skill\nvision_verify / slam_get_pose", f_s)
    arrow(d, 640, 170, 320, 230, "select+call", f_m)

    box(d, (500, 230, 900, 330), "执行资源\nIsaacSimBackend", (235, 220, 245), (110, 60, 160), f,
        "robot_runtime/isaac_sim.py\n能力 -> HTTP 端点映射 + 结果解析", f_s)
    arrow(d, 400, 280, 500, 280, "dispatch", f_m)

    box(d, (60, 400, 900, 470), "HTTP/JSON 桥  http://127.0.0.1:8765", (245, 245, 250), (90, 90, 110), f,
        "GET /pose /places /world /camera /video    POST /navigate /vla /record", f_s)
    arrow(d, 700, 330, 480, 400, "curl/urllib", f_m)

    box(d, (60, 540, 460, 660), "导航\nnav_go_to_place", (210, 235, 245), (40, 110, 150), f,
        "costmap + 动态障碍 -> A* 路径\n纯跟踪限速 (clearance 缩放 vx)\n可选 ISAAC_NAV_NOISE/DRIFT 位姿噪声", f_s)
    box(d, (500, 540, 900, 660), "抓取/技能\nvla_run_skill", (250, 225, 215), (170, 80, 40), f,
        "开门: 铰链 prim 旋转插值\n取放: 苹果 prim 关键点插值\n手臂: ArticulationAction PD 关节动画", f_s)
    box(d, (60, 720, 460, 820), "视觉核验\nvision_verify", (220, 245, 235), (30, 140, 110), f,
        "相机帧 -> MiniMax VLM 判问\n失败回退像素启发式", f_s)
    box(d, (500, 720, 900, 820), "观测/录制\nGET /camera  POST /record", (235, 235, 240), (100, 100, 120), f,
        "Replicator 双机位 (跟拍+全身)\nJPEG 缓冲 -> ffmpeg -> MP4", f_s)

    # dark sim box drawn manually (light text)
    d.rounded_rectangle((960, 400, 1220, 660), 12, fill=(30, 35, 50), outline=(80, 90, 120), width=3)
    d.text((975, 435), "Isaac Sim 4.5\n+ internutopia", font=f, fill=(235, 240, 250))
    for i, ln in enumerate(["GRScenes 房间 USD", "Unitree G1 (底盘+双臂)", "240Hz 物理步进"]):
        tw = d.textlength(ln, font=f_s)
        d.text((960 + (260 - tw) / 2, 555 + i * 28), ln, font=f_s, fill=(195, 205, 225))

    arrow(d, 480, 420, 400, 540, "navigate", f_m)
    arrow(d, 560, 470, 700, 540, "vla", f_m)
    arrow(d, 480, 460, 300, 720, "camera+q", f_m)
    arrow(d, 900, 470, 960, 480, None, f_m)
    arrow(d, 460, 600, 960, 570, None, f_m)
    arrow(d, 460, 770, 960, 620, None, f_m)
    arrow(d, 900, 780, 960, 660, None, f_m)

    img.save(os.path.join(OUT, "arch.png"))
    print("arch.png", img.size)


if __name__ == "__main__":
    terminal_png()
    arch_png()
