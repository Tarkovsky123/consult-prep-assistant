"""지자체 복지서비스 목록(복지로 등록 기준) 분석: 기존 태그 품질과 대구·경북 시군구별 대상 집단 공급 현황.

입력: data/raw/api/local_list.csv (fetch_local_services.py list), data/raw/수급권자_시군구_20251231.csv
출력: data/processed/local_tag_quality.json, data/processed/local_coverage_dg.csv
주의: '복지로에 등록된 지자체 사업'만 센다. 등록되지 않은 사업은 보이지 않는다(자료상 미관측 ≠ 실제 공급 없음).
"""
import io
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
FIN_WORDS = r"금융|대출|융자|이자|저축|신용|채무|통장|자산"
GROUPS = ["저소득", "장애인", "한부모·조손", "다문화·탈북민", "다자녀", "보훈대상자"]
LIFE = ["영유아", "아동", "청소년", "청년", "중장년", "노년", "임신 · 출산"]
# 수급권자 자료에서 대상 집단의 규모로 쓸 사업
DEMAND = {"저소득": "기초생활보장(맞춤형급여)", "장애인": "장애인연금", "노년": "기초연금"}


def tags(s):
    return [t.strip() for t in str(s).split(",") if t.strip()]


def tag_quality(d):
    themes = d["intrsThemaNmArray"].map(tags)
    fin_tag = themes.map(lambda t: "서민금융" in t)
    cash = d["srvPvsnNm"].str.contains("현금지급", na=False)
    name_fin = d["servNm"].str.contains(FIN_WORDS, na=False)
    return {
        "services": int(len(d)),
        "theme_counts": themes.explode().value_counts().to_dict(),
        "서민금융_태그_비율": round(fin_tag.mean(), 3),
        "서민금융_단독_태그_수": int((themes.map(lambda t: t == ["서민금융"])).sum()),
        "서민금융_태그_중_사업명에_금융어휘": round(name_fin[fin_tag].mean(), 3),
        "서민금융_태그_중_현금지급": round(cash[fin_tag].mean(), 3),
        "현금지급_사업_중_서민금융_태그": round(fin_tag[cash].mean(), 3),
        "가구상황_태그_빈_비율": round((d["trgterIndvdlNmArray"].fillna("") == "").mean(), 3),
        "생애주기_태그_빈_비율": round((d["lifeNmArray"].fillna("") == "").mean(), 3),
    }


def demand_table():
    raw = (RAW / "수급권자_시군구_20251231.csv").read_bytes()
    need = pd.read_csv(io.BytesIO(raw), encoding="cp949")
    need = need[need["시도"].isin(["대구광역시", "경상북도"])]
    # 일반구로 나뉜 포항시는 시 단위로 합친다(목록의 sggNm 이 '포항시')
    need["sgg"] = need["시군구"].map(lambda s: re.sub(r"^(포항시).+구$", r"\1", re.sub(r"\s+", "", s)))
    pv = need.pivot_table(index=["시도", "sgg"], columns="사업명", values="수급권자수", aggfunc="sum")
    return pv[[c for c in DEMAND.values() if c in pv.columns]]


def coverage(d):
    dg = d[d["ctpvNm"].isin(["대구광역시", "경상북도"])].copy()
    dg["sgg"] = dg["sggNm"].fillna("").str.strip()
    region_wide = dg[(dg["sgg"] == "") | dg["sgg"].str.contains("교육청") | (dg["sgg"] == "-")]
    local = dg.drop(region_wide.index)
    rows = []
    for (sido, sgg), g in local.groupby(["ctpvNm", "sgg"]):
        rec = {"시도": sido, "시군구": sgg, "등록_사업수": len(g)}
        for grp in GROUPS:
            rec[f"가구_{grp}"] = int(g["trgterIndvdlNmArray"].map(lambda s: grp in tags(s)).sum())
        for life in LIFE:
            rec[f"생애_{life}"] = int(g["lifeNmArray"].map(lambda s: life in tags(s)).sum())
        rows.append(rec)
    cov = pd.DataFrame(rows).set_index(["시도", "시군구"])
    dem = demand_table()
    dem.index = dem.index.set_names(["시도", "시군구"])
    cov = cov.join(dem, how="left")
    wide = region_wide.groupby("ctpvNm").size().to_dict()
    return cov, {k: int(v) for k, v in wide.items()}


def structured_households(path):
    """구조화 결과(structure_services.py)의 가구상황을 servId → 집합으로. 없으면 빈 dict."""
    if not path.exists():
        return {}
    out = {}
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        if row["output"]:
            out[row["id"]] = set(row["output"]["household"])
    return out


def tag_vs_structured(d, hh):
    """대구·경북 시군구별로 '태그 기준 0건'인 대상 집단이 구조화 기준으로는 몇 건인지 비교한다."""
    dg = d[d["ctpvNm"].isin(["대구광역시", "경상북도"]) & (d["sggNm"].str.strip() != "")
           & ~d["sggNm"].str.contains("교육청") & (d["sggNm"] != "-")]
    rows = []
    for (sido, sgg), g in dg.groupby(["ctpvNm", "sggNm"]):
        for grp in GROUPS:
            by_tag = int(g["trgterIndvdlNmArray"].map(lambda s: grp in tags(s)).sum())
            by_llm = int(g["servId"].map(lambda i: grp in hh.get(i, set())).sum())
            rows.append({"시도": sido, "시군구": sgg, "대상": grp, "태그_기준": by_tag, "구조화_기준": by_llm})
    return pd.DataFrame(rows)


def main():
    d = pd.read_csv(RAW / "api/local_list.csv", encoding="utf-8-sig", dtype=str).fillna("")
    quality = tag_quality(d)
    cov, wide = coverage(d)
    zero = {c: sorted(f"{s} {g}" for (s, g) in cov.index[cov[c] == 0]) for c in cov.columns if c.startswith("가구_")}
    quality["대구경북_시도·교육청_단위_사업수"] = wide
    quality["대구경북_시군구_수"] = int(len(cov))
    quality["대구경북_대상집단_등록사업_0건_시군구"] = zero
    hh = structured_households(OUT / "structured_local_codex.jsonl")
    if hh:
        cmp_ = tag_vs_structured(d, hh)
        cmp_.to_csv(OUT / "local_tag_vs_structured_dg.csv", encoding="utf-8-sig", index=False)
        tag_zero = cmp_[cmp_["태그_기준"] == 0]
        quality["태그0건_칸"] = int(len(tag_zero))
        quality["태그0건_칸_중_구조화로는_1건이상"] = int((tag_zero["구조화_기준"] > 0).sum())
        quality["구조화로도_0건_칸"] = int((cmp_["구조화_기준"] == 0).sum())
        quality["대상별_태그0건→구조화1건이상"] = (tag_zero.assign(found=tag_zero["구조화_기준"] > 0)
                                          .groupby("대상")["found"].agg(["sum", "count"]).astype(int)
                                          .apply(lambda r: f"{r['sum']}/{r['count']}", axis=1).to_dict())
    OUT.mkdir(parents=True, exist_ok=True)
    cov.to_csv(OUT / "local_coverage_dg.csv", encoding="utf-8-sig")
    (OUT / "local_tag_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in quality.items() if k != "theme_counts"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
