"""라벨과 모델이 엇갈린 항목을 사람이 다시 판정한다(2차 판정). evaluate.py 를 먼저 돌린다.

  python -X utf8 scripts/adjudicate.py make  --source private --backend codex   # 판정 시트 생성
  python -X utf8 scripts/adjudicate.py score --source private --backend codex   # 판정 반영 정확도
판정: 사람 = 라벨이 맞음 / 모델 = 모델이 맞음(라벨 누락·실수) / 둘 다 = 둘 다 허용 / 둘 다 틀림
"""
import argparse
import json
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
VERDICTS = ["사람", "모델", "둘 다", "둘 다 틀림"]


def paths(source, backend):
    return (ROOT / f"data/processed/eval_{source}_{backend}.json",
            ROOT / f"data/processed/structured_{source}_{backend}.jsonl",
            ROOT / f"data/labels/{source}_adjudication.xlsx")


def make(source, backend):
    ev_path, st_path, out = paths(source, backend)
    if out.exists():
        sys.exit(f"이미 있음(판정을 덮어쓰지 않으려고 멈춤): {out}")
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    text = {json.loads(l)["id"]: json.loads(l)["text"] for l in st_path.open(encoding="utf-8")}
    wb = Workbook()
    ws = wb.active
    heads = [("id", 10), ("항목", 14), ("원문", 80), ("사람 라벨", 22), ("모델", 26), ("판정", 12), ("메모", 24)]
    for c, (h, w) in enumerate(heads, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font, cell.fill = Font(bold=True), PatternFill("solid", fgColor="FCE4D6")
        ws.column_dimensions[cell.column_letter].width = w
    for r, d in enumerate(ev["disagreements"], 2):
        pred = ", ".join(d["pred"]) if isinstance(d["pred"], list) else d["pred"]
        vals = [d["id"], d["field"], text[d["id"]], "(빈칸)" if d["gold"] in (None, "") else d["gold"], pred or "(빈칸)"]
        for c, v in enumerate(vals, 1):
            ws.cell(row=r, column=c, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    dv = DataValidation(type="list", formula1='"' + ",".join(VERDICTS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"F2:F{len(ev['disagreements']) + 1}")
    ws.freeze_panes = "D2"
    wb.save(out)
    print(f"불일치 {len(ev['disagreements'])}건 → {out}")


def score(source, backend):
    ev_path, _, sheet = paths(source, backend)
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ws = load_workbook(sheet, data_only=True).active
    verdict = {(r[0], r[1]): r[5] for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    n = ev["n"]
    lines = [f"# 2차 판정 반영 정확도 ({source}, {backend})", "",
             "정규화 채점에서 엇갈린 항목을 사람이 다시 판정했다. '모델' 또는 '둘 다' 판정은 모델 정답으로 센다.", "",
             "| 항목 | 정규화 일치 | 판정 반영 일치 | 라벨 쪽 수정(모델 판정) | 미판정 |", "|---|---:|---:|---:|---:|"]
    out = {}
    for f, s in ev["fields"].items():
        dis = [d for d in ev["disagreements"] if d["field"] == f]
        v = [verdict.get((d["id"], f)) for d in dis]
        flipped = sum(x in ("모델", "둘 다") for x in v)
        model_fix = sum(x == "모델" for x in v)
        pending = sum(x is None for x in v)
        adj = s["norm_exact"] + flipped / n
        out[f] = {"norm_exact": s["norm_exact"], "adjudicated": round(adj, 3), "label_fixed": model_fix, "pending": pending}
        lines.append(f"| {f} | {s['norm_exact']:.0%} | {adj:.0%} | {model_fix} | {pending} |")
    base = ROOT / f"data/processed/eval_{source}_{backend}_adjudicated"
    base.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "score"])
    ap.add_argument("--source", required=True)
    ap.add_argument("--backend", default="codex")
    a = ap.parse_args()
    make(a.source, a.backend) if a.cmd == "make" else score(a.source, a.backend)
