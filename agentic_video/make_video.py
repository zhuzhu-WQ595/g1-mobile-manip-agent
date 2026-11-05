#!/usr/bin/env python3
"""生成《具身智能体 Agentic Robotics》讲解视频.

流程: PIL 渲染幻灯片 -> edge-tts 生成中文旁白 -> ffmpeg 合成 + 烧录字幕.
运行: python make_video.py
依赖: pillow, edge-tts, ffmpeg(带 libass), Noto Sans CJK 字体.
"""
import asyncio
import glob
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
VOICE = "zh-CN-YunjianNeural"
RATE = "+8%"
LEAD = 0.35      # 每段开头的静音(秒)
TAIL = 0.70      # 每段结尾的静音(秒)
ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
FINAL = os.path.join(ROOT, "agentic_robotics_explainer.mp4")
REPO_URL = "github.com/w-xb/awesome-agentic-robotics"

BG = (15, 23, 42)        # slate-900
PANEL = (30, 41, 59)     # slate-800
TITLE = (248, 250, 252)
BODY = (203, 213, 225)
MUTED = (100, 116, 139)
ACCENT = (56, 189, 248)  # sky-400
C_AGENT = (56, 189, 248)
C_HARNESS = (167, 139, 250)
C_VLA = (52, 211, 153)
C_WORLD = (251, 191, 36)


def _pick_sc_index(path):
    """在 .ttc 集合中找到 Noto Sans CJK SC 的 face 索引."""
    for i in range(12):
        try:
            f = ImageFont.truetype(path, 20, index=i)
        except OSError:
            break
        if "SC" in " ".join(f.getname()).split():
            return i
    return 0


def _find_font(names):
    for pat in names:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    raise FileNotFoundError(names)


