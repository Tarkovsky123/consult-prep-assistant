"""판정판 저장소(e2_labels)에서 내려받은 JSON을 정답표 CSV로 모은다.

1) ArtifactData list(collection="e2_labels", out_dir=<폴더>)로 문서를 내려받는다
2) python -X utf8 scripts/export_e2_labels.py <폴더>/e2_labels
출력: data/labels/E2_라벨_결과.csv (협의ID 순, 원본 사례 30건 기준)
E2b: python -X utf8 scripts/export_e2_labels.py <폴더>/e2b_labels --src data/labels/E2b_요건대조_사례.csv --out data/labels/E2b_라벨_결과.csv
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/labels/E2_요건대조_라벨시트.csv"
OUT = ROOT / "data/labels/E2_라벨_결과.csv"
COLS = [("동일", "same"), ("유형연번", "typeNo"), ("대상", "target"), ("상한", "amount"), ("협의제외", "excluded"),
        ("중복위반", "dup"), ("유형판정", "verdict"), ("자동판정", "verdictAuto"), ("직접고침", "override"),
        ("메모", "memo"), ("저장시각", "updatedAt")]


def main(folder, src=SRC, out=OUT):
    labels = {}
    for f in Path(folder).glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        labels[f.stem] = doc.get("data", doc)
    cases = list(csv.DictReader(Path(src).open(encoding="utf-8-sig")))
    with Path(out).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["협의ID", "협의요청기관", "협의 사업명"] + [k for k, _ in COLS])
        for c in cases:
            lab = labels.get(c["협의ID"], {})
            w.writerow([c["협의ID"], c["협의요청기관"], c["협의 사업명"]] + [lab.get(key) or "" for _, key in COLS])
    print(f"{len(cases)}건(저장소 문서 {len(labels)}개) → {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    main(a.folder, a.src, a.out)
