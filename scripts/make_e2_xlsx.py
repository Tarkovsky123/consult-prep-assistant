"""E2 라벨 시트를 엑셀에서 읽기 쉬운 xlsx로 만든다(원본 CSV는 그대로 둔다). 모델 출력은 넣지 않는다.

  python -X utf8 scripts/make_e2_xlsx.py
출력: data/labels/E2_요건대조_라벨시트.xlsx (이미 있으면 라벨을 덮어쓰지 않으려고 멈춘다)
시트: 라벨(원문 옆에 라벨 칸, 드롭다운) / 신속유형_참고(2026 신속협의 유형 79개) / 다는 법
"""
import csv
import math
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/labels/E2_요건대조_라벨시트.csv"
FAST = ROOT / "data/raw/신속협의_유형_2026.csv"
OUT = ROOT / "data/labels/E2_요건대조_라벨시트.xlsx"

# (열 이름, 너비) — 판정에 쓰는 열을 앞에, 참고 열을 뒤에 둔다
LAYOUT = [("협의ID", 7), ("협의요청기관", 13), ("협의 사업명", 24), ("복지로 사업명", 22),
          ("원문 지원대상", 70), ("원문 선정기준", 70), ("원문 지원내용", 70),
          ("[라벨] 동일 사업인가(예/아니오/불확실)", 13),
          ('[라벨] 해당 신속협의 유형 연번(신속협의_유형_2026.csv; 없으면 "해당없음")', 13),
          ("[라벨] 대상이 유형 범위 안인가(안/밖/확인불가)", 13),
          ("[라벨] 지원수준이 상한 안인가(안/밖/확인불가)", 13),
          ("[라벨] 유형 판정(협의제외/신속/일반/확인불가)", 14), ("메모", 30),
          ("신설변경", 8), ("복지로 servId", 13), ("이름유사도", 9), ("태그 생애주기", 14), ("태그 가구상황", 14), ("태그 관심주제", 14)]
CHOICES = {"[라벨] 동일 사업인가(예/아니오/불확실)": ["예", "아니오", "불확실"],
           "[라벨] 대상이 유형 범위 안인가(안/밖/확인불가)": ["안", "밖", "확인불가"],
           "[라벨] 지원수준이 상한 안인가(안/밖/확인불가)": ["안", "밖", "확인불가"],
           "[라벨] 유형 판정(협의제외/신속/일반/확인불가)": ["협의제외", "신속", "일반", "확인불가"]}
WRAP = Alignment(wrap_text=True, vertical="top")
HEAD_FILL, LABEL_FILL = PatternFill("solid", fgColor="DDEBF7"), PatternFill("solid", fgColor="FFF2CC")


def row_height(values_widths):
    """한글은 대략 열 너비 0.5글자당 1자. 가장 긴 칸의 줄 수로 높이를 잡는다(엑셀 최대 409pt)."""
    lines = 1
    for text, width in values_widths:
        text = str(text or "")
        per_line = max(1, int(width * 0.5))
        n = sum(max(1, math.ceil(len(part) / per_line)) for part in text.split("\n"))
        lines = max(lines, n)
    return min(409, max(30, lines * 15 + 6))


