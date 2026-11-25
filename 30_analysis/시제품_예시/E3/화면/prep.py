"""E3 시연 화면 데이터: 시제품 v3 실제 출력(30_analysis/시제품_예시/E3/*.json)을 화면용 JSON으로 옮긴다. 값을 새로 만들지 않는다."""
import csv
import json
from pathlib import Path

ROOT = Path(r"C:\Users\USER\Desktop\project\Contest\Data+AI")
OUT = Path(__file__).resolve().parent / "data.json"
CASES = [("419", "영천 청년 이사비"), ("474", "남구 어린이집 입학준비금"), ("393", "구미 청년 전월세 이자"),
         ("397", "구미 대상포진 예방접종"), ("434", "울진형 긴급복지"), ("S3", "가상 · 자격증 응시료")]
SELF = {"419": "WLF00005865", "393": "WLF00005696", "397": "WLF00006074", "434": "WLF00005878", "474": "WLF00006671"}

fast = {r["연번"]: r for r in csv.DictReader((ROOT / "data/raw/신속협의_유형_2026.csv").open(encoding="utf-8-sig"))}
kind = {r["연번"]: r["신설변경"] for r in csv.DictReader((ROOT / "data/raw/협의완료_2025_부록1.csv").open(encoding="utf-8-sig"))}
e2 = {r["협의ID"]: r for r in csv.DictReader((ROOT / "data/labels/E2_요건대조_라벨시트.csv").open(encoding="utf-8-sig"))}
gold = {r["협의ID"]: r for r in csv.DictReader((ROOT / "data/labels/E2_정답표_고정_20261103.csv").open(encoding="utf-8-sig"))}
gold.update({r["사례"]: r for r in csv.DictReader((ROOT / "data/labels/합성_정답표_고정_20261103.csv").open(encoding="utf-8-sig"))})

out = []
for cid, label in CASES:
    r = json.loads((ROOT / f"30_analysis/시제품_예시/E3/{cid}.json").read_text(encoding="utf-8"))
    v, ev, inp = r["v2"], r["eval"], r["input"]
    synth = cid.startswith("S")
    k = "" if synth else kind.get(cid, "")
    t = fast.get(v["type_no"])
    selfid = SELF.get(cid)
    groups, dropped_self = {}, None
    for g, items in r["similar_v3"]["groups"].items():
        lst = []
        for x in items:
            if x["servId"] == selfid:
                if k == "신설":  # 협의 뒤에 등록된 이 사업 자체: 신설 당시에는 없었다
                    dropped_self = x["사업명"]
                    continue
                x = {**x, "기존사업": True}
            lst.append(x)
        groups[g] = lst
    hist = [h for h in r["history"] if h["연번"] != cid]
    g = gold[cid]
    excl_kw = [f"{e['유형']}: {', '.join(e['일치어'])}" for e in r["exclude"]]
    region_hits = len(groups.get("같은 광역 본청", []))
    sgg = (inp["org"].split() + [""])[1] if inp["org"] else ""
    checklist = [
        ["1", "기초지방자치단체인가", "아니오(광역·교육청은 신속 대상 아님)" if sgg in ("본청",) or "교육청" in inp["org"] else "예", "지침 Ⅱ.5"],
        ["2", "신속협의 목록에 같은(유사) 사업이 있는가", f"{t['연번']}번 {t['사업명']}" if t else "없음 → 일반협의 경로", "신속협의 유형 79개(2026)"],
        ["3", "유사한 광역 사업이 있는가", f"후보 {region_hits}건" if region_hits else "AI가 찾은 후보 없음(원문 확인 필요)", "복지로 공개본"],
        ["4", "광역 사업과 중복을 없앴는가", "담당자 확인", ""],
        ["5", "대상·지원수준이 범위 안인가", f"대상 {v['대상판정'] or '-'} · 상한 {v['상한판정'] or '-'}" if t else "해당 없음", "유형 표와 대조"],
    ]
    quotes = [q for q in (v.get("type_evidence"), v.get("target_evidence"), v.get("dup_evidence"), v.get("exclude_evidence")) if q]
    out.append({
        "id": cid, "label": label, "synth": synth, "kind": k, "org": inp["org"] or "(기관 미기재 · 기초지자체로 가정)",
        "name": inp["name"], "srcText": inp["text"] if synth else None,
        "src": None if synth else {"지원대상": e2[cid]["원문 지원대상"], "선정기준": e2[cid]["원문 선정기준"], "지원내용": e2[cid]["원문 지원내용"]},
        "verdict": ev["유형판정"],
        "type": {"no": v["type_no"], "name": t["사업명"] if t else "", "field": t["분야"] if t else "", "target": t["대상"] if t else "",
                 "cap": t["지원수준(최대 상한)"] if t else "", "dup": t["중복·보충 조건"] if t else ""} ,
        "reason": v["type_reason"], "typeEvidence": v.get("type_evidence"),
        "alt": [f"{a}번 {fast[a]['사업명']}" for a in v.get("alt_types", []) if a in fast],
        "target": {"v": v["대상판정"], "why": v["근거"][0]}, "amount": {"v": v["상한판정"], "why": v["근거"][1]},
        "excluded": {"v": v["excluded"], "clause": v.get("exclude_clause"), "evidence": v.get("exclude_evidence"), "kw": excl_kw},
        "dup": {"v": v.get("중복위반"), "evidence": v.get("dup_evidence")},
        "checklist": checklist, "groups": groups, "candN": r["similar_v3"]["후보수"], "droppedSelf": dropped_self,
        "history": hist[:5], "historyDropped": len(hist) != len(r["history"]), "hold": r["hold"],
        "bokjiro": r["bokjiro"] if r["bokjiro"].get("servId") else None,
        "quotes": quotes,
        "gold": {"유형연번": g["유형연번"], "대상": g["대상"], "상한": g["상한"], "협의제외": g["협의제외"], "유형판정": g["유형판정"]},
    })
import re  # noqa: E402
# 원문의 한글 문서용 특수 글머리(사용자 정의 영역 문자, 예: U+F06D)는 글꼴에 없어 네모로 깨진다 → □로 바꾼다(원문·근거 구절 모두 같게)
OUT.write_text(re.sub("[-]", "□", json.dumps({"cases": out}, ensure_ascii=False)), encoding="utf-8")
print(len(out), "cases", OUT.stat().st_size, "bytes")
for c in out:
    print(c["id"], c["verdict"], "| gold", c["gold"]["유형판정"], "| self dropped", c["droppedSelf"], "| hist dropped", c["historyDropped"], "| F", bool(c["bokjiro"]))
