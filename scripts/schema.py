"""복지사업 지원조건 표준 스키마.

생애주기·가구상황은 복지로 태그 체계를 따르고(기존 태그와 비교할 수 있게),
태그에 없는 소득 기준·연령·지역 요건·지원 형태·조건 논리를 근거 구절과 함께 뽑는다.
근거(*_evidence, conditions[].evidence)는 원문에 그대로 있는 구절이어야 하며, verify_evidence 가 검사한다.
"""
import re

LIFE = ["영유아", "아동", "청소년", "청년", "중장년", "노년", "임신·출산"]
HOUSEHOLD = ["저소득", "장애인", "한부모·조손", "다문화·탈북민", "다자녀", "보훈대상자", "1인가구", "기타"]
INCOME = ["기초생활수급", "차상위", "중위소득기준", "기타소득기준", "소득무관", "미상"]
REGION = ["거주지한정", "지역무관", "미상"]
FORM = ["현금", "현물", "바우처·이용권", "서비스", "감면", "융자", "기타"]

EVAL_FIELDS = ["life", "household", "income_type", "income_median_pct", "region_type", "support_form"]

_nullable = lambda t: {"type": [t, "null"]}

ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "life", "age_min", "age_max", "age_evidence", "household", "income_type",
                 "income_median_pct", "income_evidence", "region_type", "region_name", "region_evidence",
                 "support_form", "conditions", "unknown_fields"],
    "properties": {
        "id": {"type": "string"},
        "life": {"type": "array", "items": {"type": "string", "enum": LIFE}},
        "age_min": _nullable("integer"),
        "age_max": _nullable("integer"),
        "age_evidence": _nullable("string"),
        "household": {"type": "array", "items": {"type": "string", "enum": HOUSEHOLD}},
        "income_type": {"type": "string", "enum": INCOME},
        "income_median_pct": _nullable("integer"),
        "income_evidence": _nullable("string"),
        "region_type": {"type": "string", "enum": REGION},
        "region_name": _nullable("string"),
        "region_evidence": _nullable("string"),
        "support_form": {"type": "array", "items": {"type": "string", "enum": FORM}},
        "conditions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "join", "exception", "evidence"],
            "properties": {"text": {"type": "string"}, "join": {"type": "string", "enum": ["AND", "OR"]},
                           "exception": {"type": "boolean"}, "evidence": {"type": "string"}}}},
        "unknown_fields": {"type": "array", "items": {"type": "string"}},
    },
}

BATCH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
                "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}}}

INSTRUCTION = f"""복지사업 설명문에서 지원조건을 표준 항목으로 뽑는다. 입력의 모든 id에 대해 하나씩, 빠짐없이 돌려준다.
규칙:
- 원문에 근거가 있는 것만 채운다. 근거가 없으면 빈 목록, null, '미상'으로 두고 그 항목 이름을 unknown_fields에 적는다. 추측하지 않는다.
- *_evidence 와 conditions[].evidence 는 원문에서 그대로 복사한 짧은 구절(가능하면 40자 이내)이다. 말을 바꾸거나 요약하지 않는다.
- life: 대상 생애주기 {LIFE}. 학생 학년이 나오면 해당 생애주기(초등=아동, 중·고=청소년, 대학=청년)로 본다.
- household: 대상 가구 상황 {HOUSEHOLD}. 수급자·차상위·저소득층이 대상이면 '저소득'을 넣는다.
- income_type: 소득 자격. 기초생활수급자만이면 '기초생활수급', 차상위 이하면 '차상위', 기준중위소득 %로 정하면 '중위소득기준'(income_median_pct에 숫자), 그 밖의 소득 기준은 '기타소득기준', 소득 제한이 없다고 밝히면 '소득무관', 언급이 없으면 '미상'.
- region_type: 특정 지역 거주자만 대상이면 '거주지한정'(region_name에 지역명), 전국 대상이라고 밝히면 '지역무관', 언급이 없으면 '미상'.
- support_form: 지원 형태 {FORM}.
- conditions: 자격 조건을 하나씩 나열한다. 모두 충족해야 하면 AND, 그중 하나면 OR, 제외 대상·예외 규정이면 exception=true.
"""


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def verify_evidence(item, source_text):
    """근거 구절이 원문에 그대로 있는지 검사한다(공백 차이는 무시). 실패한 항목 이름을 돌려준다."""
    src = norm_ws(source_text)
    failed = []
    for key in ("age_evidence", "income_evidence", "region_evidence"):
        ev = item.get(key)
        if ev and norm_ws(ev) not in src:
            failed.append(key)
    for i, c in enumerate(item.get("conditions", [])):
        if c.get("evidence") and norm_ws(c["evidence"]) not in src:
            failed.append(f"conditions[{i}]")
    return failed