def sheet_labels(wb, rows):
    ws = wb.active
    ws.title = "라벨"
    for c, (name, width) in enumerate(LAYOUT, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(bold=True)
        cell.fill = LABEL_FILL if (name.startswith("[라벨]") or name == "메모") else HEAD_FILL
        cell.alignment = WRAP
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 75
    for r, rec in enumerate(rows, 2):
        for c, (name, _) in enumerate(LAYOUT, 1):
            cell = ws.cell(row=r, column=c, value=rec.get(name, ""))
            cell.alignment = WRAP
            if name.startswith("[라벨]") or name == "메모":
                cell.fill = LABEL_FILL
        ws.row_dimensions[r].height = row_height([(rec.get(n, ""), w) for n, w in LAYOUT])
    last = len(rows) + 1
    letters = {name: ws.cell(row=1, column=c).column_letter for c, (name, _) in enumerate(LAYOUT, 1)}
    for name, opts in CHOICES.items():
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{letters[name]}2:{letters[name]}{last}")
    code_col = letters['[라벨] 해당 신속협의 유형 연번(신속협의_유형_2026.csv; 없으면 "해당없음")']
    dv = DataValidation(type="list", formula1="='신속유형_참고'!$A$2:$A$81", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{code_col}2:{code_col}{last}")
    ws.freeze_panes = "E2"  # 협의ID~복지로 사업명과 머리글을 고정


def sheet_fast(wb):
    ws = wb.create_sheet("신속유형_참고")
    cols = [("연번", 7), ("분야", 11), ("사업명", 28), ("대상", 26), ("지원수준(최대 상한)", 70), ("중복·보충 조건", 45), ("지침쪽(인쇄)", 9)]
    for c, (name, width) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill, cell.alignment = Font(bold=True), HEAD_FILL, WRAP
        ws.column_dimensions[cell.column_letter].width = width
    fast = list(csv.DictReader(FAST.open(encoding="utf-8-sig")))
    for r, rec in enumerate(fast, 2):
        for c, (name, _) in enumerate(cols, 1):
            ws.cell(row=r, column=c, value=int(rec[name]) if name == "연번" else rec.get(name, "")).alignment = WRAP
        ws.row_dimensions[r].height = row_height([(rec.get(n, ""), w) for n, w in cols])
    ws.cell(row=len(fast) + 2, column=1, value="해당없음")  # 연번 드롭다운의 마지막 선택지
    ws.freeze_panes = "B2"


def sheet_guide(wb):
    ws = wb.create_sheet("다는 법")
    ws.column_dimensions["A"].width = 120
    lines = [
        "E2 다는 법 (data/labels/README.md 'E2 다는 법'과 같음)",
        "1. '라벨' 시트의 노란 칸만 채운다. 원문 세 칸(지원대상·선정기준·지원내용)만 보고 판단한다.",
        "2. 비교 기준은 '신속유형_참고' 시트(2026 신속협의 유형 79개, 11/2 원문 검수본)다. 연번 칸은 드롭다운에서 고른다. 맞는 유형이 없으면 '해당없음'.",
        "3. 원문에 금액·대상이 없으면 '확인불가'를 고른다. 추측하지 않는다. 이 '확인불가'가 도구의 보류 표시 정답이 된다.",
        "   단, 원문에 근거가 있는데 확인불가를 고르면 '불필요한 보류'의 정답이 흐려진다.",
        "4. 협의제외 여부는 2026 지침 Ⅱ.3(협의 제외 대상, 인쇄 17~18쪽)을 기준으로 한다. 애매하면 '확인불가' + 메모.",
        "5. 협의 사업명과 복지로 사업명이 다른 사업이면 '동일 사업인가'에 아니오를 적고 나머지는 비운다.",
        "6. 라벨을 단 뒤에는 바꾸지 않는다. 바꿀 일이 있으면 사유를 메모에 남긴다.",
        "7. 셀 내용이 잘리면 셀을 클릭하고 수식 입력줄(위쪽)에서 전체를 본다.",
        "지침 원문: 10_research/sources/ssc-2026-consult-guideline.pdf (신속협의 목록 PDF 34~41쪽 = 인쇄 24~31쪽)",
    ]
    for r, t in enumerate(lines, 1):
        ws.cell(row=r, column=1, value=t).alignment = WRAP
    ws.cell(row=1, column=1).font = Font(bold=True)


def main():
    if OUT.exists():
        sys.exit(f"이미 있음(라벨을 덮어쓰지 않으려고 멈춤): {OUT}")
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    missing = [n for n, _ in LAYOUT if n not in rows[0]]
    if missing:
        sys.exit(f"CSV에 없는 열: {missing}")
    wb = Workbook()
    sheet_labels(wb, rows)
    sheet_fast(wb)
    sheet_guide(wb)
    wb.save(OUT)
    print(f"{len(rows)}건 → {OUT}")


if __name__ == "__main__":
    main()
