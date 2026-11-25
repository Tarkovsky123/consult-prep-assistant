"""v5 경로 회귀 확인(사전등록 30_analysis/v4_개선_사전등록.md §13). 기존 실행 폴더를 덮지 않고 따로 돌린다.

  python -X utf8 scripts/run_regress.py run <태그>        # 139건(개발 99 + E2d 40)을 지금 코드의 --v5로 돌림 → data/processed/regress/<태그>/
  python -X utf8 scripts/run_regress.py compare <기준태그> <새태그>

LLM 답은 캐시를 쓰므로 프롬프트가 같으면 다시 부르지 않는다(규칙 단계만 바뀐 경우).
"""
import csv
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_e2_eval import SETS, as_case, run_case  # noqa: E402

ORDER = ["dev", "e2b", "synth", "e2c", "e2d"]
BASE = ROOT / "data/processed/regress"
FIELDS = ("유형연번", "대상", "상한", "협의제외", "유형판정")


def cases_gold(s):
    cfg = SETS[s]
    cases = [as_case(r) for r in csv.DictReader(cfg["cases"].open(encoding="utf-8-sig"))]
    gold = {(g.get("사례") or g["협의ID"]): g for g in csv.DictReader(cfg["gold"].open(encoding="utf-8-sig"))}
    return cases, gold


def run(tag):
    for s in ORDER:
        cases, _ = cases_gold(s)
        runs = BASE / tag / s
        (runs / "M5b").mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(lambda c: run_case(runs, "M5b", c), cases))
        print(s, "완료", flush=True)


def load(tag, s, cid):
    p = BASE / tag / s / "M5b" / f"{cid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def compare(a, b):
    tot = Counter()
    L = []
    for s in ORDER:
        cases, gold = cases_gold(s)
        for c in cases:
            g = gold.get(c["id"])
            if not g or g.get("동일", "예") == "아니오":
                continue
            ra, rb = load(a, s, c["id"]), load(b, s, c["id"])
            if not ra or not rb:
                tot["실패"] += 1
                continue
            ea, eb = ra["eval"], rb["eval"]
            grp = "99" if s != "e2d" else "e2d"
            tot[f"{grp}_n"] += 1
            for tag, e in ((a, ea), (b, eb)):
                tot[f"{grp}_{tag}_판정"] += e["유형판정"] == g["유형판정"]
                tot[f"{grp}_{tag}_연번"] += e["유형연번"] == g["유형연번"]
                tot[f"{grp}_{tag}_신속오권고"] += e["유형판정"] == "신속" and g["유형판정"] != "신속"
                tot[f"{grp}_{tag}_불필요보류"] += e["유형판정"] == "확인불가" and g["유형판정"] != "확인불가"
            if any(ea[f] != eb[f] for f in FIELDS) or (rb.get("v2") or {}).get("v56"):
                L.append(f"| {s} | {c['id']} | {g['유형연번']}·{g['유형판정']} | {ea['유형연번']}·{ea['대상']}·{ea['상한']}·{ea['유형판정']} | "
                         f"{eb['유형연번']}·{eb['대상']}·{eb['상한']}·{eb['유형판정']} | {', '.join((rb.get('v2') or {}).get('v56') or []) or '-'} |")
    print(json.dumps(tot, ensure_ascii=False, indent=1))
    print("\n| 세트 | 사례 | 정답(연번·판정) | 기준 | 새 | 걸린 규칙 |\n|---|---|---|---|---|---|")
    print("\n".join(L) or "| - | 바뀐 사례 없음 | | | | |")


if __name__ == "__main__":
    {"run": lambda: run(sys.argv[2]), "compare": lambda: compare(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
