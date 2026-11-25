"""E2d: v5 시험용 새 협의 사례 40건(층 나눔)을 뽑는다. 시제품 출력은 쓰지 않는다.

사전등록: 30_analysis/v4_개선_사전등록.md §6 (11/7 고정)
  E2c(make_e2c_cases.py)와 같은 원천·짝짓기·층 나누기(같은 낱말 목록·일반어)를 쓰고, 달라지는 것은 둘뿐이다.
  1. E2c에 쓴 협의ID 40개도 뺀다(E2·E2b·E3는 E2c 코드가 이미 뺀다).
  2. 시드 20261107(층마다 '20261107-T'·'20261107-O').
  python -X utf8 scripts/make_e2d_cases.py
출력: data/labels/E2d_요건대조_사례.csv (E2c와 같은 열)
"""
import csv
import difflib
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_e2b_cases as b  # noqa: E402
import make_e2c_cases as c  # noqa: E402  (type_words, used_ids, MIN_SIM, N_PER를 그대로 쓴다)

OUT = ROOT / "data/labels/E2d_요건대조_사례.csv"
SEED = 20261107


def used_ids():
    ids = c.used_ids()
    ids |= {r["협의ID"] for r in csv.DictReader((ROOT / "data/labels/E2c_요건대조_사례.csv").open(encoding="utf-8-sig"))}
    return ids


def main():
    words = c.type_words()
    services = list(csv.DictReader(b.LIST.open(encoding="utf-8-sig")))
    by_region = {}
    for s in services:
        key = b.SIDO_KEY.get(s["ctpvNm"], s["ctpvNm"])
        sgg = "" if s["sggNm"] in ("", s["ctpvNm"]) else s["sggNm"]
        by_region.setdefault((key, sgg), []).append(s)
    skip = used_ids()
    pools = {"T": [], "O": []}
    for row in csv.DictReader(b.CONSULT.open(encoding="utf-8-sig")):
        if row["연번"] in skip:
            continue
        reg = b.org_region(row["협의요청기관"])
        if not reg:
            continue
        cands = by_region.get(reg, [])
        a = b.norm(row["사업명"], *row["협의요청기관"].split())
        scored = [(difflib.SequenceMatcher(None, a, b.norm(s["servNm"], s["ctpvNm"], s["sggNm"])).ratio(), s) for s in cands]
        if not scored:
            continue
        sim, s = max(scored, key=lambda x: x[0])
        if sim < c.MIN_SIM:
            continue
        hit = [w for w in words if w in row["사업명"]]
        pools["T" if hit else "O"].append((row, s, sim, hit))
    print(f"낱말 {len(words)}개 · 짝 있는 사례 T {len(pools['T'])}건, O {len(pools['O'])}건 (뺀 협의ID {len(skip)}개)")
    rows, calls = [], 0
    for layer in ("T", "O"):
        random.Random(f"{SEED}-{layer}").shuffle(pools[layer])
        got = 0
        for row, s, sim, hit in pools[layer]:
            d = b.detail(s["servId"]); calls += 1
            tgt, crit, cnt = (d.get(k, "").strip() for k in ("sprtTrgtCn", "slctCritCn", "alwServCn"))
            if (tgt or crit) and cnt:
                rows.append({"협의ID": row["연번"], "협의요청기관": row["협의요청기관"], "신설변경": row["신설변경"], "협의 사업명": row["사업명"],
                             "복지로 servId": s["servId"], "복지로 사업명": s["servNm"], "이름유사도": f"{sim:.2f}",
                             "원문 지원대상": tgt, "원문 선정기준": crit, "원문 지원내용": cnt, "층": layer, "층낱말": " ".join(hit)})
                got += 1
            if got == c.N_PER:
                break
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}건 → {OUT} (상세 확인 {calls}건)")
    for r in rows:
        print(f"  [{r['층']}] {r['협의ID']} | {r['협의요청기관']} | {r['협의 사업명']} ↔ {r['복지로 사업명']} ({r['이름유사도']}) {r['층낱말']}")


if __name__ == "__main__":
    main()
