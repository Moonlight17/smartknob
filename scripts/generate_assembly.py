#!/usr/bin/env python3
"""
SmartKnob View — генерация сборочного чертежа (PDF)
Парсит .kicad_pcb и рисует расположение компонентов.

Запуск:
  python3 scripts/generate_assembly.py
"""

import re
import math
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = REPO_ROOT / "releases"


def parse_footprints(content):
    """Извлекает все footprint-ы из PCB-файла."""
    footprints = []
    # Ищем блоки (footprint "..."
    fp_starts = [m.start() for m in re.finditer(r'\(footprint\s+"([^"]+)"', content)]

    for start in fp_starts:
        # Находим закрывающую скобку этого footprint
        depth = 0
        end = start
        for i in range(start, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        block = content[start:end]

        # Парсим основные поля
        name_m = re.match(r'\(footprint\s+"([^"]+)"', block)
        layer_m = re.search(r'\(layer\s+"([^"]+)"\)', block)
        at_m = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)\s*([-\d.]*)\)', block)

        if not name_m or not layer_m or not at_m:
            continue

        fp_name = name_m.group(1)
        layer = layer_m.group(1)
        x = float(at_m.group(1))
        y = float(at_m.group(2))
        rot = float(at_m.group(3)) if at_m.group(3) else 0

        if "MountingHole" in fp_name:
            continue

        # Reference
        ref_m = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
        if not ref_m:
            continue
        ref = ref_m.group(1)
        if ref.startswith("#"):
            continue

        # Value
        val_m = re.search(r'\(fp_text\s+value\s+"([^"]+)"', block)
        value = val_m.group(1) if val_m else ""

        # Pad-ы для определения размеров
        pads = re.finditer(
            r'\(pad\s+"[^"]*"\s+(smd|thru_hole)\s+(rect|circle|oval|roundrect)\s*'
            r'\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+[-\d.]+)?\)\s*'
            r'\(size\s+([-\d.]+)\s+([-\d.]+)\)',
            block
        )

        min_px = min_py = float('inf')
        max_px = max_py = float('-inf')
        pad_count = 0

        for p in pads:
            px = float(p.group(3))
            py = float(p.group(4))
            sx = float(p.group(5))
            sy = float(p.group(6))

            cos_r = math.cos(math.radians(rot))
            sin_r = math.sin(math.radians(rot))

            corners = [
                (px - sx/2, py - sy/2),
                (px + sx/2, py - sy/2),
                (px + sx/2, py + sy/2),
                (px - sx/2, py + sy/2),
            ]
            for cx, cy in corners:
                rcx = cx * cos_r - cy * sin_r
                rcy = cx * sin_r + cy * cos_r
                min_px = min(min_px, rcx)
                max_px = max(max_px, rcx)
                min_py = min(min_py, rcy)
                max_py = max(max_py, rcy)
            pad_count += 1

        if pad_count == 0:
            w, h = 5.0, 5.0
        else:
            w = max(max_px - min_px, 2.0)
            h = max(max_py - min_py, 2.0)

        footprints.append({
            "ref": ref,
            "value": value,
            "x": x,
            "y": y,
            "rot": rot,
            "width": w,
            "height": h,
            "layer": layer,
            "name": fp_name,
        })

    return footprints


def parse_board_outline(content):
    """Извлекает контур платы из Edge.Cuts."""
    outlines = []
    # Ищем секцию Edge.Cuts
    edge_start = content.find('(layer "Edge.Cuts")')
    if edge_start < 0:
        return outlines

    # Ищем все графические примитивы внутри Edge.Cuts
    # Ищем от этой секции до следующей (layer или конца
    edge_section = content[edge_start:]

    # Полигоны
    for m in re.finditer(
        r'\(gr_poly\s*\(pts\s*((?:\(xy\s+[-\d.]+\s+[-\d.]+\)\s*)+)\)',
        edge_section
    ):
        pts = [(float(x), float(y)) for x, y in
               re.findall(r'xy\s+([-\d.]+)\s+([-\d.]+)', m.group(1))]
        if pts:
            outlines.append(("polygon", pts))

    # Линии
    for m in re.finditer(
        r'\(gr_line\s*\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*\(end\s+([-\d.]+)\s+([-\d.]+)\)',
        edge_section
    ):
        x1, y1, x2, y2 = map(float, m.groups())
        outlines.append(("line", (x1, y1, x2, y2)))

    return outlines


def generate_assembly_pdf(board_outline, footprints, filepath, title):
    """Рисует сборочный чертёж в PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    # Границы
    if board_outline:
        all_x, all_y = [], []
        for st, sd in board_outline:
            if st == "polygon":
                for x, y in sd:
                    all_x.append(x); all_y.append(y)
            elif st == "line":
                all_x.extend([sd[0], sd[2]]); all_y.extend([sd[1], sd[3]])
        if all_x:
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
        else:
            min_x = min(fp["x"] for fp in footprints) - 5
            max_x = max(fp["x"] for fp in footprints) + 5
            min_y = min(fp["y"] for fp in footprints) - 5
            max_y = max(fp["y"] for fp in footprints) + 5
    elif footprints:
        min_x = min(fp["x"] for fp in footprints) - 5
        max_x = max(fp["x"] for fp in footprints) + 5
        min_y = min(fp["y"] for fp in footprints) - 5
        max_y = max(fp["y"] for fp in footprints) + 5
    else:
        return  # ничего рисовать

    board_w = max_x - min_x
    board_h = max_y - min_y

    margin = 15 * mm
    page_w, page_h = A4
    draw_w = page_w - 2 * margin
    draw_h = page_h - 2 * margin - 25 * mm

    scale = min(draw_w / board_w, draw_h / board_h) * 0.9
    ox = margin + (draw_w - board_w * scale) / 2
    oy = margin + 25 * mm + (draw_h - board_h * scale) / 2

    def to_page(px, py):
        px_mm = px * scale
        py_mm = -py * scale
        return ox + (px_mm - min_x * scale), oy + (py_mm + max_y * scale)

    c = canvas.Canvas(str(filepath), pagesize=A4)

    # Заголовок
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.HexColor("#2F5496"))
    c.drawString(margin, page_h - 12 * mm, title)

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, page_h - 18 * mm,
                 f"Масштаб: ~{scale:.2f}  |  Плата: {board_w:.1f} x {board_h:.1f} мм  |  Компонентов: {len(footprints)}")

    # Контур платы
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.3)
    for st, sd in board_outline:
        if st == "polygon":
            pts = [to_page(x, y) for x, y in sd]
            c.setFillColor(colors.HexColor("#F0F0F0"))
            p = c.beginPath()
            p.moveTo(pts[0][0], pts[0][1])
            for px, py in pts[1:]:
                p.lineTo(px, py)
            p.close()
            c.drawPath(p, fill=1, stroke=1)
        elif st == "line":
            p1 = to_page(sd[0], sd[1])
            p2 = to_page(sd[2], sd[3])
            c.line(p1[0], p1[1], p2[0], p2[1])

    # Компоненты
    c.setFont("Helvetica", 5)
    for fp in footprints:
        x, y = to_page(fp["x"], fp["y"])
        w = fp["width"] * scale
        h = fp["height"] * scale

        # Цвет в зависимости от слоя
        if fp["layer"] == "F.Cu":
            fill_color = colors.HexColor("#D6E4F0")
        else:
            fill_color = colors.HexColor("#F0D6D6")

        c.setStrokeColor(colors.HexColor("#2F5496"))
        c.setLineWidth(0.2)
        c.setFillColor(fill_color)
        c.rect(x - w / 2, y - h / 2, w, h, fill=1, stroke=1)

        # Маркер pin 1
        c.setFillColor(colors.red)
        angle_rad = math.radians(fp["rot"])
        dx = w / 3 * math.cos(angle_rad)
        dy = w / 3 * math.sin(angle_rad)
        c.circle(x + dx, y - dy, 0.5, fill=1, stroke=0)

        # Reference
        c.setFillColor(colors.black)
        ref_text = fp["ref"]
        if len(ref_text) > 8:
            ref_text = ref_text[:7] + "."
        c.drawCentredString(x, y - 1.5 * mm, ref_text)

    # Легенда
    leg_x = margin
    leg_y = margin + 3 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(leg_x, leg_y, "Условные обозначения:")

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#D6E4F0"))
    c.rect(leg_x, leg_y - 4 * mm, 4 * mm, 3 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 3.5 * mm, "Компонент (верх)")
    c.setFillColor(colors.HexColor("#F0D6D6"))
    c.rect(leg_x, leg_y - 8 * mm, 4 * mm, 3 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 7.5 * mm, "Компонент (низ)")
    c.setFillColor(colors.red)
    c.circle(leg_x + 2 * mm, leg_y - 11 * mm, 0.5, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 11.5 * mm, "Вывод 1 / ориентация")

    c.save()
    print(f"  Assembly PDF saved: {filepath}")


def main():
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("SmartKnob View — генерация сборочных чертежей")
    print("=" * 60)

    for board_name, pcb_file in [
        ("View Base", REPO_ROOT / "electronics" / "view_base" / "view_base.kicad_pcb"),
        ("View Screen", REPO_ROOT / "electronics" / "view_screen" / "view_screen.kicad_pcb"),
    ]:
        print(f"\nProcessing {board_name}...")
        with open(pcb_file) as f:
            content = f.read()

        outline = parse_board_outline(content)
        footprints = parse_footprints(content)
        print(f"  Board outline: {'found' if outline else 'not found'}")
        print(f"  Total footprints: {len(footprints)}")

        top_fps = [fp for fp in footprints if fp["layer"] == "F.Cu"]
        bot_fps = [fp for fp in footprints if fp["layer"] == "B.Cu"]

        print(f"  Top: {len(top_fps)}, Bottom: {len(bot_fps)}")

        fname = board_name.lower().replace(" ", "_")
        generate_assembly_pdf(outline, top_fps,
            RELEASES_DIR / f"Assembly_{fname}_top.pdf",
            f"Сборочный чертёж — {board_name} (верх)")

        if bot_fps:
            generate_assembly_pdf(outline, bot_fps,
                RELEASES_DIR / f"Assembly_{fname}_bottom.pdf",
                f"Сборочный чертёж — {board_name} (низ)")

    print("\n--- Done ---")
    print(f"Files saved to: {RELEASES_DIR}/")


if __name__ == "__main__":
    main()
