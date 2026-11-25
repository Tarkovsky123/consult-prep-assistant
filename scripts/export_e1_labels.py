"""E1 판정판 저장소(e1_labels)와 재확인판 저장소(e1_recheck)의 JSON을 (협의ID, servId) 정답표로 모은다.

1) ArtifactData list(collection="e1_labels", out_dir=<폴더>) / list(collection="e1_recheck", out_dir=<폴더>)
2) python -X utf8 scripts/export_e1_labels.py <폴더>/e1_labels --out data/labels/E1_라벨_재확인전_20261103.csv
   python -X utf8 scripts/export_e1_labels.py <폴더>/e1_labels --recheck <폴더>/e1_recheck --freeze
출력: 원본 후보 704행 순서 그대로. 방식·점수 열은 넣지 않는다(측정 스크립트가 원본 CSV와 다시 잇는다).
--freeze 이면 data/labels/E1_정답표_고정_<오늘>.csv 를 쓰고 sha256 앞 16자리를 출력한다.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/labels/E1_유사쌍_후보.csv"
POS = ("동일", "유사")


def load(folder):
    if not folder:
        return {}
    return {f.stem: (lambda d: d.get("data", d))(json.loads(f.read_text(encoding="utf-8"))) for f in Path(folder).glob("*.json")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--recheck")
    ap.add_argument("--out", default=str(ROOT / "data/labels/E1_라벨_결과.csv"))
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    labs, re = load(a.labels), load(a.recheck)
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        cid, sid = r["협의ID"], r["복지로 servId"]
        first = (labs.get(cid, {}).get("cand") or {}).get(sid, "")
        again = (re.get(cid, {}).get("cand") or {}).get(sid, "")
        memo = " / ".join(m for m in ((labs.get(cid) or {}).get("memo"), (re.get(cid) or {}).get("memo")) if (m or "").strip())
        out.append({"협의ID": cid, "협의요청기관": r["협의요청기관"], "협의 사업명": r["협의 사업명"], "복지로 servId": sid,
                    "시도": r["시도"], "시군구": r["시군구"], "복지로 사업명": r["복지로 사업명"],
                    "판정": again or first, "처음판정": first, "재확인": again, "메모": memo})
    by_case = Counter(o["협의ID"] for o in out if o["판정"] in POS)
    for o in out:
        o["후보없음"] = "" if by_case[o["협의ID"]] else "Y"
    blank = [(o["협의ID"], o["복지로 servId"]) for o in out if not o["판정"]]
    if blank:
        raise SystemExit(f"판정 빈칸 {len(blank)}개: {blank[:5]}")
    dest = ROOT / f"data/labels/E1_정답표_고정_{datetime.now():%Y%m%d}.csv" if a.freeze else Path(a.out)
    cols = ["협의ID", "협의요청기관", "협의 사업명", "복지로 servId", "시도", "시군구", "복지로 사업명", "판정", "후보없음", "처음판정", "재확인", "메모"]
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    changed = [(o["협의ID"], o["복지로 사업명"], o["처음판정"], o["재확인"]) for o in out if o["재확인"] and o["재확인"] != o["처음판정"]]
    print(f"{len(out)}행 · 사례 {len({o['협의ID'] for o in out})} · 판정 {dict(Counter(o['판정'] for o in out))} · 유사쌍 {sum(o['판정'] in POS for o in out)} → {dest}")
    print(f"재확인 {sum(1 for o in out if o['재확인'])}개 중 바뀐 것 {len(changed)}개", *changed, sep="\n  ")
    if a.freeze:
        print("sha256 앞 16자리", hashlib.sha256(dest.read_bytes()).hexdigest()[:16])


if __name__ == "__main__":
    main()
