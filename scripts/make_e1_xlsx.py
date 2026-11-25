"""E1 유사쌍 판정 시트를 엑셀에서 읽기 쉬운 xlsx로 만든다(원본 CSV는 그대로 둔다).

판정을 흐리지 않도록 검색 방식 정보는 넣지 않는다:
  - '순위(또는 방식)', '문자유사도', '같은 시군구' 열을 뺀다
  - 사례 안의 후보 순서를 섞는다(시드 고정) — 원래 순서가 방식별 순위라서
라벨은 (협의ID, 복지로 servId)로 원본 CSV에 다시 연결한다.

  python -X utf8 scripts/make_e1_xlsx.py
출력: data/labels/E1_유사쌍_판정시트.xlsx (이미 있으면 라벨을 덮어쓰지 않으려고 멈춘다)
"""
import csv
import random
import sys
from collections import OrderedDict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_e2_xlsx import row_height  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/labels/E1_유사쌍_후보.csv"
LOCAL = ROOT / "data/raw/api/local_list.csv"
OUT = ROOT / "data/labels/E1_유사쌍_판정시트.xlsx"
SEED = 20261103

COLS = [("사례", 6), ("협의ID", 7), ("협의요청기관", 13), ("협의 사업명", 26), ("후보 시도", 11), ("후보 시군구", 11),
        ("복지로 사업명", 30), ("복지로 요약", 62), ("사람 판정(동일/유사/무관)", 12), ("메모", 26), ("복지로 servId", 13)]
WRAP = Alignment(wrap_text=True, vertical="top")
HEAD_FILL, LABEL_FILL = PatternFill("solid", fgColor="DDEBF7"), PatternFill("solid", fgColor="FFF2CC")
BAND = [PatternFill("solid", fgColor="FFFFFF"), PatternFill("solid", fgColor="F2F2F2")]  # 사례별 줄무늬


def main():
    if OUT.exists():
        sys.exit(f"이미 있음(라벨을 덮어쓰지 않으려고 멈춤): {OUT}")
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    summary = {l["servId"]: l["servDgst"] for l in csv.DictReader(LOCAL.open(encoding="utf-8-sig"))}
    cases = OrderedDict()
    for r in rows:
        cases.setdefault(r["협의ID"], []).append(r)
    rng = random.Random(SEED)

    wb = Workbook()
    ws = wb.active
    ws.title = "판정"
    for c, (name, width) in enumerate(COLS, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.alignment = Font(bold=True), WRAP
        cell.fill = LABEL_FILL if name in ("사람 판정(동일/유사/무관)", "메모") else HEAD_FILL
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 45
    r_out = 2
    for n, (cid, cands) in enumerate(cases.items(), 1):
        cands = cands[:]
        rng.shuffle(cands)
        for cand in cands:
            vals = {"사례": n, "협의ID": cid, "협의요청기관": cand["협의요청기관"], "협의 사업명": cand["협의 사업명"],
                    "후보 시도": cand["시도"], "후보 시군구": cand["시군구"], "복지로 사업명": cand["복지로 사업명"],
                    "복지로 요약": summary.get(cand["복지로 servId"], cand["요약 앞80자"]),
                    "사람 판정(동일/유사/무관)": cand.get("사람 판정(동일/유사/무관)", ""), "메모": "",
                    "복지로 servId": cand["복지로 servId"]}
            for c, (name, _) in enumerate(COLS, 1):
                cell = ws.cell(row=r_out, column=c, value=vals[name])
                cell.alignment = WRAP
                cell.fill = LABEL_FILL if name in ("사람 판정(동일/유사/무관)", "메모") else BAND[n % 2]
            ws.row_dimensions[r_out].height = row_height([(vals[nm], w) for nm, w in COLS])
            r_out += 1
    dv = DataValidation(type="list", formula1='"동일,유사,무관"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"I2:I{r_out - 1}")
    ws.freeze_panes = "E2"

    guide = wb.create_sheet("다는 법")
    guide.column_dimensions["A"].width = 120
    for i, t in enumerate([
        "E1 다는 법 (data/labels/README.md 'E1 다는 법'과 같음)",
        "1. '판정' 시트의 노란 칸만 채운다. 같은 '사례' 번호(회색·흰색 줄무늬)가 협의 사업 하나와 그 후보들이다. 후보 순서는 무작위다.",
        "2. 같은 목적·같은 대상·같은 급여 형태면 '동일', 목적은 같고 대상·급여가 다르면 '유사', 그 밖은 '무관'. 드롭다운에서 고른다.",
        "3. 한 사례의 후보가 모두 '무관'이면 그 사례 아무 행의 메모에 '후보 없음'이라고 적는다(검색 누락 사례로 쓴다).",
        "4. 라벨을 단 뒤에는 바꾸지 않는다. 바꿀 일이 있으면 사유를 메모에 남긴다.",
        "5. 셀 내용이 잘리면 셀을 클릭하고 수식 입력줄에서 전체를 본다.",
        "6. 검색 방식·점수는 일부러 뺐다. 원본 CSV(E1_유사쌍_후보.csv)는 판정이 끝날 때까지 열지 않는다.",
    ], 1):
        guide.cell(row=i, column=1, value=t).alignment = WRAP
    guide.cell(row=1, column=1).font = Font(bold=True)
    wb.save(OUT)
    print(f"사례 {len(cases)}개, 후보 {r_out - 2}행 → {OUT}")


if __name__ == "__main__":
    main()