_REG_PATH = _find_font(["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                        "/usr/share/fonts/**/*CJK*Regular*", "/usr/share/fonts/**/*.ttc"])
_BOLD_PATH = _find_font(["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                         "/usr/share/fonts/**/*CJK*Bold*", "/usr/share/fonts/**/*.ttc"])
_REG_IDX = _pick_sc_index(_REG_PATH)
_BOLD_IDX = _pick_sc_index(_BOLD_PATH)


def F(size, bold=False):
    return ImageFont.truetype(_BOLD_PATH if bold else _REG_PATH, size,
                              index=_BOLD_IDX if bold else _REG_IDX)


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if ch == "\n" or draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = "" if ch == "\n" else ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def arrow_down(d, x, y0, y1, color=MUTED, w=4):
    d.line([x, y0, x, y1 - 8], fill=color, width=w)
    d.polygon([(x - 8, y1 - 10), (x + 8, y1 - 10), (x, y1)], fill=color)


def base_frame(idx, total, kicker):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.text((70, 26), kicker, font=F(20, True), fill=ACCENT)
    page = f"{idx:02d} / {total:02d}"
    d.text((W - 70 - d.textlength(page, font=F(20)), 26), page, font=F(20), fill=MUTED)
    d.text((70, H - 34), REPO_URL, font=F(16), fill=MUTED)
    return img, d


def draw_title(d, title):
    d.text((70, 66), title, font=F(42, True), fill=TITLE)
    tw = d.textlength(title, font=F(42, True))
    d.rectangle([70, 122, 70 + min(tw, 220), 126], fill=ACCENT)


def draw_bullets(d, bullets, y0=158, size=27, gap=18, max_w=1120):
    f_txt = F(size)
    lh = int(size * 1.5)
    y = y0
    r = int(size * 0.24)
    for b in bullets:
        d.ellipse([76, y + int(size * 0.55) - r, 76 + 2 * r, y + int(size * 0.55) + r],
                  fill=ACCENT)
        if isinstance(b, tuple):  # (head, desc)
            head, desc = b
            d.text((104, y), head, font=F(size, True), fill=TITLE)
            hw = d.textlength(head, font=F(size, True))
            d.text((104 + hw + 14, y + 2), desc, font=F(size - 2), fill=BODY)
            y += lh + gap
        else:
            for j, line in enumerate(wrap(d, b, f_txt, max_w)):
                d.text((104, y), line, font=f_txt, fill=BODY)
                y += lh
            y += gap
    return y


# ---------------------------------------------------------------- 幻灯片定义
SLIDES = [
    dict(layout="cover", kicker="EXPLAINER",
         title="具身智能体", sub="AGENTIC ROBOTICS",
         desc="会推理、记忆、规划、使用工具、验证执行、\n从失败中恢复并自我进化的物理智能体",
         foot="基于 GitHub 精选论文清单  Awesome Agentic Robotics",
         narration="大家好。这期视频我们讲解具身智能体，英文叫 Agentic Robotics。"
                   "内容基于 GitHub 上的精选论文清单 Awesome Agentic Robotics，"
                   "它系统梳理了这个新兴方向的核心概念、技术栈和代表工作。"),
    dict(layout="bullets", kicker="DEFINITION", title="什么是 Agentic Robotics",
         bullets=[("能力中心定义：", "看能力，不看标签"),
                  "感知并维持任务状态 · 记忆 · 规划未来后果",
                  "调用技能 / 工具 · 验证执行 · 失败恢复",
                  "在物理安全约束下行动 · 从具身经验中改进",
                  "具身智能是一条连续谱，而非二元判定"],
         narration="仓库采用能力中心的定义：一个机器人系统越能感知并维持任务状态、利用记忆、"
                   "对未来后果进行规划、调用技能和工具、验证执行结果、从失败中恢复，"
                   "并在物理安全约束下行动，它就越具有智能体性。"
                   "所以具身智能不是非黑即白的标签，而是一条连续谱。"),
    dict(layout="bullets", kicker="VS SOFTWARE AGENTS", title="与软件智能体的本质区别",
         bullets=[("软件 Agent：", "规划 / 记忆 / 反思 → 文本 + API"),
                  ("机器人 Agent：", "动态、部分可观测的物理世界"),
                  "时空记忆 · 动作条件的世界模型",
                  "落地的技能接口 · 执行监控 · 失败归因",
                  "恢复策略 · 安全包络（safety envelope）"],
         narration="和纯软件智能体不同，软件智能体的规划、记忆和反思大多通过文本和 API 完成；"
                   "而机器人必须在动态、部分可观测的物理世界中行动。"
                   "因此它的智能不仅依赖外部的大模型循环，还依赖具身机制："
                   "时空记忆、动作条件的世界模型、落地的技能接口、执行监控、"
                   "失败归因、恢复策略和安全包络。"),
    dict(layout="stack", kicker="CORE ARCHITECTURE", title="核心架构：Agent–Harness–VLA 闭环栈",
         narration="仓库的组织视角是一个三层闭环栈。最上层是 Agent 规划器，负责推理、"
                   "任务分解和维护任务状态；中间是 Harness 运行时，负责记忆、工具、路由、"
                   "验证、恢复和安全；最下面是 VLA 策略，把感知直接映射为物理动作；"
                   "物理世界返回观测、结果和失败。被验证过的持久化更新跨回合积累，"
                   "就形成了自我进化。"),
    dict(layout="bullets", kicker="THREE ROLES", title="三层各管什么",
         bullets=[("Agent / Planner：", "做什么、为什么 → 任务分解·子目标·重规划"),
                  ("Harness / Runtime：", "组件如何协调 → 检查·路由·重试·恢复·约束"),
                  ("VLA / Policy：", "多模态上下文 → 可执行的物理动作"),
                  ("物理世界：", "提供证据 —— 观测、结果、失败")],
         narration="这个栈的价值在于分清三个常被混为一谈的问题：Agent 回答接下来做什么、"
                   "为什么；Harness 回答组件如何被协调、检查、重试、恢复和约束；"
                   "VLA 回答多模态上下文如何变成可执行的物理动作。"),
    dict(layout="cols", kicker="CAPABILITY MAP", title="能力地图：八个能力层",
         cols=[[("Agent 规划器", "任务分解·子目标·重规划"),
                ("Harness 运行时", "记忆/工具/验证/恢复编排"),
                ("Memory 具身记忆", "记住什么·如何检索与遗忘"),
                ("World Model 世界模型", "预测未来与动作后果")],
               [("VLA 策略", "多模态上下文→物理动作"),
                ("Skills 技能工具", "发现·表示·组合·调用"),
                ("Verifier 验证安全", "成功？安全？符合契约？"),
                ("物理世界 / 评测", "交互产生的证据与基准")]],
         narration="在这个栈之上，清单进一步划分出八个能力层：规划器、运行时、记忆、"
                   "世界模型、策略、技能工具、验证安全，以及物理世界与评测。"
                   "每一层都对应一组研究问题，也对应一种可以被持久改进的进化目标。"),
    dict(layout="works", kicker="PLANNING & REASONING", title="规划与推理",
         works=[("SayCan (2022)", "语义有用性 × 可供性可行性，开创落地范式"),
                ("Inner Monologue", "环境反馈·成功检测接入规划闭环"),
                ("ProgPrompt", "计划即程序：断言 + 恢复步骤"),
                ("VoxPoser", "语言 → 组合式 3D 价值图"),
                ("ThinkAct", "视觉潜空间中的强化规划"),
                ("趋势", "开环计划 → 反馈驱动的闭环重规划")],
         narration="规划方向从 2022 年的 SayCan 开始确立范式：用语言模型产出候选技能，"
                   "再用学到的可供性给物理可行性打分。Inner Monologue 把环境反馈、"
                   "成功检测和重规划接进循环。之后的 ProgPrompt 把计划写成带断言和"
                   "恢复步骤的程序，VoxPoser 生成三维价值图，ThinkAct 则在视觉潜空间里"
                   "做强化规划。"),
    dict(layout="works", kicker="EMBODIED MEMORY", title="具身记忆",
         works=[("AtlasVLA", "持久“世界-自我”状态，抗感知/进度遗忘"),
                ("MemoryVLA", "感知 + 认知双重记忆接入控制"),
                ("MEM", "多尺度观测-动作记忆"),
                ("3D-Mem / DynaMem", "显式三维场景记忆，在线更新"),
                ("MEMORA", "第一人称经验 → 可检索可编辑的动作记忆")],
         narration="长时程任务最大的敌人是遗忘。AtlasVLA 维护持久的世界-自我状态来追踪"
                   "空间上下文和任务进度；MemoryVLA 把感知记忆和认知记忆同时接入控制；"
                   "MEM 构建多尺度记忆；3D-Mem 和 DynaMem 维护显式的空间语义场景记忆；"
                   "MEMORA 则把第一人称视频经验提炼成可检索、可编辑的动作记忆。"),
    dict(layout="works", kicker="WORLD MODELS", title="世界模型",
         works=[("V-JEPA 2", "大规模自监督视频预测表征"),
                ("τ_0-WM", "动作生成·未来预测·候选评估·仿真校正一体"),
                ("WAM 系列", "世界-动作模型成为独立研究方向"),
                ("PointWorld", "3D 点云空间中的预测建模"),
                ("用途", "想象未来 · 评估候选 · 内部规划")],
         narration="世界模型让机器人能在行动前先想象后果。V-JEPA 2 用大规模自监督视频"
                   "学习预测表征；τ_0-WM 把动作生成、未来视频预测、候选评估和仿真校正"
                   "统一在一个模型里；世界-动作模型 WAM 正在成为独立方向；"
                   "PointWorld 把预测扩展到三维点云空间。"),
    dict(layout="works", kicker="AGENTIC VLA", title="Agentic VLA：策略本身的智能体化",
         works=[("π0.5", "异构协同训练 → 开放世界泛化"),
                ("Gemini Robotics 1.5", "显式思考 + 跨本体动作迁移"),
                ("Hi Robot", "开放式指令 → 语义子目标 → 底层动作"),
                ("Harness VLA", "冻结 VLA = 可重试操作原语"),
                ("Agentic Robot", "Plan–Execute–Verify 三环结构")],
         narration="VLA 本身也在智能体化。π0.5 用异构协同训练实现开放世界泛化；"
                   "Gemini Robotics 1.5 把显式思考和跨本体动作迁移放进通用策略；"
                   "Hi Robot 做分层指令拆解；Harness VLA 把冻结的 VLA 包装成可重试的"
                   "操作原语，由上层智能体负责验证和恢复；Agentic Robot 则提出经典的"
                   "计划-执行-验证三环结构。"),
    dict(layout="works", kicker="VERIFICATION & SAFETY", title="验证与安全",
         works=[("VLM as Success Detector", "通用视觉语言模型即成功检测器"),
                ("Pre-VLA", "动作执行前的预防性运行时验证"),
                ("Speculative Verification", "开环规划 + 闭环投机验证"),
                ("MANIGUARD", "过程级安全评测基准（非只看结果）"),
                ("治理方向", "同意链退化 · 运行时政策约束")],
         narration="可靠性的另一半是验证。从用通用视觉语言模型做成功检测，"
                   "到 Pre-VLA 在动作执行前做预防性验证，再到 MANIGUARD 对操作过程"
                   "而不是最终结果做安全评测。治理方向甚至开始研究具身多智能体系统中的"
                   "同意链退化和运行时政策约束。"),
    dict(layout="works", kicker="FAILURE & RECOVERY", title="失败检测与恢复",
         works=[("SAFE", "跨任务共享的失败检测器"),
                ("FPC-VLA", "监督模型预测失败、提前纠偏"),
                ("FailSafe-VLM", "解释失败原因 + 生成恢复策略"),
                ("CycleVLA", "不确定子任务回溯 + 安全重选"),
                ("原则", "失败不可避免 → 检测-归因-恢复闭环")],
         narration="失败不可避免，关键是闭环处理。SAFE 训练跨任务共享的失败检测器；"
                   "FPC-VLA 加一个监督模型在错误传播之前纠偏；FailSafe-VLM 能解释失败"
                   "原因并生成恢复策略；CycleVLA 主动识别不确定的子任务并回溯重选动作。"),
    dict(layout="works", kicker="SKILLS & TOOLS", title="技能学习与工具使用",
         works=[("Code as Policies", "语言模型 → 组合感知/控制的策略代码"),
                ("DeCo", "任务分解 + 技能组合 → 零样本泛化"),
                ("VLM Tool Use", "选择并使用未见过的物理工具"),
                ("ROS-LLM / RAI", "接入 ROS 的智能体工程框架")],
         narration="技能和工具是智能体能力的落脚点。Code as Policies 让语言模型直接生成"
                   "组合感知和控制接口的策略代码；DeCo 通过任务分解和技能组合实现零样本"
                   "泛化；还有工作让视觉语言模型选择并使用没见过的物理工具；"
                   "ROS-LLM 和 RAI 则提供接进 ROS 的工程框架。"),
    dict(layout="evolve", kicker="SELF-EVOLUTION", title="自我进化：清单最有特色的部分",
         narration="自我进化是这份清单最有特色的部分。判据很严格：一次改动必须经过验证、"
                   "持久保留、并且影响后续回合，才算进化；回合内的重规划和重试只算瞬时适应。"
                   "进化目标分六类：运行时、技能库、验证契约、策略数据、奖励目标和记忆上下文。"
                   "Zetta 冻结基座模型只进化运行时组件；Eureka 进化奖励函数；"
                   "RoboCat 是最早的真机策略自我改进案例。"),
    dict(layout="works", kicker="HORIZON & EVAL", title="长时程任务 · 导航 · 评测基建",
         works=[("长时程操作", "进度建模·技能链接·执行轨迹条件化"),
                ("具身导航", "空间记忆 + 零样本视觉语言导航"),
                ("LIBERO / CALVIN", "终身学习 / 长链条操作基准"),
                ("RoboCasa365", "大规模日常任务仿真框架"),
                ("Open X-Embodiment", "跨本体数据与 RT-X 模型基础")],
         narration="应用侧，长时程操作靠进度建模和技能链接维持任务状态；导航方向把空间"
                   "记忆和零样本视觉语言导航结合。支撑这一切的是评测基础设施："
                   "LIBERO 测终身学习，CALVIN 测长链条操作，RoboCasa365 提供大规模仿真"
                   "日常任务，Open X-Embodiment 奠定了跨本体数据基础。"),
    dict(layout="bullets", kicker="HOW TO USE", title="怎么用这份清单",
         bullets=[("入口：", "25 篇高信号论文 · 5 条阅读路线"),
                  "VLA 即工具 | 自我进化 | 分层推理",
                  "记忆与世界模型 | 规划·安全·评测",
                  ("归类规则：", "每篇按主要贡献只归一类"),
                  "被淘汰的相邻工作保留在 Extended Reading"],
         narration="使用建议：清单开头给出五条阅读路线共二十五篇高信号论文，按 VLA 即工具、"
                   "自我进化、分层推理、记忆世界模型、规划安全评测分组。每篇论文只按主要"
                   "贡献归类一次，次要能力写在描述里；被策展淘汰的工作保留在 "
                   "Extended Reading 中。"),
    dict(layout="end", kicker="TAKEAWAYS", title="总结",
         bullets=["具身智能是连续谱：单点突破与闭环系统都在地图上",
                  "长时程自主性 = 闭环协同，而不只是更大的 VLA",
                  "开放方向：跨层协同进化（cross-layer co-evolution）"],
         narration="总结三点：第一，具身智能是连续谱，单个组件的突破和完整的闭环系统都在"
                   "这张地图上。第二，可靠的长时程自主性越来越取决于推理、记忆、世界模型、"
                   "技能、验证、恢复、安全和底层控制如何作为一个闭环协同，而不只是把 "
                   "VLA 做得更大。第三，一个重要的开放方向是跨层协同进化，让各层联合进化，"
                   "同时保持兼容、安全和稳定的物理行为。仓库地址在屏幕上，感谢观看。"),
]


# ---------------------------------------------------------------- 各版式渲染
def render_cover(img, d, s):
    d.text((W // 2, 250), s["title"], font=F(84, True), fill=TITLE, anchor="mm")
    sub = s["sub"]
    sw = d.textlength(sub, font=F(34, True))
    d.text(((W - sw) / 2, 320), sub, font=F(34, True), fill=ACCENT)
    for i, line in enumerate(s["desc"].split("\n")):
        d.text((W // 2, 420 + i * 44), line, font=F(26), fill=BODY, anchor="mm")
    d.text((W // 2, 574), s["foot"], font=F(20), fill=MUTED, anchor="mm")
    d.rectangle([W // 2 - 60, 532, W // 2 + 60, 536], fill=ACCENT)


def render_stack(img, d, s):
    draw_title(d, s["title"])
    cx, bw = 560, 560
    boxes = [
        ("目标 / 人类意图", "", MUTED, 42),
        ("Agent / Planner", "推理 · 分解 · 任务状态", C_AGENT, 66),
        ("Harness / Runtime", "记忆·工具·路由·验证·恢复·安全", C_HARNESS, 66),
        ("VLA / Policy", "感知 → 动作的落地执行", C_VLA, 66),
        ("机器人 + 物理世界", "", C_WORLD, 54),
    ]
    ys = [150, 222, 314, 406, 492]
    for (label, sub, color, bh), y in zip(boxes, ys):
        d.rounded_rectangle([cx - bw // 2, y, cx + bw // 2, y + bh], 12,
                            fill=PANEL, outline=color, width=3)
        if sub:
            d.text((cx, y + bh // 2 - 14), label, font=F(26, True), fill=TITLE, anchor="mm")
            d.text((cx, y + bh // 2 + 16), sub, font=F(19), fill=color, anchor="mm")
        else:
            d.text((cx, y + bh // 2), label, font=F(24, True), fill=TITLE, anchor="mm")
    for i in range(len(boxes) - 1):
        arrow_down(d, cx, ys[i] + boxes[i][3], ys[i + 1], ACCENT)
    # 右侧反馈箭头
    fx = cx + bw // 2 + 60
    d.line([fx, 519, fx, 171], fill=C_WORLD, width=4)
    d.polygon([(fx - 8, 181), (fx + 8, 181), (fx, 169)], fill=C_WORLD)
    d.line([cx + bw // 2, 519, fx, 519], fill=C_WORLD, width=4)
    d.line([fx, 171, cx + bw // 2, 171], fill=C_WORLD, width=4)
    d.text((fx + 14, 340), "观测 · 结果", font=F(20), fill=C_WORLD)
    d.text((fx + 14, 372), "· 失败反馈", font=F(20), fill=C_WORLD)
    # 底部自我进化条
    d.rounded_rectangle([70, 578, W - 70, 632], 12, outline=ACCENT, width=2)
    d.text((W // 2, 605), "跨回合持久化、已验证的更新  →  自我进化（Self-Evolution）",
           font=F(24, True), fill=ACCENT, anchor="mm")


def render_cols(img, d, s):
    draw_title(d, s["title"])
    for ci, col in enumerate(s["cols"]):
        x = 70 + ci * 590
        y = 168
        for head, desc in col:
            d.rounded_rectangle([x, y, x + 550, y + 100], 12, fill=PANEL)
            d.rectangle([x, y, x + 6, y + 100], fill=ACCENT)
            d.text((x + 24, y + 16), head, font=F(25, True), fill=TITLE)
            d.text((x + 24, y + 56), desc, font=F(20), fill=BODY)
            y += 122


def render_works(img, d, s):
    draw_title(d, s["title"])
    y = 156
    for name, desc in s["works"]:
        d.rounded_rectangle([70, y, W - 70, y + 70], 10, fill=PANEL)
        d.text((94, y + 12), name, font=F(24, True), fill=ACCENT)
        nw = max(d.textlength(name, font=F(24, True)), 190)
        for j, line in enumerate(wrap(d, desc, F(21), W - 260 - nw)[:2]):
            d.text((110 + nw, y + 13 + j * 28), line, font=F(21), fill=BODY)
        y += 84


def render_evolve(img, d, s):
    draw_title(d, s["title"])
    d.rounded_rectangle([70, 158, W - 70, 232], 12, fill=PANEL, outline=ACCENT, width=2)
    d.text((94, 176), "判据：经验证 · 持久保留 · 影响未来回合", font=F(26, True), fill=TITLE)
    d.text((94, 246), "瞬时适应（重规划/重试/测试时搜索）≠ 进化", font=F(22), fill=MUTED)
    targets = ["harness/runtime", "skill/library", "contract/verifier",
               "policy/data", "objective/reward", "memory/context"]
    d.text((70, 300), "六大进化目标", font=F(24, True), fill=TITLE)
    for i, t in enumerate(targets):
        x, y = 70 + (i % 3) * 390, 344 + (i // 3) * 66
        d.rounded_rectangle([x, y, x + 360, y + 50], 10, outline=C_HARNESS, width=2)
        d.text((x + 180, y + 25), t, font=F(21, True), fill=BODY, anchor="mm")
    draw_bullets(d, [("Zetta：", "冻结基座 VLA + 编排器，只进化运行时批评器/恢复手册/工具"),
                     ("Eureka：", "进化奖励函数；RoboCat：真机策略自改进先驱")],
                 y0=500, size=24)


def render_end(img, d, s):
    draw_title(d, s["title"])
    draw_bullets(d, s["bullets"], y0=180, size=27, gap=22)
    d.rectangle([70, 560, W - 70, 564], fill=ACCENT)
    d.text((W // 2, 616), REPO_URL, font=F(30, True), fill=ACCENT, anchor="mm")


def render(idx, s, total):
    img, d = base_frame(idx, total, s["kicker"])
    lay = s["layout"]
    if lay == "cover":
        render_cover(img, d, s)
    elif lay == "stack":
        render_stack(img, d, s)
    elif lay == "cols":
        render_cols(img, d, s)
    elif lay == "works":
        render_works(img, d, s)
    elif lay == "evolve":
        render_evolve(img, d, s)
    elif lay == "end":
        render_end(img, d, s)
    else:
        draw_title(d, s["title"])
        draw_bullets(d, s["bullets"])
    return img


# ---------------------------------------------------------------- TTS / 合成
async def gen_audio(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(path)


def dur_of(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path])
    return float(out.strip())


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(map(str, cmd)))
        print(r.stdout[-2000:])
        print(r.stderr[-3000:])
        sys.exit(1)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    n = len(SLIDES)
    durs = []
    # 1) 渲染幻灯片
    for i, s in enumerate(SLIDES, 1):
        render(i, s, n).save(os.path.join(ASSETS, f"s{i:02d}.png"))
    print(f"[1/4] {n} 张幻灯片渲染完成")
    # 2) TTS
    async def all_tts():
        for i, s in enumerate(SLIDES, 1):
            p = os.path.join(ASSETS, f"a{i:02d}.mp3")
            if not os.path.exists(p):
                await gen_audio(s["narration"], p)
            print(f"  TTS {i}/{n}")
    asyncio.run(all_tts())
    print("[2/4] 旁白音频完成")
    # 3) 逐段合成 + 字幕计时
    srt, t = [], 0.0
    for i, s in enumerate(SLIDES, 1):
        ad = dur_of(os.path.join(ASSETS, f"a{i:02d}.mp3"))
        D = LEAD + ad + TAIL
        durs.append(D)
        fade = min(0.4, D / 4)
        vf = (f"fade=t=in:st=0:d={fade},fade=t=out:st={D - fade:.3f}:d={fade},"
              f"format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
             "-i", f"s{i:02d}.png", "-i", f"a{i:02d}.mp3",
             "-vf", vf, "-af", f"adelay={int(LEAD*1000)}|{int(LEAD*1000)},apad=whole_dur={D:.3f}",
             "-t", f"{D:.3f}", "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium",
             "-r", str(FPS), "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
             f"seg{i:02d}.mp4"], cwd=ASSETS)
        # 字幕：按句切分，时长 ∝ 字数
        sents = [x for x in re.split(r"(?<=[。！？；])", s["narration"]) if x.strip()]
        tot = max(sum(len(x) for x in sents), 1)
        cur = t + LEAD
        for x in sents:
            sd = ad * len(x) / tot
            srt.append((cur, cur + sd, x))
            cur += sd
        t += D
    print("[3/4] 分段视频完成")
    # 4) 写 SRT + concat + 烧录
    def ts(sec):
        h = int(sec // 3600); m = int(sec % 3600 // 60); s2 = sec % 60
        return f"{h:02d}:{m:02d}:{s2:06.3f}".replace(".", ",")
    with open(os.path.join(ASSETS, "subs.srt"), "w", encoding="utf-8") as f:
        for k, (a, b, txt) in enumerate(srt, 1):
            f.write(f"{k}\n{ts(a)} --> {ts(b)}\n{txt}\n\n")
    with open(os.path.join(ASSETS, "list.txt"), "w") as f:
        for i in range(1, n + 1):
            f.write(f"file 'seg{i:02d}.mp4'\n")
    has_ass = "subtitles" in subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-filters"], text=True)
    if has_ass:
        style = ("FontName=Noto Sans CJK SC,FontSize=22,PrimaryColour=&H00FFFFFF,"
                 "BackColour=&H78000000,BorderStyle=3,Outline=6,Shadow=0,"
                 "Alignment=2,MarginV=24")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
             "-vf", f"subtitles=subs.srt:force_style='{style}'",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", FINAL],
            cwd=ASSETS)
    else:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
             "-c", "copy", "-movflags", "+faststart", FINAL], cwd=ASSETS)
    print(f"[4/4] 完成: {FINAL}  总时长 {sum(durs):.0f}s")


if __name__ == "__main__":
    main()
