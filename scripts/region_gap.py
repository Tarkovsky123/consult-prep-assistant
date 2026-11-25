"""시군구별 취약계층 수요 대비 사회서비스 제공기관 수 (1차 분석).

입력: data/raw/ 의 SSiS 공개 CSV 2종
  - 수급권자_시군구_20251231.csv  (행복이음 복지사업 시군구별 수급권자, 2025-12)
  - 사회서비스_제공기관수_시군구_20260116.csv  (시군구별 전자바우처 제공기관 수)
출력: data/processed/region_gap.csv, data/processed/region_gap_summary.json

실행: python -X utf8 scripts/region_gap.py
"""
import io
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"

# 취약계층 수요 대리지표: 아래 자격의 수급권자 수 합 (한 사람이 여러 자격을 가지면 중복 집계될 수 있음)
NEED_COLS = ["기초생활보장(맞춤형급여)", "차상위장애인", "장애인연금"]


def read_csv(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없음: {path}")


def split_city(sido, sgg):
    """도 소속 시의 일반구('고양시덕양구')는 시 이름도 돌려준다. 광역시의 구는 그대로 둔다."""
    sgg = re.sub(r"\s+", "", str(sgg))
    m = re.match(r"^(.+?시)(.+구)$", sgg) if sido.endswith("도") else None
    return sido.strip(), sgg, (m.group(1) if m else sgg)


def harmonize(frames):
    """두 자료의 행정구역 단위를 맞춘다: 한쪽이라도 일반구로 나뉜 시는 양쪽 모두 시 단위로 합친다."""
    for df in frames:
        parts = [split_city(s, g) for s, g in zip(df["시도"], df["시군구"])]
        df["sido"], df["sgg"], df["city"] = zip(*parts)
    split = {(s, c) for df in frames for s, g, c in zip(df["sido"], df["sgg"], df["city"]) if g != c}
    for df in frames:
        df["region"] = [f"{s} {c if (s, c) in split else g}" for s, g, c in zip(df["sido"], df["sgg"], df["city"])]
    return split


def main():
    need = read_csv(RAW / "수급권자_시군구_20251231.csv")
    prov = read_csv(RAW / "사회서비스_제공기관수_시군구_20260116.csv")
    prov[["시도", "시군구"]] = prov["시군구명"].str.strip().str.split(r"\s+", n=1, expand=True)
    prov["시군구"] = prov["시군구"].fillna(prov["시도"])  # 세종특별자치시처럼 시군구가 없는 경우
    merged_cities = harmonize([need, prov])

    pivot = need.pivot_table(index="region", columns="사업명", values="수급권자수", aggfunc="sum")
    providers = prov.groupby("region")["제공기관수"].sum()
    unmatched = sorted(set(pivot.index) ^ set(providers.index))
    df = pivot.join(providers, how="inner")
    df["취약수요"] = df[NEED_COLS].fillna(0).sum(axis=1)
    df["노인수요_기초연금"] = df["기초연금"]
    df["기관_per_취약1천명"] = df["제공기관수"] / df["취약수요"] * 1000
    ratio = df["기관_per_취약1천명"]
    df["전국_백분위"] = ratio.rank(pct=True).round(3)

    dg = df[df.index.str.startswith(("대구", "경상북도"))]
    summary = {
        "기준": {"수급권자": "2025-12", "제공기관": "2026-01-16 등록"},
        "지역_수": int(len(df)),
        "시_단위로_합친_시": sorted(f"{s} {c}" for s, c in merged_cities),
        "매칭_안된_지역": unmatched,
        "기관_per_취약1천명": {k: round(float(v), 2) for k, v in ratio.describe().items()},
        "P90_P10_배율": round(float(ratio.quantile(0.9) / ratio.quantile(0.1)), 2),
        "최대_최소_배율": round(float(ratio.max() / ratio.min()), 1),
        "제공기관_10곳_이하_지역": sorted(df.index[df["제공기관수"] <= 10]),
        "하위10": df.sort_values("기관_per_취약1천명").head(10)[["제공기관수", "취약수요", "기관_per_취약1천명"]]
                   .round(2).reset_index().to_dict("records"),
        "대구경북": {
            "지역_수": int(len(dg)),
            "전국_하위25%_이하": sorted(dg.index[dg["기관_per_취약1천명"] <= ratio.quantile(0.25)]),
            "전국_하위10%_이하": sorted(dg.index[dg["기관_per_취약1천명"] <= ratio.quantile(0.10)]),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    df.round(3).to_csv(OUT / "region_gap.csv", encoding="utf-8-sig")
    (OUT / "region_gap_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
