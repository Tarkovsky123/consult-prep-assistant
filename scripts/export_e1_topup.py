"""E1 추가 판정판 저장소(e1_topup)의 JSON을 (협의ID, servId) 정답표로 고정한다. AI 판정·묶음 열은 넣지 않는다.

1) ArtifactData list(collection="e1_topup", out_dir=<폴더>)
2) python -X utf8 scripts/export_e1_topup.py <폴더>/e1_topup
출력: data/labels/E1추가_정답표_고정_<오늘>.csv (후보 순서는 data/processed/e1_topup_candidates.csv) + sha256 앞 16자리
"""
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/processed/e1_topup_candidates.csv"


def main(folder):
    labs = {f.stem: (lambda d: d.get("data", d))(json.loads(f.read_text(encoding="utf-8"))) for f in Path(folder).glob("*.json")}
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        lab = labs.get(r["협의ID"], {})
        v = (lab.get("cand") or {}).get(r["복지로 servId"], "")
        if not v:
            raise SystemExit(f"판정 빈칸: {r['협의ID']} {r['복지로 servId']}")
        out.append({"협의ID": r["협의ID"], "협의 사업명": r["협의 사업명"], "복지로 servId": r["복지로 servId"], "복지로 사업명": r["복지로 사업명"],
                    "시도": r["시도"], "시군구": r["시군구"], "판정": v, "메모": lab.get("memo") or ""})
    dest = ROOT / f"data/labels/E1추가_정답표_고정_{datetime.now():%Y%m%d}.csv"
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)}행 · 사례 {len({o['협의ID'] for o in out})} · 판정 {dict(Counter(o['판정'] for o in out))} → {dest}")
    print("sha256 앞 16자리", hashlib.sha256(dest.read_bytes()).hexdigest()[:16])


if __name__ == "__main__":
    main(sys.argv[1])
