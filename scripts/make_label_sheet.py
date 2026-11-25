"""사람 라벨 시트(xlsx)를 만든다. 모델 출력은 넣지 않는다(라벨을 다 달기 전에는 structured_*.jsonl 을 열지 않는다).

  python -X utf8 scripts/make_label_sheet.py --source private --n 40
  python -X utf8 scripts/make_label_sheet.py --source local --sido 대구광역시 경상북도 --n 60
출력: data/labels/<source>_label_sheet.xlsx (이미 있으면 덮어쓰지 않는다)
"""
import argparse
import random
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).parent))
from schema import FORM, HOUSEHOLD, INCOME, LIFE, REGION  # noqa: E402
from structure_services import load_local, load_private  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261101
SKIP = {f"PRV{i:04d}" for i in range(6)}  # 파이프라인 시험에 쓴 6건은 평가에서 뺀다

COLUMNS = [  # (머리글, 너비, 설명)
    ("id", 10, ""), ("사업명", 22, ""), ("원문", 80, ""),
    ("life", 18, f"여러 개면 ; 로 구분. 선택지: {', '.join(LIFE)}"),
    ("age_min", 8, "만 나이 숫자, 없으면 비움"), ("age_max", 8, "만 나이 숫자, 없으면 비움"),
    ("household", 18, f"여러 개면 ; 로 구분. 선택지: {', '.join(HOUSEHOLD)}"),
    ("income_type", 14, "하나 고르기(드롭다운)"), ("income_median_pct", 10, "중위소득 % 숫자, 없으면 비움"),
    ("region_type", 12, "하나 고르기(드롭다운)"), ("region_name", 14, "거주지한정일 때 지역명"),
    ("support_form", 16, f"여러 개면 ; 로 구분. 선택지: {', '.join(FORM)}"), ("메모", 24, "애매한 점"),
]


def stratified_sample(items, n):
    """소득·지역 조건이 있는 사업이 표본에 충분히 들어가게 층을 나눠 뽑는다."""
    rng = random.Random(SEED)
    has_cond = [it for it in items if re.search(r"수급|차상위|중위소득|거주|소재", it["text"])]
    rest = [it for it in items if it not in has_cond]
    k = min(len(has_cond), n // 2)
    picked = rng.sample(has_cond, k) + rng.sample(rest, min(len(rest), n - k))
    rng.shuffle(picked)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["private", "local"], required=True)
    ap.add_argument("--sido", nargs="*", default=[])
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    out = ROOT / f"data/labels/{a.source}_label_sheet.xlsx"
    if out.exists():
        sys.exit(f"이미 있음(라벨을 덮어쓰지 않으려고 멈춤): {out}")
    items = [it for it in (load_private() if a.source == "private" else load_local(a.sido)) if it["id"] not in SKIP]
    sample = stratified_sample(items, a.n)

    wb = Workbook()
    ws = wb.active
    ws.title = "labels"
    for c, (head, width, note) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c, value=head)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        ws.column_dimensions[cell.column_letter].width = width
        ws.cell(row=2, column=c, value=note).font = Font(italic=True, color="808080")
    for r, it in enumerate(sample, 3):
        ws.cell(row=r, column=1, value=it["id"])
        ws.cell(row=r, column=2, value=it["name"])
        ws.cell(row=r, column=3, value=it["text"]).alignment = Alignment(wrap_text=True, vertical="top")
    last = len(sample) + 2
    for col, options in (("H", INCOME), ("J", REGION)):  # income_type, region_type 드롭다운
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}3:{col}{last}")
    ws.freeze_panes = "D3"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"{len(sample)}건 → {out}")


if __name__ == "__main__":
    main()
