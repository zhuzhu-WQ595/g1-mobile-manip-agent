#!/usr/bin/env python3
"""Render a Markdown subset to PDF with CJK support via reportlab.

No pandoc/LaTeX required. Supports headings, paragraphs, fenced code blocks,
bullet and numbered lists, pipe tables, images, block quotes and rules.

Usage:
    python3 scripts/build_pdf.py docs/input.md docs/output.pdf
"""
from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Droid Sans Fallback covers CJK but contains no basic-Latin glyphs (its charset
# jumps from U+0020 straight to U+0E3F), while DejaVu has no CJK. Every text run
# is therefore split by script and rendered with the matching face.
CJK_FONT_PATH = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
LATIN_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
LATIN_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LATIN_ITALIC_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
MONO_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

CJK = "CJK"
BODY = "Latin"
MONO = "Mono"

CJK_RE = re.compile(
    r"[\u1100-\u11ff\u2e80-\u9fff\u3000-\u303f\u3040-\u30ff"
    r"\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]+"
)

ACCENT = colors.HexColor("#1a4f7a")
ACCENT_LIGHT = colors.HexColor("#2d7fb8")
CODE_BG = colors.HexColor("#f4f6f8")
CODE_BORDER = colors.HexColor("#d8dee4")
CODE_FG = colors.HexColor("#24292e")
INLINE_CODE_FG = colors.HexColor("#b31d28")
MUTED = colors.HexColor("#57606a")
RULE = colors.HexColor("#d0d7de")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 20 * mm
MARGIN_BOTTOM = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

CODE_FONT_SIZE = 7.6
CODE_CHAR_W = 0.6023 * CODE_FONT_SIZE
CODE_PAD = 6
CODE_MAX_CHARS = max(40, int((CONTENT_W - 2 * CODE_PAD - 4) / CODE_CHAR_W))


def _need(path: str, what: str) -> str:
    if not Path(path).exists():
        raise SystemExit(f"{what} font not found: {path}")
    return path


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(CJK, _need(CJK_FONT_PATH, "CJK")))
    pdfmetrics.registerFont(TTFont(BODY, _need(LATIN_FONT_PATH, "Latin")))
    pdfmetrics.registerFont(TTFont(BODY + "-Bold", _need(LATIN_BOLD_PATH, "Latin bold")))
    pdfmetrics.registerFont(TTFont(BODY + "-Italic", _need(LATIN_ITALIC_PATH, "Latin italic")))
    pdfmetrics.registerFont(TTFont(MONO, _need(MONO_FONT_PATH, "mono")))
    pdfmetrics.registerFont(TTFont(MONO + "-Bold", _need(MONO_BOLD_PATH, "mono bold")))
    # Droid ships a single weight, so its bold/italic slots reuse the regular face.
    pdfmetrics.registerFontFamily(CJK, normal=CJK, bold=CJK, italic=CJK, boldItalic=CJK)
    pdfmetrics.registerFontFamily(
        BODY, normal=BODY, bold=BODY + "-Bold",
        italic=BODY + "-Italic", boldItalic=BODY + "-Bold",
    )
    pdfmetrics.registerFontFamily(
        MONO, normal=MONO, bold=MONO + "-Bold",
        italic=MONO, boldItalic=MONO + "-Bold",
    )


def spans(escaped: str, cjk_size: str = "") -> str:
    """Wrap CJK runs of already-escaped text in the CJK face."""
    attr = f' size="{cjk_size}"' if cjk_size else ""
    return CJK_RE.sub(lambda m: f'<font face="{CJK}"{attr}>{m.group(0)}</font>', escaped)


def make_styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body", fontName=BODY, fontSize=9.4, leading=15.2,
        textColor=colors.HexColor("#1f2328"), alignment=TA_LEFT, spaceAfter=5,
    )
    return {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontSize=25, leading=32,
                                textColor=ACCENT, alignment=TA_CENTER, spaceAfter=10),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=11.5, leading=18,
                                   textColor=MUTED, alignment=TA_CENTER, spaceAfter=4),
        "h1": ParagraphStyle("h1", parent=base, fontSize=17.5, leading=24,
                             textColor=ACCENT, spaceBefore=4, spaceAfter=9),
        "h2": ParagraphStyle("h2", parent=base, fontSize=13.4, leading=19,
                             textColor=ACCENT_LIGHT, spaceBefore=12, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base, fontSize=11, leading=16,
                             textColor=colors.HexColor("#3d4b58"), spaceBefore=9, spaceAfter=4),
        "h4": ParagraphStyle("h4", parent=base, fontSize=9.8, leading=15,
                             textColor=colors.HexColor("#57606a"), spaceBefore=7, spaceAfter=3),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=13, bulletIndent=3, spaceAfter=3),
        "quote": ParagraphStyle("quote", parent=base, leftIndent=10, textColor=MUTED,
                                borderPadding=(0, 0, 0, 6), spaceAfter=5),
        "code": ParagraphStyle("code", fontName=MONO, fontSize=CODE_FONT_SIZE,
                               leading=CODE_FONT_SIZE * 1.5, textColor=CODE_FG),
        "caption": ParagraphStyle("caption", parent=base, fontSize=8.2, leading=12,
                                  textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=9),
        "cell": ParagraphStyle("cell", fontName=BODY, fontSize=8.3, leading=12.4,
                               textColor=colors.HexColor("#1f2328")),
        "cellhead": ParagraphStyle("cellhead", fontName=BODY, fontSize=8.4, leading=12.6,
                                   textColor=colors.white),
    }


INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def inline(text: str) -> str:
    """Convert inline Markdown to reportlab mini-HTML."""
    placeholders: list[str] = []

    def stash(markup: str) -> str:
        placeholders.append(markup)
        return f"\x00{len(placeholders) - 1}\x00"

    def code_sub(m: re.Match[str]) -> str:
        inner = spans(html.escape(m.group(1)))
        return stash(
            f'<font face="{MONO}" size="8.4" color="#b31d28">{inner}</font>'
        )

    text = INLINE_CODE_RE.sub(code_sub, text)
    text = LINK_RE.sub(lambda m: stash(
        f'<a href="{html.escape(m.group(2))}" color="#2d7fb8">'
        f'{spans(html.escape(m.group(1)))}</a>'
    ), text)
    text = BOLD_RE.sub(lambda m: stash(
        f'<font color="#0b3d5c"><b>{spans(html.escape(m.group(1)))}</b></font>'
    ), text)
    text = ITALIC_RE.sub(lambda m: stash(f"<i>{spans(html.escape(m.group(1)))}</i>"), text)

    text = spans(html.escape(text))
    for i, markup in enumerate(placeholders):
        text = text.replace(f"\x00{i}\x00", markup)
    return text


def wrap_code(line: str) -> list[str]:
    line = line.replace("\t", "    ")
    if len(line) <= CODE_MAX_CHARS:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    pad = " " * min(indent + 2, 12)
    out, cur = [], line
    while len(cur) > CODE_MAX_CHARS:
        cut = cur.rfind(" ", 0, CODE_MAX_CHARS)
        if cut <= indent + 4:
            cut = CODE_MAX_CHARS
        out.append(cur[:cut])
        cur = pad + cur[cut:].lstrip(" ")
    out.append(cur)
    return out


def code_block(lines: list[str], styles: dict[str, ParagraphStyle]):
    wrapped: list[str] = []
    for raw in lines:
        wrapped.extend(wrap_code(raw))
    if not wrapped:
        wrapped = [" "]
    # Paragraph (not Preformatted) so a block may mix mono Latin with CJK runs;
    # leading runs of spaces become non-breaking to survive HTML collapsing.
    rendered = []
    for raw in wrapped:
        esc = html.escape(raw)
        indent = len(raw) - len(raw.lstrip(" "))
        if indent:
            esc = "&nbsp;" * indent + esc[indent:]
        esc = esc.replace("  ", "&nbsp;&nbsp;")
        rendered.append(spans(esc, cjk_size=f"{CODE_FONT_SIZE + 0.4:.1f}"))
    inner = Paragraph("<br/>".join(rendered), styles["code"])
    tbl = Table([[inner]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, CODE_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), CODE_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), CODE_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [tbl, Spacer(1, 7)]


def build_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]):
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    head, body = rows[0], rows[1:]

    weights = [1.0] * ncols
    for c in range(ncols):
        longest = max((len(r[c]) for r in rows), default=1)
        weights[c] = max(1.0, min(float(longest), 46.0))
    total = sum(weights)
    widths = [CONTENT_W * w / total for w in weights]

    data = [[Paragraph(inline(c), styles["cellhead"]) for c in head]]
    data += [[Paragraph(inline(c), styles["cell"]) for c in r] for r in body]

    tbl = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    tbl.setStyle(TableStyle(style))
    return [tbl, Spacer(1, 8)]


def build_image(path: Path, alt: str, styles: dict[str, ParagraphStyle]):
    try:
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(str(path)).getSize()
    except Exception:
        return [Paragraph(inline(f"*(图片无法读取: {path.name})*"), styles["caption"])]
    max_w = CONTENT_W
    max_h = 118 * mm
    scale = min(max_w / iw, max_h / ih, 1.0)
    img = Image(str(path), width=iw * scale, height=ih * scale)
    img.hAlign = "CENTER"
    flow = [img]
    if alt and not alt.isdigit():
        flow.append(Paragraph(inline(alt), styles["caption"]))
    else:
        flow.append(Spacer(1, 8))
    return [KeepTogether(flow)]


