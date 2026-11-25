"""E2b: 대구·경북 밖 2025 협의완료 사례에서 v2 평가용 새 사례 20건을 뽑는다(시제품 출력은 쓰지 않음).

절차(11/3 고정):
  1. 협의완료_2025_부록1.csv 중 지자체 요청(대구·경북·중앙부처 제외)만 남긴다.
  2. 같은 시도·같은 시군구(본청이면 시군구 없음)의 복지로 지자체 서비스(local_list.csv)와 사업명 유사도를 잰다.
     유사도 = difflib 비율, 지역명·띄어쓰기·'지원/사업' 접미어를 뺀 이름끼리. 0.7 이상 중 가장 비슷한 것 하나를 짝으로 둔다.
  3. 짝이 있는 사례를 시드 20261104로 섞고, 차례로 상세(원문)를 받아 지원대상(또는 선정기준)과 지원내용이 모두 있는 것만 20건 모은다.
  python -X utf8 scripts/make_e2b_cases.py
출력: data/labels/E2b_요건대조_사례.csv (E2 라벨시트와 같은 열 이름)
"""
import csv
import difflib
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_local_services import call, element_to_dict  # noqa: E402

CONSULT = ROOT / "data/raw/협의완료_2025_부록1.csv"
LIST = ROOT / "data/raw/api/local_list.csv"
CACHE = ROOT / "data/raw/api/local_detail"
OUT = ROOT / "data/labels/E2b_요건대조_사례.csv"
SEED, N, MIN_SIM = 20261104, 20, 0.7
EXCLUDE = {"대구광역시", "경상북도"}
SIDO_KEY = {"전라남도": "전남광주", "광주광역시": "전남광주", "전남광주통합특별시": "전남광주", "세종특별자치시세종특별자치시": "세종특별자치시"}
SIDOS = {"서울특별시", "부산광역시", "인천광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도",
         "충청남도", "전북특별자치도", "전라남도", "광주광역시", "경상남도", "제주특별자치도", "세종특별자치시세종특별자치시"}


def short(region):
    return re.sub(r"(특별자치도|특별자치시|광역시|특별시|도|시|군|구)$", "", region)


def norm(name, *regions):
    for r in regions:
        if r:
            name = name.replace(r, "").replace(short(r), "") if len(short(r)) >= 2 else name.replace(r, "")
    name = re.sub(r"[\s·ㆍ,()\[\]「」'\"]", "", name)
    return re.sub(r"(지원사업|사업|지원)$", "", re.sub(r"(지원사업|사업)$", "", name))


def org_region(org):
    t = org.split()
    if not t or t[0] not in SIDOS or t[0] in EXCLUDE or len(t) > 2:
        return None
    return SIDO_KEY.get(t[0], t[0]), (t[1] if len(t) == 2 and t[1] != "본청" else "")


def detail(serv_id):
    p = CACHE / f"{serv_id}.json"
    if not p.exists():
        root = call("LcgvWelfaredetailed", servId=serv_id)
        body = root.find(".//body")
        p.write_text(json.dumps(element_to_dict(body if body is not None else root), ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.1)
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    services = list(csv.DictReader(LIST.open(encoding="utf-8-sig")))
    by_region = {}
    for s in services:
        key = SIDO_KEY.get(s["ctpvNm"], s["ctpvNm"])
        sgg = "" if s["sggNm"] in ("", s["ctpvNm"]) else s["sggNm"]
        by_region.setdefault((key, sgg), []).append(s)
    pool = []
    for c in csv.DictReader(CONSULT.open(encoding="utf-8-sig")):
        reg = org_region(c["협의요청기관"])
        if not reg:
            continue
        cands = by_region.get(reg, [])
        a = norm(c["사업명"], *c["협의요청기관"].split())
        scored = [(difflib.SequenceMatcher(None, a, norm(s["servNm"], s["ctpvNm"], s["sggNm"])).ratio(), s) for s in cands]
        if scored:
            sim, s = max(scored, key=lambda x: x[0])
            if sim >= MIN_SIM:
                pool.append((c, s, sim))
    print(f"짝 있는 사례 {len(pool)}건(유사도 {MIN_SIM} 이상)")
    random.Random(SEED).shuffle(pool)
    rows = []
    for c, s, sim in pool:
        d = detail(s["servId"])
        tgt, crit, cnt = (d.get(k, "").strip() for k in ("sprtTrgtCn", "slctCritCn", "alwServCn"))
        if (tgt or crit) and cnt:
            rows.append({"협의ID": c["연번"], "협의요청기관": c["협의요청기관"], "신설변경": c["신설변경"], "협의 사업명": c["사업명"],
                         "복지로 servId": s["servId"], "복지로 사업명": s["servNm"], "이름유사도": f"{sim:.2f}",
                         "원문 지원대상": tgt, "원문 선정기준": crit, "원문 지원내용": cnt})
        if len(rows) == N:
            break
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}건 → {OUT}")
    for r in rows:
        print(f"  {r['협의ID']} | {r['협의요청기관']} | {r['협의 사업명']} ↔ {r['복지로 사업명']} ({r['이름유사도']})")


if __name__ == "__main__":
    main()
