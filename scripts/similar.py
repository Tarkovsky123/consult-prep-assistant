"""유사사업 후보 만들기·AI 판정(E1 측정과 시제품 v3가 함께 쓴다).

- b2_rank: 풀을 만들 때 쓴 '태그필터+키워드'(11/3 이전 세션 코드 그대로)
- e1_instruction: 판정기준_E1_E2.md §3.1·3.2·3.3(앞 다섯 항목). clarify=True면 v3 보완 문구를 덧붙인다
- judge_similar: 후보마다 동일·유사·무관 + 근거 한 줄. 결과는 out_path에 캐시한다
- decompose=True(v4 C3, 11/7): LLM은 목적·대상·형태를 따로 답하고 판정은 decide()가 판정기준 §3.2대로 정한다
"""
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAIL = ROOT / "data/raw/api/local_detail"
CRITERIA = ROOT / "data/labels/판정기준_E1_E2.md"

# v3 보완: (C) 추가 판정에서 같은 지자체·광역 후보의 AI 양성 정밀도가 5/15였다. 판정기준 §3.2(무관 = 목적이 다르다)를 다시 강조한다.
E1_CLARIFY = ("\n- 같은 지자체·같은 광역의 사업이라는 이유만으로 유사로 보지 않는다. 목적이 같거나 일부 겹칠 때만 유사다. "
              "대상 집단만 같고 목적이 다르면 무관이다.\n")


def norm(s):
    return re.sub(r"[\s\(\)\[\]·ㆍ,\.\-_/「」『』]", "", re.sub(r"^\(.*?\)\s*|^\[.*?\]\s*", "", s))


def region(org):
    t = org.split()
    return (t[0] if t else ""), ("" if len(t) < 2 or t[1] == "본청" else t[1])


def relation(org, l):
    """협의 기관과 후보 사업의 지역 관계."""
    sido, sgg = region(org)
    if l["ctpvNm"] != sido:
        return "다른 시도"
    if (l["sggNm"] or "") == sgg:
        return "같은 지자체"
    if not l["sggNm"]:
        return "같은 광역 본청"
    return "같은 시도"


B2_STOP = {"지원", "사업", "지원사업", "지급", "운영", "확대", "신설", "변경", "경산시", "군위군", "대구", "경북", "경상북도", "대구광역시"}
B2_LIFE = {"청년": "청년", "노인": "노년", "어르신": "노년", "장수": "노년", "아동": "아동", "영유아": "영유아", "출산": "임신·출산", "임신": "임신·출산",
           "산모": "임신·출산", "청소년": "청소년", "중장년": "중장년"}
B2_HH = {"다자녀": "다자녀", "장애": "장애인", "한부모": "한부모·조손", "저소득": "저소득", "수급": "저소득", "다문화": "다문화·탈북민", "보훈": "보훈대상자", "참전": "보훈대상자"}


def b2_toks(s):
    out = []
    for w in re.findall(r"[가-힣A-Za-z0-9]+", re.sub(r"^\(.*?\)\s*|^\[.*?\]\s*", "", s)):
        w = re.sub(r"(지원사업|사업|지원|지급|비용|비)$", "", w) or w
        if len(w) >= 2 and w not in B2_STOP:
            out.append(w)
    return out


def b2_rank(org, name, loc):
    sgg, kws = (org.split() or [""])[-1], b2_toks(name)
    life = [v for k, v in B2_LIFE.items() if k in name]
    hh = [v for k, v in B2_HH.items() if k in name]
    scored = []
    for i, l in enumerate(loc):
        tagok = (not life and not hh) or any(v in l["lifeNmArray"] for v in life) or any(v in l["trgterIndvdlNmArray"] for v in hh)
        kw = sum(1 for w in kws if w in l["servNm"])
        if tagok and kw > 0:
            scored.append((kw, l["sggNm"] == sgg, i))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [i for _, _, i in scored]


def cand_text(l):
    p = DETAIL / f"{l['servId']}.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    out = {"사업명": l["servNm"], "지역": (l["ctpvNm"] + " " + (l["sggNm"] or "(도·시 본청)")).strip(), "요약": l["servDgst"]}
    if d.get("sprtTrgtCn"):
        out["지원대상"] = d["sprtTrgtCn"]
    if d.get("alwServCn"):
        out["지원내용"] = d["alwServCn"]
    return out


