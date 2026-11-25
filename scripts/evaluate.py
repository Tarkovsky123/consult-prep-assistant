"""사람 라벨 대비 추출 정확도. 기준선은 복지로 기존 태그(생애주기·가구상황만 있음)다.

채점은 두 가지를 함께 낸다.
  원 채점   라벨 칸에 적힌 문자 그대로 비교
  정규화    표기 차이만 맞춘 뒤 비교: '미상' = 빈 목록, 명백한 오타(융지→융자, 바우처/이용권→바우처·이용권),
            소득 자격 칸에 여러 값을 적은 라벨은 모델 값이 그 안에 있으면 일치로 본다(스키마는 한 값만 받으므로)
  python -X utf8 scripts/evaluate.py --source private --backend codex
출력: data/processed/eval_<source>_<backend>.md, .json
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))
from schema import EVAL_FIELDS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MULTI = {"life", "household", "support_form"}
TAG_KEY = {"life": "생애주기", "household": "가구상황"}
ALIAS = {"임신 · 출산": "임신·출산", "융지": "융자", "바우처": "바우처·이용권", "이용권": "바우처·이용권"}
UNKNOWN = {"미상", "없음", "-"}


def tokens(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[;,]", str(v)) if x.strip()]


def as_set(v, normalize):
    toks = tokens(v)
    if normalize:
        toks = [ALIAS.get(t, t) for t in toks if t not in UNKNOWN]
    return set(toks)


def as_scalar(field, v):
    if v in (None, ""):
        return "미상" if field in ("income_type", "region_type") else None
    if field == "income_median_pct":  # 라벨에 '72%이하'처럼 글자가 섞여 들어와도 숫자만 읽는다
        m = re.search(r"\d+(?:\.\d+)?", str(v))
        return int(float(m.group())) if m else None
    return str(v).strip()


def score(field, gold, pred, normalize):
    """(완전 일치 여부, 자카드)"""
    if field in MULTI:
        g, p = as_set(gold, normalize), as_set(pred, normalize)
        return g == p, (1.0 if not g and not p else len(g & p) / len(g | p))
    if field == "income_type" and normalize:
        g = as_set(gold, False) or {"미상"}
        ok = as_scalar(field, pred) in g
        return ok, float(ok)
    ok = as_scalar(field, gold) == as_scalar(field, pred)
    return ok, float(ok)


def read_labels(path):
    ws = load_workbook(path, data_only=True).active
    head = [c.value for c in ws[1]]
    rows = {}
    for r in ws.iter_rows(min_row=3, values_only=True):
        rec = dict(zip(head, r))
        if rec.get("id") and any(rec.get(f) not in (None, "") for f in EVAL_FIELDS):
            rows[rec["id"]] = rec
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["private", "local"], required=True)
    ap.add_argument("--backend", default="codex")
    a = ap.parse_args()
    labels = read_labels(ROOT / f"data/labels/{a.source}_label_sheet.xlsx")
    preds = {json.loads(l)["id"]: json.loads(l)
             for l in (ROOT / f"data/processed/structured_{a.source}_{a.backend}.jsonl").open(encoding="utf-8")}
    ids = [i for i in labels if i in preds and preds[i]["output"]]
    if not ids:
        sys.exit("라벨과 모델 출력이 겹치는 행이 없습니다.")
    n = len(ids)

    result = {"source": a.source, "backend": a.backend, "n": n, "fields": {}, "disagreements": []}
    for f in EVAL_FIELDS:
        s = {"raw_exact": 0.0, "norm_exact": 0.0, "norm_jaccard": 0.0, "tag_exact": 0.0, "tag_jaccard": 0.0}
        for i in ids:
            gold, out = labels[i].get(f), preds[i]["output"].get(f)
            s["raw_exact"] += score(f, gold, out, False)[0]
            e, j = score(f, gold, out, True)
            s["norm_exact"] += e
            s["norm_jaccard"] += j
            if not e:
                result["disagreements"].append({"id": i, "field": f, "gold": gold, "pred": out})
            if f in TAG_KEY:
                te, tj = score(f, gold, preds[i]["tags"].get(TAG_KEY[f]), True)
                s["tag_exact"] += te
                s["tag_jaccard"] += tj
        s = {k: round(v / n, 3) for k, v in s.items()}
        if f not in TAG_KEY:
            s["tag_exact"] = s["tag_jaccard"] = None
        result["fields"][f] = s
    result["evidence_fail_rate"] = round(sum(bool(preds[i]["evidence_failed"]) for i in ids) / n, 3)

    out = ROOT / f"data/processed/eval_{a.source}_{a.backend}"
    out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pct = lambda v: "태그 없음" if v is None else f"{v:.0%}"
    dec = lambda v: "태그 없음" if v is None else f"{v:.2f}"
    lines = [f"# 추출 정확도 ({a.source}, {a.backend}, {datetime.now():%Y-%m-%d %H:%M})", "",
             f"사람 라벨 {n}건. 기준선은 복지로 기존 태그(생애주기·가구상황만 있고 나머지 항목은 태그 자체가 없음).",
             "정규화: '미상' = 빈 목록, 오타(융지→융자, 바우처/이용권→바우처·이용권), 소득 자격에 여러 값을 적은 라벨은 "
             "모델 값이 그 안에 있으면 일치.", "",
             "| 항목 | 모델 일치(원 채점) | 모델 일치(정규화) | 모델 자카드(정규화) | 기존 태그 일치(정규화) | 기존 태그 자카드 |",
             "|---|---:|---:|---:|---:|---:|"]
    for f, s in result["fields"].items():
        lines.append(f"| {f} | {s['raw_exact']:.0%} | {s['norm_exact']:.0%} | {s['norm_jaccard']:.2f} | "
                     f"{pct(s['tag_exact'])} | {dec(s['tag_jaccard'])} |")
    lines += ["", f"근거 구절 불일치 비율: {result['evidence_fail_rate']:.0%}", "",
              "## 정규화 뒤에도 남은 불일치", "", "| id | 항목 | 사람 | 모델 |", "|---|---|---|---|"]
    lines += [f"| {d['id']} | {d['field']} | {d['gold']} | {d['pred']} |" for d in result["disagreements"]]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:16]))
    print(f"남은 불일치 {len(result['disagreements'])}건 → {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
