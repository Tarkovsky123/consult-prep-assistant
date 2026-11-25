"""구조화 결과 요약: 항목별 채움률, 근거 구절 일치율, 기존 태그와의 차이.

  python -X utf8 scripts/summarize_structured.py --source private --backend codex
  python -X utf8 scripts/summarize_structured.py --source local --skip-sido 대구광역시 경상북도 --suffix national   # 대구·경북 밖(C4)
출력: data/processed/summary_<source>_<backend>[_<suffix>].json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG_ALIAS = {"임신 · 출산": "임신·출산"}


def tagset(s):
    return {TAG_ALIAS.get(x.strip(), x.strip()) for x in (s or "").split(",") if x.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="private")
    ap.add_argument("--backend", default="codex")
    ap.add_argument("--skip-sido", nargs="*", default=[])
    ap.add_argument("--suffix", default="")
    a = ap.parse_args()
    rows = [json.loads(l) for l in (ROOT / f"data/processed/structured_{a.source}_{a.backend}.jsonl").open(encoding="utf-8")]
    rows = [r for r in rows if (r.get("org") or "").split(" ")[0] not in a.skip_sido]
    ok = [r for r in rows if r["output"]]
    n = len(ok)
    pct = lambda k: round(k / n, 3) if n else 0
    out = [r["output"] for r in ok]
    income = Counter(o["income_type"] for o in out)
    region = Counter(o["region_type"] for o in out)
    summary = {
        "source": a.source, "backend": a.backend, "rows": len(rows), "structured": n,
        "missing_from_model": len(rows) - n,
        "evidence_all_verified": pct(sum(not r["evidence_failed"] for r in ok)),
        "evidence_failed_rows": sum(bool(r["evidence_failed"]) for r in ok),  # 비율이 반올림돼 1.0으로 보이는 것을 막는다(11/10)
        "conditions_total": sum(len(o["conditions"]) for o in out),
        "conditions_with_or": pct(sum(any(c["join"] == "OR" for c in o["conditions"]) for o in out)),
        "conditions_with_exception": pct(sum(any(c["exception"] for c in o["conditions"]) for o in out)),
        "income_type": dict(income.most_common()),
        "income_stated": pct(n - income.get("미상", 0)),
        "income_median_pct_values": dict(Counter(o["income_median_pct"] for o in out if o["income_median_pct"]).most_common()),
        "region_type": dict(region.most_common()),
        "age_range_stated": pct(sum(o["age_min"] is not None or o["age_max"] is not None for o in out)),
        "support_form": dict(Counter(f for o in out for f in o["support_form"]).most_common()),
        "life_differs_from_tag": pct(sum(set(o["life"]) != tagset(r["tags"].get("생애주기")) for r, o in zip(ok, out))),
        "household_differs_from_tag": pct(sum(set(o["household"]) != tagset(r["tags"].get("가구상황")) for r, o in zip(ok, out))),
        "tag_life_empty": pct(sum(not tagset(r["tags"].get("생애주기")) for r in ok)),
        "sec_per_item_mean": round(sum(r["sec_per_item"] for r in ok) / n, 1) if n else None,
    }
    path = ROOT / f"data/processed/summary_{a.source}_{a.backend}{'_' + a.suffix if a.suffix else ''}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