def e1_instruction(clarify=False):
    t = CRITERIA.read_text(encoding="utf-8")
    sec = t.split("### 3.1 세 가지를 본다")[1].split("- **요약이 짧아 판단할 수 없으면**")[0]
    return ("지자체 사회보장 신설·변경 협의를 준비하는 담당자를 돕는다. '협의 사업' 하나와 복지로에 등록된 '후보' 사업들이 주어진다.\n"
            "후보마다 묻는다: 이 후보를 협의 요청서 4절 '기존 제도와의 관계'에 비교 대상으로 적어야 하는가? 적어야 하면 동일 또는 유사, 적을 필요가 없으면 무관이다.\n"
            "후보마다 판정 하나와 근거 한 줄(목적·대상 집단·급여 형태 중 무엇이 같고 무엇이 다른지)을 낸다. 모든 후보를 빠짐없이 한 번씩 판정한다.\n\n"
            "### 세 가지를 본다" + sec + (E1_CLARIFY if clarify else ""))


E1_DECOMPOSE = ("\n### 답하는 방법(세 요소를 따로)\n"
                "- 먼저 협의 사업의 목적(어떤 필요·위험에 대응하나)을 한 구절로 적는다.\n"
                "- 후보마다 후보의 목적을 한 구절로 적고, 목적이 협의 사업과 '같음'·'일부 겹침'·'다름' 중 무엇인지 답한다. "
                "대상 집단이 같다는 것만으로, 또는 급여 형태(현금·의료비·바우처 등)가 같다는 것만으로 목적이 같은 것은 아니다. "
                "같은 지자체·같은 광역의 사업이라는 것도 목적과 상관없다.\n"
                "- 대상 집단과 급여 형태가 각각 협의 사업과 '같음'인지 '다름'인지 답한다.\n"
                "- 판정은 코드가 정한다: 목적이 다름이면 무관, 목적이 같음·일부 겹침이고 대상·형태가 모두 같음이면 동일, 그 밖은 유사.\n")


def decide(purpose, target, form):
    if purpose == "다름":
        return "무관"
    return "동일" if purpose == "같음" and target == "같음" and form == "같음" else "유사"


def judge_similar(proj, cands, loc_by_id, out_path, seed_key, clarify=False, backend="codex", decompose=False):
    """proj: 협의 사업(기관·사업명·신설변경, 원문이 있으면 지원대상·선정기준·지원내용). 후보 순서는 seed_key로 섞는다."""
    from llm import ask, CODEX_MODEL
    out_path = Path(out_path)
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    ids = list(cands)
    random.Random(seed_key).shuffle(ids)
    keys = {f"c{n + 1}": sid for n, sid in enumerate(ids)}
    payload = {"협의 사업": proj, "후보": [{"id": k, **cand_text(loc_by_id[s])} for k, s in keys.items()]}
    if decompose:
        same = {"type": "string", "enum": ["같음", "다름"]}
        item = {"type": "object", "additionalProperties": False, "required": ["id", "후보_목적", "목적", "대상", "형태", "근거"],
                "properties": {"id": {"type": "string", "enum": list(keys)}, "후보_목적": {"type": "string"},
                               "목적": {"type": "string", "enum": ["같음", "일부 겹침", "다름"]}, "대상": same, "형태": same, "근거": {"type": "string"}}}
        schema = {"type": "object", "additionalProperties": False, "required": ["협의_목적", "judgments"],
                  "properties": {"협의_목적": {"type": "string"}, "judgments": {"type": "array", "items": item}}}
        res, sec = ask(backend, e1_instruction(True) + E1_DECOMPOSE, payload, schema)
        got = {j["id"]: {**j, "판정": decide(j["목적"], j["대상"], j["형태"])} for j in res["judgments"]}
    else:
        schema = {"type": "object", "additionalProperties": False, "required": ["judgments"],
                  "properties": {"judgments": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "판정", "근거"],
                                                                          "properties": {"id": {"type": "string", "enum": list(keys)},
                                                                                         "판정": {"type": "string", "enum": ["동일", "유사", "무관"]},
                                                                                         "근거": {"type": "string"}}}}}}
        res, sec = ask(backend, e1_instruction(clarify), payload, schema)
        got = {j["id"]: j for j in res["judgments"]}
    keep = ("판정", "근거", "후보_목적", "목적", "대상", "형태")
    rec = {"sec": round(sec, 1), "n": len(keys), "clarify": clarify, "decompose": decompose, "model": CODEX_MODEL if backend == "codex" else backend,
           "협의_목적": res.get("협의_목적") if decompose else None,
           "labels": {s: {f: got[k][f] for f in keep if f in got[k]} for k, s in keys.items() if k in got},
           "missing": [s for k, s in keys.items() if k not in got]}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec
