"""E2c: v4 시험용 새 협의 사례 40건(층 나눔)을 뽑는다. 시제품 출력은 쓰지 않는다.

사전등록: 30_analysis/v4_개선_사전등록.md §2 (11/6 고정)
  1. 협의완료_2025_부록1.csv 중 지자체 요청(대구·경북·중앙부처 제외), E2·E2b·E3에 쓴 협의ID 제외.
  2. 짝짓기는 E2b와 같다(make_e2b_cases.norm, 같은 시도·시군구, 유사도 0.7 이상 중 최고).
  3. 층: 2026 신속협의 유형 79개 사업명의 낱말(2글자 이상, 일반어 제외)이 협의 사업명에 하나라도 있으면 T, 없으면 O.
  4. 층마다 시드 20261106으로 섞고, 차례로 상세를 받아 지원대상(또는 선정기준)과 지원내용이 모두 있는 것을 20건씩.
  python -X utf8 scripts/make_e2c_cases.py
출력: data/labels/E2c_요건대조_사례.csv (E2b와 같은 열 + 층·층낱말)
"""
import csv
import difflib
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_e2b_cases as b  # noqa: E402  (norm, org_region, detail, 경로를 그대로 쓴다)

OUT = ROOT / "data/labels/E2c_요건대조_사례.csv"
TYPES = ROOT / "data/raw/신속협의_유형_2026.csv"
SEED, N_PER, MIN_SIM = 20261106, 20, 0.7
# 일반어(11/6 표본 뽑기 전에 고정): 급여 종류가 아니라 대상 집단·일반 명사라 거의 모든 사업명에 걸리는 낱말
STOP = {"지원", "사업", "지원사업", "비용", "서비스", "추가", "지원금", "이용료", "구입비", "본인부담금", "일반", "전체", "등", "및",
        "가구", "가정", "공공", "공영", "관리", "관리비", "관외", "교육", "노인", "부모", "아동", "청년", "청소년", "학생", "장애", "장애인",
        "이상", "제외", "포함", "미포함", "정도", "의료", "의료비", "의료기관", "이동", "준비", "촉진", "행복", "경비", "물품", "발급", "보증",
        "수리", "환자", "저소득", "취약계층", "자녀", "근로자", "중장년", "미취업", "치료", "치료비", "검사", "검사비", "시술", "수술", "병원",
        "생활안정", "문화", "여가", "결혼", "전입", "이사", "임차", "응시", "취득", "수강", "자립준", "중개수수", "이사비용지원"}


def type_words():
    words = set()
    for t in csv.DictReader(TYPES.open(encoding="utf-8-sig")):
        for w in re.split(r"[^가-힣A-Za-z]+", t["사업명"]):
            if len(w) >= 2 and w not in STOP:
                words.add(w)
                for s in ("지원", "비", "료"):          # '응시료'·'교통비'처럼 낱말 끝 일반어를 떼어도 2글자 이상이면 함께 쓴다
                    if w.endswith(s) and len(w) - len(s) >= 2 and w[: -len(s)] not in STOP:
                        words.add(w[: -len(s)])
    return sorted(words)


def used_ids():
    ids = set()
    for f in ["E2_정답표_고정_20261103.csv", "E2b_정답표_고정_20261103.csv", "E2_요건대조_라벨시트.csv", "E2b_요건대조_사례.csv"]:
        p = ROOT / "data/labels" / f
        if p.exists():
            ids |= {r["협의ID"] for r in csv.DictReader(p.open(encoding="utf-8-sig"))}
    ids |= {"419", "474", "393", "397", "434"}   # E3 시연 사례
    return ids


def main():
    words = type_words()
    services = list(csv.DictReader(b.LIST.open(encoding="utf-8-sig")))
    by_region = {}
    for s in services:
        key = b.SIDO_KEY.get(s["ctpvNm"], s["ctpvNm"])
        sgg = "" if s["sggNm"] in ("", s["ctpvNm"]) else s["sggNm"]
        by_region.setdefault((key, sgg), []).append(s)
    skip = used_ids()
    pools = {"T": [], "O": []}
    for c in csv.DictReader(b.CONSULT.open(encoding="utf-8-sig")):
        if c["연번"] in skip:
            continue
        reg = b.org_region(c["협의요청기관"])
        if not reg:
            continue
        cands = by_region.get(reg, [])
        a = b.norm(c["사업명"], *c["협의요청기관"].split())
        scored = [(difflib.SequenceMatcher(None, a, b.norm(s["servNm"], s["ctpvNm"], s["sggNm"])).ratio(), s) for s in cands]
        if not scored:
            continue
        sim, s = max(scored, key=lambda x: x[0])
        if sim < MIN_SIM:
            continue
        hit = [w for w in words if w in c["사업명"]]
        pools["T" if hit else "O"].append((c, s, sim, hit))
    print(f"낱말 {len(words)}개 · 짝 있는 사례 T {len(pools['T'])}건, O {len(pools['O'])}건")
    rows, calls = [], 0
    for layer in ("T", "O"):
        random.Random(f"{SEED}-{layer}").shuffle(pools[layer])
        got = 0
        for c, s, sim, hit in pools[layer]:
            d = b.detail(s["servId"]); calls += 1
            tgt, crit, cnt = (d.get(k, "").strip() for k in ("sprtTrgtCn", "slctCritCn", "alwServCn"))
            if (tgt or crit) and cnt:
                rows.append({"협의ID": c["연번"], "협의요청기관": c["협의요청기관"], "신설변경": c["신설변경"], "협의 사업명": c["사업명"],
                             "복지로 servId": s["servId"], "복지로 사업명": s["servNm"], "이름유사도": f"{sim:.2f}",
                             "원문 지원대상": tgt, "원문 선정기준": crit, "원문 지원내용": cnt, "층": layer, "층낱말": " ".join(hit)})
                got += 1
            if got == N_PER:
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