def parse(md: str, base_dir: Path, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    lines = md.split("\n")
    i = 0
    first_h1 = True
    seen_title = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            flow.extend(code_block(buf, styles))
            continue

        if not stripped:
            i += 1
            continue

        if stripped.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        m = IMAGE_RE.match(stripped)
        if m:
            alt, src = m.group(1), m.group(2).split(" ")[0]
            src = src.split("?")[0]
            p = (base_dir / src).resolve()
            if p.exists():
                flow.extend(build_image(p, alt, styles))
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and re.match(
            r"^\|[\s:|-]+\|?$", lines[i + 1].strip()
        ):
            rows: list[list[str]] = []
            header = [c.strip() for c in stripped.strip("|").split("|")]
            rows.append(header)
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            flow.extend(build_table(rows, styles))
            continue

        if re.match(r"^(---|\*\*\*|___)\s*$", stripped):
            flow.append(Spacer(1, 3))
            flow.append(HRFlowable(width="100%", thickness=0.7, color=RULE,
                                   spaceBefore=2, spaceAfter=9))
            i += 1
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if level == 1 and text.startswith("!TITLE"):
                title = text.replace("!TITLE", "").strip()
                flow.append(Spacer(1, 42 * mm))
                flow.append(Paragraph(inline(title), styles["title"]))
                seen_title = True
                i += 1
                continue
            if level == 1 and text.startswith("!SUB"):
                flow.append(Paragraph(inline(text.replace("!SUB", "").strip()), styles["subtitle"]))
                i += 1
                continue
            if level == 1:
                if not first_h1 or seen_title:
                    flow.append(PageBreak())
                first_h1 = False
                flow.append(Paragraph(inline(text), styles["h1"]))
                flow.append(HRFlowable(width="100%", thickness=1.1, color=ACCENT,
                                       spaceBefore=1, spaceAfter=10))
            else:
                key = {2: "h2", 3: "h3"}.get(level, "h4")
                flow.append(Paragraph(inline(text), styles[key]))
            i += 1
            continue

        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            flow.append(Paragraph(inline(" ".join(buf)), styles["quote"]))
            continue

        bullet_m = re.match(r"^([-*+])\s+(.*)$", stripped)
        num_m = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if bullet_m or num_m:
            while i < len(lines):
                cur = lines[i].strip()
                bm = re.match(r"^([-*+])\s+(.*)$", cur)
                nm = re.match(r"^(\d+)[.)]\s+(.*)$", cur)
                if not (bm or nm):
                    break
                indent = len(lines[i]) - len(lines[i].lstrip(" "))
                text = (bm.group(2) if bm else nm.group(2))
                marker = "•" if bm else f"{nm.group(1)}."
                st = ParagraphStyle(
                    f"b{indent}", parent=styles["bullet"],
                    leftIndent=13 + indent * 9, bulletIndent=3 + indent * 9,
                )
                flow.append(Paragraph(inline(text), st, bulletText=marker))
                i += 1
            flow.append(Spacer(1, 4))
            continue

        buf = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "```", "|", ">", "---"))
                    or re.match(r"^([-*+]|\d+[.)])\s+", nxt) or IMAGE_RE.match(nxt)):
                break
            buf.append(nxt)
            i += 1
        flow.append(Paragraph(inline(" ".join(buf)), styles["body"]))

    return flow


class DocTemplate(BaseDocTemplate):
    def __init__(self, path: str, title: str, **kw):
        super().__init__(path, pagesize=A4, title=title, author="self-test / microduck_rl",
                         leftMargin=MARGIN_X, rightMargin=MARGIN_X,
                         topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM, **kw)
        frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W,
                      PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id="body")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame]),
            PageTemplate(id="main", frames=[frame], onPage=self._decorate),
        ])
        self.doc_title = title

    def _decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        size = 7.6
        x, y = MARGIN_X, MARGIN_BOTTOM - 9 * mm
        # The footer mixes scripts, so draw it run by run with the matching face.
        for run in re.split(f"({CJK_RE.pattern})", self.doc_title):
            if not run:
                continue
            face = CJK if CJK_RE.fullmatch(run) else BODY
            canvas.setFont(face, size)
            canvas.drawString(x, y, run)
            x += canvas.stringWidth(run, face, size)
        canvas.setFont(BODY, size)
        canvas.drawRightString(PAGE_W - MARGIN_X, y, str(doc.page))
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, MARGIN_BOTTOM - 6 * mm, PAGE_W - MARGIN_X, MARGIN_BOTTOM - 6 * mm)
        canvas.restoreState()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if not src.exists():
        raise SystemExit(f"input not found: {src}")

    register_fonts()
    styles = make_styles()
    md = src.read_text(encoding="utf-8")

    title = "MicroDuck 机器人智能体项目技术文档"
    for line in md.split("\n"):
        if line.strip().startswith("# !TITLE"):
            title = line.split("!TITLE", 1)[1].strip()
            break

    flow = parse(md, src.parent, styles)
    # Switch to the decorated template right after the cover block.
    for idx, item in enumerate(flow):
        if isinstance(item, PageBreak):
            flow.insert(idx, NextPageTemplate("main"))
            break

    dst.parent.mkdir(parents=True, exist_ok=True)
    DocTemplate(str(dst), title).build(flow)
    size = dst.stat().st_size
    print(f"wrote {dst}  ({size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
