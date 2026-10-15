#!/usr/bin/env python3
"""
SmartKnob View — генерация производственной документации
Генерирует: BOM (Excel + PDF), сборочный чертёж (PDF)

Запуск:
  python3 scripts/generate_docs.py

Зависимости: openpyxl, reportlab
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = REPO_ROOT / "releases"

# ─── Парсинг KiCad schematic ────────────────────────────────────────────────

def parse_kicad_sch(filepath):
    """Парсит .kicad_sch и извлекает все компоненты."""
    with open(filepath, "r") as f:
        content = f.read()

    # Ищем symbol_instances — там финальные атрибуты компонентов
    instances_match = re.search(r'\(symbol_instances\n(.*?)\n\)', content, re.DOTALL)
    if not instances_match:
        print(f"  [WARN] No symbol_instances found in {filepath}")
        return []

    instances_text = instances_match.group(1)

    # Парсим каждый instance
    components = []
    blocks = re.finditer(
        r'\(path\s+"([^"]+)"\s*\n((?:\s*\([^)]+\)[^\n]*\n?)*)',
        instances_text
    )

    for block in blocks:
        block_text = block.group(2)

        ref_match = re.search(r'\(reference\s+"([^"]+)"\)', block_text)
        value_match = re.search(r'\(value\s+"([^"]+)"\)', block_text)
        fp_match = re.search(r'\(footprint\s+"([^"]+)"\)', block_text)

        if not ref_match or not value_match:
            continue

        ref = ref_match.group(1)
        value = value_match.group(1)
        footprint = fp_match.group(1) if fp_match else ""

        if ref.startswith("#"):
            continue

        components.append({
            "ref": ref,
            "value": value,
            "footprint": footprint,
        })

    # Ищем пользовательские поля (LCSC, Digikey, etc.) в symbol-блоках
    symbol_sections = re.finditer(
        r'\(symbol\s*\(lib_id\s+"([^"]*)"\)\s*\(at\s+([^)]+)\)\s*[^)]*\)(.*?)(?=\(symbol\s|\Z)',
        content,
        re.DOTALL
    )

    extra_fields = {}
    for sym in symbol_sections:
        sym_body = sym.group(0)
        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sym_body)
        if not ref_m:
            continue
        ref = ref_m.group(1)
        if ref.startswith("#"):
            continue

        props = re.findall(
            r'\(property\s+"([^"]+)"\s+"([^"]*)"\s*\(id\s+(\d+)\)',
            sym_body
        )

        fields = {}
        for key, val, pid in props:
            if int(pid) >= 4:
                fields[key] = val

        if fields:
            extra_fields[ref] = fields

    for comp in components:
        ref = comp["ref"]
        if ref in extra_fields:
            comp.update(extra_fields[ref])

    return components


def parse_all_components():
    """Парсит обе платы и возвращает объединённый список."""
    base_sch = REPO_ROOT / "electronics" / "view_base" / "view_base.kicad_sch"
    screen_sch = REPO_ROOT / "electronics" / "view_screen" / "view_screen.kicad_sch"

    print("Parsing view_base schematic...")
    base_comps = parse_kicad_sch(base_sch)
    print(f"  Found {len(base_comps)} components")

    print("Parsing view_screen schematic...")
    screen_comps = parse_kicad_sch(screen_sch)
    print(f"  Found {len(screen_comps)} components")

    for comp in screen_comps:
        comp["board"] = "Screen"
        comp["ref"] = f"SCREEN-{comp['ref']}"

    for comp in base_comps:
        comp["board"] = "Base"

    return base_comps + screen_comps


# ─── Группировка BOM ────────────────────────────────────────────────────────

def group_bom(components):
    """Группирует компоненты по (value, footprint, LCSC)."""
    groups = defaultdict(lambda: {
        "refs": [], "value": "", "footprint": "",
        "LCSC": "", "Digikey": "", "Mouser": "",
        "AliExpress": "", "Note": "", "qty": 0,
    })

    for comp in components:
        key = (comp.get("value", ""), comp.get("footprint", ""), comp.get("LCSC", ""))
        g = groups[key]
        g["refs"].append(comp["ref"])
        g["value"] = comp.get("value", "")
        g["footprint"] = comp.get("footprint", "")
        g["LCSC"] = comp.get("LCSC", "")
        g["Digikey"] = comp.get("Digikey", "")
        g["Mouser"] = comp.get("Mouser", "")
        g["AliExpress"] = comp.get("AliExpress", "")
        g["Note"] = comp.get("Note", "")
        g["qty"] += 1

    bom_list = []
    for g in groups.values():
        g["refs_str"] = ", ".join(sorted(g["refs"], key=lambda x: (not x.startswith("SCREEN"), x)))
        bom_list.append(g)

    bom_list.sort(key=lambda x: (
        0 if all(not r.startswith("SCREEN-") for r in x["refs"]) else 1,
        x["refs"][0]
    ))

    return bom_list


# ─── Генерация Excel ────────────────────────────────────────────────────────

def generate_excel(bom, filepath):
    """Генерирует BOM в .xlsx"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"

    headers = [
        "№", "Поз. обозначение", "Наименование", "Номинал",
        "Корпус (Footprint)", "Кол-во", "LCSC", "Digikey", "Mouser",
        "AliExpress", "Примечание"
    ]

    hfont = Font(name="Arial", bold=True, size=10, color="FFFFFF")
    hfill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    halign = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cfont = Font(name="Arial", size=9)
    calign = Alignment(vertical="top", wrap_text=True)
    border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # Заголовок
    ws.merge_cells("A1:K1")
    ws["A1"].value = "СПЕЦИФИКАЦИЯ (BOM) — SmartKnob View"
    ws["A1"].font = Font(name="Arial", bold=True, size=14, color="2F5496")
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:K2")
    ws["A2"].value = "Платы: View Base + View Screen"
    ws["A2"].font = Font(name="Arial", size=10, color="666666")
    ws["A2"].alignment = Alignment(horizontal="center")

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.font, cell.fill, cell.alignment, cell.border = hfont, hfill, halign, border

    for i, item in enumerate(bom, 1):
        row = i + 4
        fp = item["footprint"].split(":")[-1] if ":" in item["footprint"] else item["footprint"]
        values = [
            i, item["refs_str"], "", item["value"], fp,
            item["qty"], item["LCSC"], item["Digikey"],
            item["Mouser"], item["AliExpress"], item["Note"],
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font, cell.alignment, cell.border = cfont, calign, border

    widths = [5, 30, 25, 12, 25, 8, 12, 20, 20, 30, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.auto_filter.ref = f"A4:K{len(bom) + 4}"

    sfill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    for i, item in enumerate(bom, 1):
        if any(r.startswith("SCREEN-") for r in item["refs"]):
            for col in range(1, len(headers) + 1):
                ws.cell(row=i + 4, column=col).fill = sfill

    wb.save(filepath)
    print(f"  Excel BOM saved: {filepath}")


# ─── Генерация PDF BOM ──────────────────────────────────────────────────────

def generate_pdf_bom(bom, filepath):
    """Генерирует BOM в PDF"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
    from reportlab.lib.enums import TA_CENTER

    doc = SimpleDocTemplate(
        str(filepath), pagesize=A4,
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CT", parent=styles["Title"], fontSize=16,
        textColor=colors.HexColor("#2F5496"), spaceAfter=4*mm,
    )
    sub_style = ParagraphStyle(
        "CS", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#666666"), spaceAfter=6*mm,
    )

    elements = [
        Paragraph("СПЕЦИФИКАЦИЯ (BOM) — SmartKnob View", title_style),
        Paragraph("Платы: View Base + View Screen", sub_style),
        Spacer(1, 3*mm),
    ]

    headers = ["№", "Поз. обозначение", "Номинал", "Корпус", "Кол-во", "LCSC", "Digikey", "Mouser"]
    data = [headers]

    for i, item in enumerate(bom, 1):
        fp = item["footprint"].split(":")[-1] if ":" in item["footprint"] else item["footprint"]
        data.append([
            str(i), item["refs_str"], item["value"], fp,
            str(item["qty"]), item["LCSC"], item["Digikey"], item["Mouser"],
        ])

    col_widths = [8*mm, 40*mm, 15*mm, 30*mm, 8*mm, 15*mm, 25*mm, 25*mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5496")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 6.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]

    # Alternating rows
    for i in range(2, len(data)):
        if i % 2 == 0:
            style_cmds.append(
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F2F2F2"))
            )

    # Highlight Screen section
    for idx, item in enumerate(bom):
        if any(r.startswith("SCREEN-") for r in item["refs"]):
            row = idx + 1
            style_cmds.append(
                ("BACKGROUND", (0, row), (-1, row), colors.HexColor("#E2EFDA"))
            )

    table.setStyle(style_cmds)
    elements.append(table)
    doc.build(elements)
    print(f"  PDF BOM saved: {filepath}")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("SmartKnob View — генерация производственной документации")
    print("=" * 60)

    components = parse_all_components()
    print(f"\nTotal components: {len(components)}")

    bom = group_bom(components)
    print(f"BOM groups: {len(bom)}")

    print("\n--- Generating BOM Excel ---")
    generate_excel(bom, RELEASES_DIR / "BOM_SmartKnob_View.xlsx")

    print("\n--- Generating BOM PDF ---")
    generate_pdf_bom(bom, RELEASES_DIR / "BOM_SmartKnob_View.pdf")

    print("\n--- Done ---")
    print(f"Files saved to: {RELEASES_DIR}/")
    print(f"  - BOM_SmartKnob_View.xlsx")
    print(f"  - BOM_SmartKnob_View.pdf")


if __name__ == "__main__":
    main()
