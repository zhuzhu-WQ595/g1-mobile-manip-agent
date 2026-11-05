"""Build the Word project report for the Isaac Sim G1 agent demo.
Run: /home/pc/miniconda3/envs/unitree_sim_env/bin/python docs/gen_report_docx.py
"""
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "report_assets")
OUT = os.path.join(HERE, "IsaacSim_G1_Agent_项目演示报告.docx")

doc = Document()

# 全局中文字体
style = doc.styles["Normal"]
style.font.name = "Noto Sans CJK SC"
style.font.size = Pt(11)


def h(text, level=1):
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x2A, 0x4A)
    return p


def para(text, bold=False, size=11, color=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    return p


def bullet(text):
    return doc.add_paragraph(text, style="List Bullet")


def pic(fname, width_cm=16.5, caption=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(os.path.join(ASSETS, fname), width=Cm(width_cm))
    if caption:
        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = c.add_run(caption)
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)


def code(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.name = "DejaVu Sans Mono"
    r.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.8)


# ============================================================ 封面/标题
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("\nIsaac Sim G1 移动操作 Agent\n项目演示报告")
r.bold = True
r.font.size = Pt(26)

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = sub.add_run("自然语言任务 · 规划-执行循环 · 导航/抓取技能 · VLM 视觉核验 · 双视角视频录制")
r.font.size = Pt(12)
r.font.color.rgb = RGBColor(0x55, 0x55, 0x66)

m = doc.add_paragraph()
m.alignment = WD_ALIGN_PARAGRAPH.CENTER
m.add_run("2026-11-05 · 场景 GRScenes MWBGLK_Q8 · 机器人 Unitree G1").font.size = Pt(10)
doc.add_page_break()

# ============================================================ 1 概述
h("1. 项目概述")
para("本项目实现了一个跑在 Isaac Sim 4.5(internutopia 框架 + GRScenes 家居场景）上的移动操作智能体。"
     "用户用自然语言下达任务，例如 “Go to the kitchen, open the fridge, pick the apple, "
     "carry it to the dining table and place it, then return home”,Agent 自行规划、"
     "逐步调用工具执行，并通过视觉语言模型（VLM）核验关键结果。")
bullet("执行器：Unitree G1 人形机器人（移动底盘 + 双臂），240Hz 物理仿真")
bullet("场景：GRScenes-100 家居房间（厨房/餐桌/冰箱等），占用栅格地图预生成")
bullet("大模型：MiniMax（任务规划）+ MiniMax VLM（视觉核验）")
bullet("观测：双机位 Replicator 相机（近距跟拍 + 全身 3/4 视角），全程录制 MP4")

# ============================================================ 2 架构
h("2. 系统架构")
para("整体分四层：Agent 决策层（规划-执行循环）、工具/执行资源层、HTTP 桥接层、Isaac Sim 仿真层。"
     "各层间单向依赖，仿真细节对 Agent 完全透明——Agent 只看到语义化的工具和 JSON 结果。")
pic("arch.png", 16.5, "图 1 系统架构：LLM 逐步选工具 → 执行资源 → HTTP 桥 → Isaac Sim")
doc.add_paragraph()
h("2.1 决策层：agent.execution.cli", 2)
para("命令行入口加载目标 → 询问 LLM 下一步 → 执行工具 → 把结果回灌给模型 → 循环直至完成或步数耗尽。"
     "内置两项保护：重复动作保护（同签名连续调用截停）、失败熔断（同一错误反复出现即阻塞）。")
h("2.2 执行资源：IsaacSimBackend(robot_runtime/isaac_sim.py)", 2)
para("把抽象能力映射为桥的 HTTP 端点，并解析返回值成 Agent 可读的 JSON。"
     "MOBILE_MANIP_BACKEND=isaac 时启用；另有 Mock 后端供离线测试。")
h("2.3 桥接层：scripts/isaac_bridge.py", 2)
para("与 Isaac Sim 同进程运行的轻量 HTTP 服务（端口 8765)，在物理主循环里排队执行请求。"
     "所有仿真读写（位姿、prim 变换、关节、渲染）都集中在这里，Agent 端零 Isaac 依赖。")

# ============================================================ 3 调用链
h("3. Agent 如何调用导航与抓取")
h("3.1 工具清单", 2)
tbl = doc.add_table(rows=7, cols=3)
tbl.style = "Light Grid Accent 1"
rows = [
    ("工具", "对应 HTTP 端点", "作用"),
    ("robot_get_status", "GET /pose", "位姿、所在地点、持物、冰箱门状态"),
    ("nav_list_places", "GET /places", "语义地点表 kitchen/dining_table/home"),
    ("slam_get_pose", "GET /pose", "定位读数（含可配置的估计噪声）"),
    ("nav_go_to_place", "POST /navigate", "代价地图 A* 规划 + 纯跟踪，动态避障"),
    ("vla_run_skill", "POST /vla", "脚本化操作技能：开关冰箱、取/放苹果"),
    ("vision_verify", "GET /camera + VLM", "相机帧交给 MiniMax VLM 问答核验"),
]
for i, (a, b, c) in enumerate(rows):
    cells = tbl.rows[i].cells
    for j, v in enumerate((a, b, c)):
        cells[j].text = v
        if i == 0:
            cells[j].paragraphs[0].runs[0].bold = True

doc.add_paragraph()
h("3.2 导航链路", 2)
para("nav_go_to_place 收到目标地名 → 查语义地点坐标 → 在占用栅格 costmap 上跑 A*（冰箱门等动态障碍"
     "实时投影进 BLOCKED_DYN 层）→ 纯跟踪循环：向路径点转向、按局部 clearance 缩放 vx 限速、"
     "卡死时局部重规划。位姿可通过 ISAAC_NAV_NOISE / ISAAC_NAV_DRIFT 注入抖动和随机游走漂移，"
     "用于验证导航对定位误差的鲁棒性。")
pic("room_map.png", 15.5, "图 3 房间占用地图（MWBGLK_Q8)：黑=障碍，白=可走，彩色标记为语义地点（kitchen 右下、"
                          "dining_table 中部、home 青色 G1 起点）")
h("3.3 抓取/技能链路", 2)
para("vla_run_skill 按指令关键词分派脚本化技能，技能内部逐帧调用 env.step 驱动仿真：")
bullet("开关冰箱：验证在 FRIDGE_FRONT 可达范围内 → 右臂前伸 → 铰链 prim(Group_356/361)"
       "绕轴插值旋转 ±100° → 收回手臂；同步更新动态障碍层")
bullet("取苹果：确认冰箱已开且可达 → 双臂前伸探入 → 苹果 prim 从 APPLE_REST 线性插值到"
       "持物点 CARRY_OFFSET(身前 0.28m、高 0.95m)→ 双臂收拢成持物姿势并保持")
bullet("放苹果：确认在餐桌可达 → 双臂下放到桌高 → 苹果插值到 TABLE_TARGET → 手臂归零收拢")
para("手臂动画：通过 env.runner → robot.articulation 取得 G1 关节，每步用 "
     "ArticulationAction 以 PD 关节目标驱动（每步趋近 12%)，肩/肘/腕关键帧随技能时序播放，"
     "搬运期间持物姿态持续保持。", bold=False)

# ============================================================ 4 成功检验
h("4. 任务成功与否的检验")
para("采用三层校验，而不是只看动作有没有发出去：")
bullet("执行层回执：每个技能返回结构化结果（ok/error/holding/fridge_open),"
       "not_reachable、not_holding、occluded 等失败被显式上报")
bullet("视觉核验 vision_verify：取当前相机帧发给 MiniMax VLM 提问"
       "（如 “Is the apple placed on the dining table, and is the robot's gripper empty?”),"
       "VLM 返回空时重试一次后回退到本地像素启发式")
bullet("世界态终检：GET /world 直读仿真真相（fridge_open / holding / 苹果位姿）,"
       "SLAM 位姿确认终点 home")

# ============================================================ 5 执行实录
h("5. 任务执行实录")
para("任务：Go to the kitchen, open the fridge, pick the apple, carry it to the dining_table "
     "and place it, then return home。Agent 共执行 12 步：")
pic("terminal.png", 16.0, "图 2 Agent 终端执行日志(12 步)")
para("step 1-3 读取状态与地点表；step 4 导航至厨房；step 5-6 开门、取果；"
     "step 7-8 导航至餐桌并放置；step 9 用 VLM 核验放置结果；step 10-12 返程并终检。"
     "第 12 步后模型再次重复 home 导航，被重复动作保护截停——此时苹果已放妥、"
     "冰箱门保持开启，任务主体目标全部达成。")

# ============================================================ 6 演示截图
h("6. 仿真画面实录")
para("全程由桥内 Replicator 双机位录制：左图为近距跟拍视角，右图为全身 3/4 视角"
     "（后 2.2m、右 1.1m、高 2.0m 跟拍）。成片 /tmp/isaac_rec.mp4,1193 帧 / 238s / 25.4MB。")
for fig_n, (ts, cap) in enumerate([(8, "任务起点：机器人位于 home"), (45, "导航前往厨房途中"),
                (100, "开冰箱：右臂前伸，门体旋开"), (130, "取苹果：双臂探入箱内"),
                (160, "搬运：双臂持果（红球）走向餐桌"), (185, "放置：双臂下放至桌面"),
                (215, "返程：苹果留在桌上")], start=4):
    pic(f"seg_{ts}s.png", 16.5, f"图 {fig_n}  {cap}")

# ============================================================ 7 复现
h("7. 环境与复现命令")
para("依赖：Isaac Sim 4.5 + internutopia + unitree_sim_env(python3.10)；桥需场景 USD 与地图前缀。")
code("""# 启动桥(headless + 内存保护)
INTERNUTOPIA_ASSETS_PATH=/home/pc/assets/GRScenes \\
MDL_SYSTEM_PATH=$M MDL_USER_PATH=$M MALLOC_ARENA_MAX=4 \\
python scripts/isaac_bridge.py --scene <scene.usd> --map maps/MWBGLK_Q8

# 录制 + 任务
curl -X POST localhost:8765/record -d '{"cmd":"start","fps":5}'
MOBILE_MANIP_BACKEND=isaac python3 -m agent.execution.cli --mobile-manip \\
  --max-steps 18 --output reports/mission.json "<任务描述>"
curl -X POST localhost:8765/record -d '{"cmd":"stop"}'   # -> /tmp/isaac_rec.mp4""")

doc.save(OUT)
print("saved:", OUT, os.path.getsize(OUT) / 1048576, "MB")
