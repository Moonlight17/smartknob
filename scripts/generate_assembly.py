#!/usr/bin/env python3
"""
SmartKnob View — генерация сборочного чертежа (PDF)
"""

import re
import math
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = REPO_ROOT / "releases"


def parse_footprints(content):
    footprints = []
    fp_starts = [m.start() for m in re.finditer(r'\(footprint\s+"([^"]+)"', content)]
    for start in fp_starts:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block = content[start:i+1]
                    break
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
        ref_m = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
        if not ref_m:
            continue
        ref = ref_m.group(1)
        if ref.startswith("#"):
            continue
        val_m = re.search(r'\(fp_text\s+value\s+"([^"]+)"', block)
        value = val_m.group(1) if val_m else ""
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
            for cx, cy in [(px-sx/2, py-sy/2), (px+sx/2, py-sy/2),
                           (px+sx/2, py+sy/2), (px-sx/2, py+sy/2)]:
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
            "ref": ref, "value": value, "x": x, "y": y, "rot": rot,
            "width": w, "height": h, "layer": layer, "name": fp_name,
        })
    return footprints


def parse_board_outline(content):
    outlines = []
    edge_start = content.find('(layer "Edge.Cuts")')
    if edge_start < 0:
        return outlines
    edge_section = content[edge_start:]
    for m in re.finditer(
        r'\(gr_poly\s*\(pts\s*((?:\(xy\s+[-\d.]+\s+[-\d.]+\)\s*)+)\)',
        edge_section
    ):
        pts = [(float(x), float(y)) for x, y in
               re.findall(r'xy\s+([-\d.]+)\s+([-\d.]+)', m.group(1))]
        if pts:
            outlines.append(("polygon", pts))
    for m in re.finditer(
        r'\(gr_line\s*\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*\(end\s+([-\d.]+)\s+([-\d.]+)\)',
        edge_section
    ):
        x1, y1, x2, y2 = map(float, m.groups())
        outlines.append(("line", (x1, y1, x2, y2)))
    for m in re.finditer(
        r'\(gr_circle\s*\(center\s+([-\d.]+)\s+([-\d.]+)\)\s*\(end\s+([-\d.]+)\s+([-\d.]+)\)',
        edge_section
    ):
        cx, cy = float(m.group(1)), float(m.group(2))
        ex, ey = float(m.group(3)), float(m.group(4))
        r = math.sqrt((ex-cx)**2 + (ey-cy)**2)
        outlines.append(("circle", (cx, cy, r)))
    for m in re.finditer(
        r'\(gr_arc\s*\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*\(mid\s+([-\d.]+)\s+([-\d.]+)\)\s*\(end\s+([-\d.]+)\s+([-\d.]+)\)',
        edge_section
    ):
        sx, sy = float(m.group(1)), float(m.group(2))
        mx, my = float(m.group(3)), float(m.group(4))
        ex, ey = float(m.group(5)), float(m.group(6))
        outlines.append(("arc", (sx, sy, mx, my, ex, ey)))
    return outlines


def get_board_bounds(board_outline, footprints):
    # Always include footprint bounds as baseline
    if footprints:
        min_x = min(fp["x"] for fp in footprints) - 5
        max_x = max(fp["x"] for fp in footprints) + 5
        min_y = min(fp["y"] for fp in footprints) - 5
        max_y = max(fp["y"] for fp in footprints) + 5
    else:
        min_x = min_y = 0
        max_x = max_y = 10
    
    # Expand with outline bounds
    for st, sd in board_outline:
        if st == "polygon":
            for x, y in sd:
                min_x = min(min_x, x); max_x = max(max_x, x)
                min_y = min(min_y, y); max_y = max(max_y, y)
        elif st == "line":
            min_x = min(min_x, sd[0], sd[2]); max_x = max(max_x, sd[0], sd[2])
            min_y = min(min_y, sd[1], sd[3]); max_y = max(max_y, sd[1], sd[3])
        elif st == "circle":
            cx, cy, r = sd
            min_x = min(min_x, cx - r); max_x = max(max_x, cx + r)
            min_y = min(min_y, cy - r); max_y = max(max_y, cy + r)
        elif st == "arc":
            min_x = min(min_x, sd[0], sd[2], sd[4]); max_x = max(max_x, sd[0], sd[2], sd[4])
            min_y = min(min_y, sd[1], sd[3], sd[5]); max_y = max(max_y, sd[1], sd[3], sd[5])
    
    return min_x, max_x, min_y, max_y


def generate_assembly_pdf(board_outline, footprints, filepath, title):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    if not footprints:
        c = canvas.Canvas(str(filepath), pagesize=A4)
        c.setFont("Helvetica", 12)
        c.drawString(30*mm, 150*mm, f"{title} - no components")
        c.save()
        print(f"  Assembly PDF saved (empty): {filepath}")
        return

    min_x, max_x, min_y, max_y = get_board_bounds(board_outline, footprints)
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

    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.HexColor("#2F5496"))
    c.drawString(margin, page_h - 12 * mm, title)

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, page_h - 18 * mm,
                 f"Scale: ~{scale:.2f}  |  Board: {board_w:.1f} x {board_h:.1f} mm  |  Components: {len(footprints)}")

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
        elif st == "circle":
            cx, cy, r = sd
            px, py = to_page(cx, cy)
            r_mm = r * scale
            c.setFillColor(colors.HexColor("#F0F0F0"))
            c.circle(px, py, r_mm, fill=1, stroke=1)
        elif st == "arc":
            p1 = to_page(sd[0], sd[1])
            p2 = to_page(sd[4], sd[5])
            c.line(p1[0], p1[1], p2[0], p2[1])

    for fp in footprints:
        x, y = to_page(fp["x"], fp["y"])
        w = max(fp["width"] * scale, 8.0)
        h = max(fp["height"] * scale, 8.0)
        if fp["layer"] == "F.Cu":
            fill_color = colors.HexColor("#D6E4F0")
            stroke_color = colors.HexColor("#2F5496")
        else:
            fill_color = colors.HexColor("#F0D6D6")
            stroke_color = colors.HexColor("#962F2F")
        c.setStrokeColor(stroke_color)
        c.setLineWidth(0.2)
        c.setFillColor(fill_color)
        c.rect(x - w / 2, y - h / 2, w, h, fill=1, stroke=1)
        c.setFillColor(colors.red)
        angle_rad = math.radians(fp["rot"])
        dx = w / 3 * math.cos(angle_rad)
        dy = w / 3 * math.sin(angle_rad)
        c.circle(x + dx, y - dy, 0.5, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 5)
        ref_text = fp["ref"]
        if len(ref_text) > 8:
            ref_text = ref_text[:7] + "."
        c.drawCentredString(x, y + h/2 + 2.0, ref_text)

    leg_x = margin
    leg_y = margin + 3 * mm
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.black)
    c.drawString(leg_x, leg_y, "Legend:")
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#D6E4F0"))
    c.rect(leg_x, leg_y - 4 * mm, 4 * mm, 3 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 3.5 * mm, "Component (top)")
    c.setFillColor(colors.HexColor("#F0D6D6"))
    c.rect(leg_x, leg_y - 8 * mm, 4 * mm, 3 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 7.5 * mm, "Component (bottom)")
    c.setFillColor(colors.red)
    c.circle(leg_x + 2 * mm, leg_y - 11 * mm, 0.5, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.drawString(leg_x + 5 * mm, leg_y - 11.5 * mm, "Pin 1 / orientation")

    c.save()
    sz = os.path.getsize(filepath)
    print(f"  Assembly PDF saved ({sz} bytes): {filepath}")


def main():
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("SmartKnob View - assembly drawing generation")
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
        print(f"  Board outline: {len(outline)} primitives")
        print(f"  Total footprints: {len(footprints)}")
        top_fps = [fp for fp in footprints if fp["layer"] == "F.Cu"]
        bot_fps = [fp for fp in footprints if fp["layer"] == "B.Cu"]
        print(f"  Top: {len(top_fps)}, Bottom: {len(bot_fps)}")
        fname = board_name.lower().replace(" ", "_")
        generate_assembly_pdf(outline, footprints,
            RELEASES_DIR / f"Assembly_{fname}_all.pdf",
            f"Assembly drawing - {board_name} (all components)")
        generate_assembly_pdf(outline, top_fps,
            RELEASES_DIR / f"Assembly_{fname}_top.pdf",
            f"Assembly drawing - {board_name} (top)")
        if bot_fps:
            generate_assembly_pdf(outline, bot_fps,
                RELEASES_DIR / f"Assembly_{fname}_bottom.pdf",
                f"Assembly drawing - {board_name} (bottom)")
    print("\n--- Done ---")

if __name__ == "__main__":
    main()
