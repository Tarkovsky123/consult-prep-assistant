"""협의 준비 보조 시제품 v1 (2026-11-02 밤; v0.1 위에 LLM 추출·중앙부처 대조·조건 차이를 더함).

사업안 하나를 넣으면
  0. (v1) 자유 서술 사업안(--text)에서 대상·내용·기준·금액·주기·소득·지역과 표준 조건을 LLM으로 뽑고, 근거 구절을 원문과 대조
  A. 협의제외 후보(2026 지침 Ⅱ.3 키워드 규칙, 쪽수 표시)
  B. 신속협의 유형 후보(data/raw/신속협의_유형_2026.csv)와 금액·소득 상한 대조
  C. 유사사업 후보(복지로 지자체 서비스 4,828건, 문자 2-gram TF-IDF; 같은 시군구·같은 시도 별도)
     + (v1) 중앙부처 복지서비스 461건 후보(이름·요약 기준), 구조화된 지자체 후보와의 조건 차이
  D. 관련 협의 이력(2025 협의완료 부록 1,146건, 이름 유사도)
  E. 보류 항목(입력 누락, 광역 중복 미확인 등)
  F. 복지로 등록 초안·현행화 차이표(6절 환류: 같은 조건이 복지로 등록 항목의 초안이 되고, 기존 등록본과의 차이를 보임)
을 서식 1-2 체크리스트·서식 1-1 자가진단 ② 초안 형태의 마크다운으로 낸다.
(v2, --v2) 유형 고르기와 협의제외를 LLM이 79개 유형 전체·지침 Ⅱ.3 목록과 대조해 근거 구절과 함께 정한다. 대상·상한 대조는 v1 규칙 그대로.
(v3, --v3) v2 + 고른 유형의 대상 조건(지역·자격 등 숫자 규칙이 못 읽는 것)과 중복·보충 조건 위반을 LLM이 근거와 함께 본다.
    유사사업은 AI가 동일·유사·무관으로 판정해 같은 지자체 / 같은 광역 본청 / 같은 시도 / 다른 시도로 묶는다(scripts/similar.py).

판정은 하지 않는다. 명시한 인자(--target 등)가 LLM 추출값보다 우선한다.

사용 예:
  python scripts/consult_prep.py --name "출산·육아용품 지원 확대" --org "대구광역시 군위군" \
      --target "둘째 이상 출산가정" --content "출산용품 구입비 지원" --amount 500000 --cycle 1회 --out out.md
  python scripts/consult_prep.py --name "..." --org "경상북도 영덕군" --text "사업안 자유 서술" --backend codex
  python scripts/consult_prep.py ... --servId WLF00000131   # 기존 복지로 등록본과 차이표
"""
import argparse, csv, json, re, math, collections, difflib, hashlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
LOCAL = ROOT / "data/raw/api/local_list.csv"
DETAIL = ROOT / "data/raw/api/local_detail"
FAST = ROOT / "data/raw/신속협의_유형_2026.csv"
HIST = ROOT / "data/raw/협의완료_2025_부록1.csv"
CENTRAL = ROOT / "data/raw/복지서비스_중앙부처_20260819.csv"
PROPOSAL_CACHE = ROOT / "data/processed/proposal_cache"
CRITERIA = ROOT / "data/labels/판정기준_E1_E2.md"  # v2 협의제외 목록(§2, 지침 Ⅱ.3 요약)

# A. 협의제외 키워드 규칙 (2026 지침 Ⅱ.3 '협의제외 기본원칙에 부합하는 사업' 예시에서 옮김; 인쇄 17~18쪽)
EXCLUDE_RULES = [
    ("일반행정·생활편의", ["종량제", "이미용", "미용", "목욕비", "전입 축하 현물", "민원기동반", "국적취득", "빨래방", "이장", "경로당 임원", "명절위문금", "복지카드 발급", "발급비용", "발급수수료", "경사로", "저장강박"], "지침 Ⅱ.3, 인쇄 17쪽"),
    ("이동권·접근성(단, 직접 현금 교통비 지원은 협의대상)", ["버스", "운수업체", "여객선", "공공자전거", "공영주차", "대중교통 요금", "정기패스", "면허 자진반납", "교통패스"], "지침 Ⅱ.3, 인쇄 17쪽"),
    ("국가적 피해자 지원·재난 예방", ["전세사기", "화재 피해", "수해", "배상책임보험", "실종예방", "인식표", "응급이송", "성매매", "성폭력", "아동학대", "범죄 피해", "안전보험", "소화기", "화재감지기", "예방접종", "치안"], "지침 Ⅱ.3, 인쇄 17쪽"),
    ("전국적으로 정착된 교육·보육·보호아동·문화", ["교복", "체육복", "체험학습", "수학여행", "졸업앨범", "급식비", "방과후", "평생교육이용권", "조식", "간식", "우유 급식"], "지침 Ⅱ.3, 인쇄 18쪽"),
    ("한시적·일회성", ["시상금", "인센티브", "민생지원금", "참여예산", "공모사업"], "지침 Ⅱ.3, 인쇄 17쪽"),
]

STOP = {"지원", "사업", "지원사업", "지급", "운영", "확대", "신설", "변경", "등", "및", "관련"}

# F. 복지로 태그 어휘(복지로 지자체 서비스 4,828건에서 확인, 2026-11-02)와 키워드 규칙
LIFE_RULES = [("영유아", ["영유아", "어린이집", "보육", "만 0세", "만 1세", "만 2세", "유아"]), ("아동", ["아동", "초등", "어린이", "입학"]), ("청소년", ["청소년", "중학", "고등학", "학생"]),
              ("청년", ["청년", "대학생", "신혼부부", "미취업"]), ("중장년", ["중장년", "중년", "장년"]), ("노년", ["노인", "어르신", "65세", "장수", "경로당", "고령"]),
              ("임신 · 출산", ["임신", "출산", "산모", "난임", "신생아", "출생아", "산후"])]
HH_RULES = [("저소득", ["저소득", "수급자", "차상위", "기초생활", "중위소득"]), ("장애인", ["장애"]), ("보훈대상자", ["보훈", "참전", "유공자"]), ("한부모·조손", ["한부모", "조손"]),
            ("다자녀", ["다자녀", "둘째", "셋째", "2자녀", "3자녀", "다둥이"]), ("다문화·탈북민", ["다문화", "결혼이민", "북한이탈", "탈북"])]
THEME_RULES = [("임신·출산", ["임신", "출산", "산모", "난임", "신생아", "출생아", "산후"]), ("교육", ["교육", "학자금", "입학", "교복", "장학", "검정고시", "유학"]),
               ("일자리", ["취업", "면접", "자격증", "창업", "근로", "구직", "일자리"]), ("신체건강", ["건강", "의료", "치료", "검진", "예방접종", "수술", "틀니", "임플란트", "보청기", "진료"]),
               ("보호·돌봄", ["돌봄", "요양", "치매", "간병", "아이돌봄", "케어"]), ("주거", ["주거", "월세", "전세", "임차", "이사", "주택", "보증금"]),
               ("안전·위기", ["안전", "재난", "피해", "보험", "위기", "긴급"]), ("입양·위탁", ["입양", "위탁"]), ("생활지원", ["생활", "용품", "이미용", "목욕", "물품"]),
               ("에너지", ["난방", "에너지", "냉방"]), ("보육", ["보육", "어린이집"]), ("서민금융", ["대출이자", "융자", "보증료", "이자 지원"])]
PROVISION_RULES = [("전자바우처(바우처)", ["바우처", "이용권"]), ("지역화폐", ["지역화폐", "지역상품권"]), ("현물대여", ["대여"]), ("현물지급", ["현물", "물품", "용품", "제공"]),
                   ("감면", ["감면", "면제"]), ("현금대여(융자)", ["융자", "대출"]), ("프로그램/서비스(서비스)", ["서비스", "프로그램", "상담", "교육"]),
                   ("현금지급", ["현금", "지원금", "수당", "축하금", "장려금", "구입비", "비용 지원", "비 지원", "지급"])]
CYCLE_MAP = {"월": "월", "연": "년", "년": "년", "1회": "1회성", "일회": "1회성", "분기": "분기", "반기": "반기", "주": "주", "수시": "수시"}


def toks(s):
    s = re.sub(r"^\(.*?\)\s*|^\[.*?\]\s*", "", s or "")
    out = []
    for w in re.findall(r"[가-힣A-Za-z0-9]+", s):
        w2 = re.sub(r"(지원사업|사업|지원|지급|비용)$", "", w) or w
        if len(w2) >= 2 and w2 not in STOP:
            out.append(w2)
    return out


def grams(s):
    s = re.sub(r"\s", "", s or "")
    return [s[i:i + 2] for i in range(len(s) - 1)]


class Tfidf:
    def __init__(self, docs):
        self.G = [set(grams(d)) for d in docs]
        df = collections.Counter()
        for g in self.G:
            df.update(g)
        n = len(docs)
        self.idf = {k: math.log(n / (1 + v)) for k, v in df.items()}
        self.V = [self._vec(g) for g in self.G]

    def _vec(self, g):
        v = {k: self.idf.get(k, 1.0) for k in g}
        nrm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {k: x / nrm for k, x in v.items()}

    def query(self, q, k=5, mask=None):
        qv = self._vec(set(grams(q)))
        sc = []
        for i, v in enumerate(self.V):
            if mask is not None and not mask[i]:
                continue
            sc.append((sum(qv.get(t, 0) * v.get(t, 0) for t in qv), i))
        sc.sort(reverse=True)
        return [x for x in sc[:k] if x[0] >= 0.03]  # '지원' 같은 공통 2-gram 하나로만 걸린 후보는 내지 않는다


def parse_amounts(text):
    """'연 최대 20만원', '월 10만원', '1회 30만원' → [(금액원, 주기)]"""
    out = []
    for m in re.finditer(r"(연|월|1회|생애 1회|1인당|가구당|회당|일)?\s*(?:최대|한도)?\s*(\d[\d,]*)\s*(만\s*원|천원|원)", text or ""):
        n = int(m.group(2).replace(",", ""))
        unit = m.group(3).replace(" ", "")
        won = n * 10000 if unit == "만원" else n * 1000 if unit == "천원" else n
        out.append((won, m.group(1) or ""))
    return out


def annualize(won, cycle):
    c = (cycle or "")
    if "월" in c:
        return won * 12
    return won  # 연·1회·미상은 그대로


def load_csv(p, enc="utf-8-sig"):
    return list(csv.DictReader(open(p, encoding=enc)))


def rule_tags(text, rules):
    hits = []
    for tag, kws in rules:
        k = [w for w in kws if w in text]
        if k:
            hits.append((tag, k))
    return hits


STRUCTURED = ROOT / "data/processed/structured_local_codex.jsonl"
BOKJIRO_HH = {"저소득", "장애인", "보훈대상자", "한부모·조손", "다자녀", "다문화·탈북민"}
FORM_MAP = {"현금": "현금지급", "현물": "현물지급", "바우처·이용권": "전자바우처(바우처)", "서비스": "프로그램/서비스(서비스)", "감면": "감면", "융자": "현금대여(융자)", "기타": "기타"}


def cell(x, n=70):
    x = re.sub(r"\s+", " ", str(x or "")).replace("|", "／").strip()
    return x if len(x) <= n else x[:n] + "…"


def load_structured():
    if not STRUCTURED.exists():
        return {}
    out = {}
    for line in open(STRUCTURED, encoding="utf-8"):
        r = json.loads(line)
        if r.get("output"):
            out[r["id"]] = r["output"]
    return out


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


SECTIONED = re.compile(r"(구간|가형|나형|마형|출생순위|첫째|둘째|셋째|다태아|만 0세|만 1세|순위|차등)")


def amount_check(ann_in, cap_text):
    """상한 대조(E2 사전 등록 §3): 사업안 연환산 ≤ 유형 최대 연환산이면 안. 못 읽거나 구간별이면 확인불가."""
    caps = parse_amounts(cap_text)
    if ann_in is None:
        return "확인불가", "사업안 금액 없음"
    if not caps:
        return "확인불가", "유형 상한 금액을 자동 추출 못 함(원문 확인)"
    if SECTIONED.search(cap_text):
        return "확인불가", f"유형 상한이 구간별로 다름 → 구간을 지정해 대조: {cap_text[:70]}…"
    cap = max(annualize(w, c) for w, c in caps)
    return ("안" if ann_in <= cap else "밖"), f"사업안 연환산 {ann_in:,}원 vs 유형 최대 연환산 {cap:,}원"


# v4 C1(30_analysis/v4_개선_사전등록.md §3): 구간별·비율 상한. v3 이하의 amount_check는 그대로 둬서 이전 결과를 재현한다.
AGE0 = re.compile(r"만\s*0\s*세[^,;/]*?(\d[\d,]*)\s*(만\s*원|천원|원)")
AGE1 = re.compile(r"만\s*1\s*세\s*이후[^,;/]*?(\d[\d,]*)\s*(만\s*원|천원|원)")


def _won(n, unit):
    n = int(n.replace(",", "")); unit = unit.replace(" ", "")
    return n * 10000 if unit == "만원" else n * 1000 if unit == "천원" else n


def proposal_ratio(text):
    """사업안의 지원 비율: '본인부담금 100% 지원' → 100, '본인부담금의 90%' → 90, '본인부담금 전액' → 100. 없으면 None."""
    t = text or ""
    m = re.search(r"본인\s*부담(?:금)?(?:의)?\s*(\d+)\s*%", t) or re.search(r"(\d+)\s*%\s*(?:를|을)?\s*(?:지원|보조|감면)", t)
    if m:
        return int(m.group(1))
    if re.search(r"본인\s*부담(?:금)?\s*(?:의\s*)?전액", t):
        return 100
    return None


def section_cap(cap_text, text, prof):
    """구간별 상한에서 사업안에 맞는 구간 하나를 고른다. 고를 수 없으면 None."""
    a0, a1 = AGE0.search(cap_text), AGE1.search(cap_text)
    if a0 and a1:
        lo = prof.get("age_min")
        hi = prof.get("age_max")
        if lo is not None and lo >= 1:
            return _won(*a1.groups()), "만 1세 이후"
        if hi is not None and hi == 0:
            return _won(*a0.groups()), "만 0세"
        return None
    segs = [s.strip() for s in re.split(r"\s*/\s*", cap_text) if s.strip()]
    if len(segs) >= 2 and any("둘째" in s for s in segs):          # 출생순위 구간(예: 7번 출산·육아용품)
        t = text or ""
        want = "셋째" if re.search(r"셋째|다태아", t) else "둘째" if "둘째" in t else None
        pick = next((s for s in segs if want and want in s), None) if want else next((s for s in segs if "모든" in s or "첫째" in s), None)
        if pick:
            amts = parse_amounts(pick)
            if amts:
                return annualize(*amts[0]), pick[:20]
    return None


def amount_check_v4(ann_in, cap_text, text, prof):
    caps = parse_amounts(cap_text)
    pcts = [int(x) for x in re.findall(r"(\d+)\s*%", cap_text)]
    if not caps and pcts and re.search(r"본인\s*부담|이용료", cap_text):   # 비율만 있는 상한(5·29·79번 등)
        cap_pct, p = max(pcts), proposal_ratio(text)
        if p is None:
            return "확인불가", f"유형 상한이 비율(최대 {cap_pct}%)인데 사업안 지원 비율을 확인 못 함"
        return ("안" if p <= cap_pct else "밖"), f"사업안 지원 비율 {p}% vs 유형 최대 {cap_pct}%"
    if ann_in is None:
        return "확인불가", "사업안 금액 없음"
    if not caps:
        return "확인불가", "유형 상한 금액을 자동 추출 못 함(원문 확인)"
    anns = [annualize(w, c) for w, c in caps]
    if SECTIONED.search(cap_text):
        lo, hi = min(anns), max(anns)
        if ann_in <= lo:
            return "안", f"사업안 연환산 {ann_in:,}원 ≤ 유형의 가장 낮은 구간 상한 {lo:,}원"
        if ann_in > hi:
            return "밖", f"사업안 연환산 {ann_in:,}원 > 유형의 가장 높은 구간 상한 {hi:,}원"
        sec = section_cap(cap_text, text, prof)
        if sec:
            cap, label = sec
            return ("안" if ann_in <= cap else "밖"), f"사업안 연환산 {ann_in:,}원 vs 유형 '{label}' 구간 상한 {cap:,}원"
        return "확인불가", f"사업안 연환산 {ann_in:,}원이 유형 구간 상한 사이({lo:,}~{hi:,}원) → 구간을 지정해 대조"
    cap = max(anns)
    return ("안" if ann_in <= cap else "밖"), f"사업안 연환산 {ann_in:,}원 vs 유형 최대 연환산 {cap:,}원"


# v5 C5(30_analysis/v4_개선_사전등록.md §6): 금액 없이 비율(또는 '전액')만 있는 상한. 괄호 안 소득 구간(중위 ○%)은 상한이 아니다.
def ratio_caps(cap_text):
    clean = re.sub(r"\([^)]*중위[^)]*\)", "", cap_text)
    pcts = [int(x) for x in re.findall(r"(\d+)\s*%", clean)]
    if "전액" in clean:
        pcts.append(100)
    return pcts


def amount_check_v5(ann_in, cap_text, text, prof):
    pcts = ratio_caps(cap_text)
    if not parse_amounts(cap_text) and pcts and len(set(pcts)) > 1:   # 유형별로 비율이 다른 상한(13번 아이돌봄)
        lo, hi, p = min(pcts), max(pcts), proposal_ratio(text)
        if p is None:
            return "확인불가", f"유형 상한이 소득 유형별 비율({lo}~{hi}%)인데 사업안 지원 비율을 확인 못 함"
        if p <= lo:
            return "안", f"사업안 지원 비율 {p}% ≤ 유형의 가장 낮은 비율 상한 {lo}%"
        if p > hi:
            return "밖", f"사업안 지원 비율 {p}% > 유형의 가장 높은 비율 상한 {hi}%"
        return "확인불가", f"사업안 지원 비율 {p}%가 유형별 비율 상한 사이({lo}~{hi}%) → 소득 유형별로 대조"
    # v5.1 D2(사전등록 §8): 구간형이 아닌데 금액이 여럿인 상한. 괄호 안 설명 금액은 빼고, '총 ○원'이 있으면 그 값,
    # 서로 다른 금액이 남으면 가장 낮은 값 이하만 '안', 가장 높은 값 초과만 '밖', 사이는 확인불가.
    # (11/10 첫 판은 괄호 금액을 모두 뺐다가 59번 '120만원 한도(양쪽 240만원)'을 깎아 E2c 289를 틀렸다. 그래서 설명 괄호(대출·예시)만 빼고,
    #  ';'·'/'로 나뉜 항목은 사업안 낱말과 맞는 항목 하나를 골라 그 항목의 상한을 쓴다.)
    if not SECTIONED.search(cap_text) and ann_in is not None:
        main = re.sub(r"\([^)]*(?:대출|예:)[^)]*\)", "", cap_text)
        item_cap = lambda it: max((annualize(w, c) for w, c in parse_amounts(it)), default=None)
        tot = TOTAL_CAP.search(main)
        if tot:
            cap = annualize(_won(tot.group(2), tot.group(3)), tot.group(1) or "")
            return ("안" if ann_in <= cap else "밖"), f"사업안 연환산 {ann_in:,}원 vs 유형 총 상한 {cap:,}원"
        items = [it for it in re.split(r"\s*[;/]\s*", main) if item_cap(it) is not None]
        if len(items) > 1:
            words = lambda it: [w for w in toks(re.sub(r"\([^)]*\)|\d[\d,]*\s*(만\s*원|천원|원)", " ", it)) if w not in ("최대", "한도", "이내", "연", "월", "본인부담금")]
            ws = [words(it) for it in items]
            uniq = [[w for w in ws[i] if not any(w in ws[j] for j in range(len(items)) if j != i)] for i in range(len(items))]  # 그 항목에만 있는 낱말
            hit = [it for it, u in zip(items, uniq) if any(w in (text or "") or (len(w) >= 4 and w[:2] in (text or "")) for w in u)]
            if len(hit) == 1:
                cap = item_cap(hit[0])
                return ("안" if ann_in <= cap else "밖"), f"사업안 연환산 {ann_in:,}원 vs 유형 항목 '{hit[0][:18]}…' 상한 {cap:,}원"
            caps = sorted(item_cap(it) for it in items)
            lo, hi = caps[0], caps[-1]
            if ann_in <= lo:
                return "안", f"사업안 연환산 {ann_in:,}원 ≤ 유형 상한 항목 중 가장 낮은 {lo:,}원"
            if ann_in > hi:
                return "밖", f"사업안 연환산 {ann_in:,}원 > 유형 상한 항목 중 가장 높은 {hi:,}원"
            return "확인불가", f"유형 상한에 항목이 여럿({lo:,}~{hi:,}원)이라 사업안 {ann_in:,}원이 어느 항목인지 확인 필요"
        if parse_amounts(main):
            return amount_check_v4(ann_in, main, text, prof)
    return amount_check_v4(ann_in, cap_text, text, prof)


_AMT = r"(\d[\d,]*)\s*(만|천)?\s*원"
PERIODS = [(re.compile(r"분기(?:마다|별|당)?[^0-9\n]{0,8}" + _AMT), 4), (re.compile(r"반기(?:마다|별|당)?[^0-9\n]{0,8}" + _AMT), 2),
           (re.compile(r"(?:매주|주당|주마다|1주에|주)\s+" + _AMT), 52),
           # v5.2(사전등록 §9 결과): 3차 시험에서 빠진 표현
           (re.compile(r"격주(?:로|마다)?[^0-9\n]{0,8}" + _AMT), 26), (re.compile(r"학기(?:마다|별|당)?[^0-9\n]{0,8}" + _AMT), 2),
           (re.compile(r"(?:하루|매일|일당|1일)[^0-9\n]{0,8}" + _AMT), 365)]
N_MONTHS = re.compile(r"(\d+)\s*개월(?:마다|에 한 번|에 1회)[^0-9\n]{0,8}" + _AMT)
PERIOD_WORD = re.compile(r"격주|개월마다|개월에 한 번|개월에 1회|하루|매일|일당|학기|분기|반기|매주|주당|주마다|회당|건당|시간당|매회|차수당|회차당")
ANNUAL_STATED = re.compile(r"연\s*(?:간\s*)?(?:최대\s*)?\d[\d,]*\s*(?:만|천)?\s*원")
PER_USE = re.compile(r"(?:회당|1회당|건당|회차당|차수당)[^0-9\n]{0,8}" + _AMT)
USE_COUNT = re.compile(r"연\s*(?:최대\s*)?(\d+)\s*(?:회|건|차)")


def _amt(n, unit):
    return int(n.replace(",", "")) * {"만": 10000, "천": 1000}.get(unit or "", 1)


def period_annual(text):
    """v5.1 D3: 사업안 원문에서 분기·반기·주 단위 금액과 '회당 ○원 … 연 ○회'를 연 총액으로 바꾼다. (연 총액 후보 목록, 횟수를 모르는 회당 금액이 있는가)"""
    t = text or ""
    cands = [_amt(m.group(1), m.group(2)) * k for rx, k in PERIODS for m in rx.finditer(t)]
    cands += [_amt(m.group(2), m.group(3)) * 12 // int(m.group(1)) for m in N_MONTHS.finditer(t) if int(m.group(1)) > 0]
    per, cnt = PER_USE.search(t), USE_COUNT.search(t)
    if per and cnt:
        cands.append(_amt(per.group(1), per.group(2)) * int(cnt.group(1)))
    # v5.2: 주기 낱말은 있는데 연 총액으로 바꾸지 못했고 원문에 연 금액도 없으면 '확인 필요'로 넘긴다(표현을 다 셀 수 없으므로 안전 쪽으로)
    return cands, bool(PERIOD_WORD.search(t) and not cands and not ANNUAL_STATED.search(t))


# v5.6(사전등록 §13): 실제 요청서(경상북도 정보공개청구 회신)에서 찾은 결함 4개. 모두 LLM 답 뒤의 규칙 단계다.
OTHER_SECTION = re.compile(r"(?:^|\n)[^\n]*기존\s*제도와의\s*관계.*?(?=\n\s*\d+\.\s|\Z)", re.S)


def own_text(text):
    """F1: 협의요청서의 '기존 제도와의 관계' 절(다른 제도를 적는 곳, 다음 번호 절 앞까지)을 뺀 글."""
    return OTHER_SECTION.sub("\n", text or "")


MULTI_YEAR = re.compile(r"첫\s*돌|두\s*돌|세\s*돌|네\s*돌|돌\s*(?:때|시|도달)|연령\s*도달|\d+\s*년(?:간|에\s*걸쳐|\s*동안)\s*(?:나누어|나눠|분할)")
# F3: 사람이 지침 신속협의 유형표를 읽어 만든 '이름·상한 조건 엇갈림' 목록(지금은 6번 하나)
NAME_CAP_CONFLICT = {"6": {"topic": re.compile(r"출산\s*(?:축하|장려|지원)금|양육\s*(?:수당|지원금)"),
                           "first": re.compile(r"첫째|첫\s*아이|첫\s*자녀|1자녀|모든\s*출생아|출생아\s*(?:전체|모두)"),
                           "note": "유형 6번 이름은 '2자녀 이상 다자녀', 상한 칸은 '출생순위 관계없이'로 엇갈림 → 첫째아를 포함한 이 사업을 6번으로 볼지"}}
AGE_GROUP = {"청년": "청년", "노인": "노년", "어르신": "노년", "아동": "아동", "청소년": "청소년", "영유아": "영유아"}


def target_check_v56(type_target, income_pct, prof):
    """F4: (a) 유형이 중위소득 50% 이상 기준이고 사업안이 수급자·차상위면 소득 조건은 안. (b) 유형 대상에 숫자 없는 연령층 낱말이 있고
    사업안 생애주기가 네 층 이상(사실상 전 연령)이면 밖. 돌려주는 값: (판정, 이유, 걸린 규칙 목록)."""
    v, why = target_check(type_target, income_pct, prof)
    hit = []
    inc_type = prof.get("income_type") or "미상"
    m = re.search(r"중위소득\s*(\d+)\s*%", type_target)
    if v == "확인불가" and m and int(m.group(1)) >= 50 and income_pct is None and inc_type in ("기초생활수급", "차상위"):
        # §13 결과: 첫 판은 여기서 바로 '안'을 내 E2d 124(수급자 전 연령 + 39세 이하 자립준비청년, 사람 판정 '밖')를 '안'으로 바꿨다.
        # 유형 대상에 연령층 낱말이 있으면 소득만 맞다고 적고 확인불가로 둔다.
        if any(w in type_target for w in AGE_GROUP):
            why = f"소득 조건은 맞음(사업안 {inc_type} = 기준중위소득 50% 이하, 유형 {m.group(1)}% 이하); 유형 대상의 연령층('{type_target}')은 확인 필요"
        else:
            v, why = "안", f"사업안 소득 자격 {inc_type}(기준중위소득 50% 이하) vs 유형 중위소득 {m.group(1)}% 이하"
        hit.append("F4a")
    life = [x for x in (prof.get("life") or []) if x != "임신·출산"]
    if v != "밖" and any(w in type_target for w in AGE_GROUP) and not re.search(r"\d+\s*세", type_target) and len(life) >= 4:
        v, why = "밖", f"사업안 생애주기 {'·'.join(life)}(사실상 전 연령) vs 유형 대상 '{type_target}' → 대상이 유형보다 넓음"
        hit.append("F4b")
    return v, why, hit


# v5.3 방어장치(사전등록 §10): 신속을 권하기 전에 통과해야 하는 점검. 하나라도 걸리면 신속 대신 확인불가로 넘기고 이유를 적는다.
# 신속이 아닌 판정은 바꾸지 않는다(신속 오권고만 막는 장치).
SUSPECT = re.compile(r"검토\s*AI|AI\s*(?:는|에게|가)\s|시스템\s*지시|\[\s*시스템|SYSTEM\s*:|[Ii]gnore (?:all )?previous|이전 지시|(?:분류|판정|출력|간주|가정)(?:하라|할 것|해라|하시오)|type_no|amount_won|excluded\s*=")
ANY_AMT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?\s*원")


def text_amounts(text):
    """원문에 적힌 금액(원)들. '50만 원', '500,000원', '0.5백만원', '1억 원'."""
    mult = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "천": 1_000}
    return [int(float(n.replace(",", "")) * mult.get(u or "", 1)) for n, u in ANY_AMT.findall(text or "")]


def guards(body, content, amount, ann_chk, cap_basis, evidence_failed, unknown_period):
    """[(이름, 통과?, 설명)]. cap_basis: 상한 대조가 '금액'·'비율'·'' 중 무엇으로 됐는가."""
    out = []
    out.append(("근거 구절", not evidence_failed, "근거 구절이 원문에 그대로 있음" if not evidence_failed else f"원문에 그대로 없는 근거 {evidence_failed}"))
    out.append(("지급 주기", not unknown_period, "주기를 연 총액으로 읽음" if not unknown_period else "주기 낱말이 있는데 연 총액으로 바꾸지 못함"))
    m = SUSPECT.search(body or "")
    out.append(("지시문 의심", m is None, "판정을 지시하는 문구 없음" if m is None else f"사업안 안에 판정을 지시하는 듯한 문구 '{m.group(0)}'"))
    if cap_basis == "금액":
        amts = text_amounts(body)
        ok = amount is not None and amount in amts
        out.append(("금액 출처", ok, "대조한 금액이 원문에 숫자로 있음" if ok else f"대조한 금액 {amount}원을 원문 숫자에서 찾지 못함(한글 수·계산값)"))
        ok = ann_chk is not None and 0 < ann_chk <= 100_000_000
        out.append(("금액 범위", ok, "연 총액이 0원 초과 1억 원 이하" if ok else f"연 총액 {ann_chk}원이 통상 범위 밖"))
        big = [x for x in text_amounts(content) if amount is not None and x > amount]
        out.append(("더 큰 금액", not big, "지원내용에 대조한 금액보다 큰 금액 없음" if not big else f"지원내용에 대조한 금액보다 큰 금액 {max(big):,}원이 있음"))
    return out


TOTAL_CAP = re.compile(r"총\s*(?:지원금(?:액)?)?\s*(?:약)?\s*(연|월)?\s*(\d[\d,]*)\s*(만\s*원|천원|원)")
WIDE_ORG = re.compile(r"^\S+(특별자치도|특별자치시|통합특별시|특별시|광역시|도)(청)?$")
WIDE_SHORT = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"}  # v5.2: 시도 약칭


NO_BASIC = re.compile(r"^(세종|제주)")  # v5.5: 기초지자체가 없는 세종·제주는 본청도 신속협의 대상기관(지침 Ⅱ.5)


def is_wide(org, v5=False):
    """신속협의를 쓸 수 없는 광역(본청)·교육청인가. v5.1 D1: 기관명이 시도 이름 하나뿐이어도 광역으로 본다('경기도', '서울특별시').
    v5.5(11/13): 지침 Ⅱ.5 '기초지방자치단체(기초지자체 없는 세종, 제주 포함)'에 따라 세종·제주는 교육청이 아니면 광역으로 보지 않는다.
    v4 이하 경로는 그대로 둔다(제안서 측정의 재현용; 측정 130건에 세종·제주 사례 없음)."""
    o = (org or "").strip()
    if v5 and NO_BASIC.match(o) and "교육청" not in o:
        return False
    return bool(re.search(r"본청|교육청", o) or (v5 and (WIDE_ORG.match(o) or re.sub(r"(시|도|청|시청|도청)$", "", o) in WIDE_SHORT)))


# v4 C2: 소득 금액의 기준중위소득 % 참고값. 판정은 바꾸지 않는다(판정 기준상 원문에 %가 없으면 대상 '알 수 없음').
# 2026 기준중위소득(월, 원): 보건복지부 수급자선정기준 https://www.mohw.go.kr/menu.es?mid=a10708010300 (11/6 저장, 소득인정액 기준)
MEDIAN_2026 = {1: 2564238, 2: 4199292, 3: 5359036, 4: 6494738, 5: 7556719, 6: 8555952}
KWON = re.compile(r"(?:(\d+)\s*억\s*)?(?:(\d[\d,]*)\s*(천만|백만|만|천)?\s*)?원")


def _korean_won(m):
    eok, n, unit = m.group(1), m.group(2), m.group(3)
    if not eok and not n:
        return None
    v = int(eok) * 100_000_000 if eok else 0
    if n:
        k = int(n.replace(",", ""))
        v += k * {"천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "천": 1_000}.get(unit or "", 1)
    return v


def income_amount(text):
    """'연소득 5천만원 이하', '부부합산 연소득 1억3천만원 이하', '연소득 50백만원 이하인 자' → (연 금액, 구절, 가구원 수 단서)."""
    for m in re.finditer(r"((?:부부\s*합산\s*)?(?:연\s*소득|연간\s*소득|연봉|월\s*소득))[^0-9\n]{0,6}", text or ""):
        tail = (text or "")[m.end(): m.end() + 25]
        w = KWON.match(tail)
        if not w or w.end() == 0:
            continue
        won = _korean_won(w)
        if not won or won < 1_000_000:
            continue
        if not re.match(r"\s*(이하|미만|이내)", tail[w.end():]):
            continue
        ann = won * 12 if "월" in m.group(1) else won
        phrase = (m.group(0) + tail[: w.end()]).strip()
        hh = 2 if re.search(r"부부\s*합산", m.group(1)) else 1 if re.search(r"1인\s*가구|미혼\s*1인|1인\s*세대", text) else None
        return ann, phrase, hh
    return None


def income_reference(text):
    got = income_amount(text)
    if not got:
        return ""
    ann, phrase, hh = got
    sizes = [hh] if hh else [1, 2, 3, 4]
    parts = [f"{h}인 가구 약 {ann / (MEDIAN_2026[h] * 12) * 100:.0f}%" for h in sizes]
    return f"참고: '{phrase}'을 2026 기준중위소득에 비추면 " + "·".join(parts) + "(기준중위소득은 소득인정액 기준이라 판정에는 쓰지 않음)"


def target_check(type_target, income_pct, prof):
    """대상 대조(E2 사전 등록 §3): ①중위소득 ②수급·차상위 ③연령 ④넓은 대상 순으로 먼저 걸리는 규칙."""
    inc_type = prof.get("income_type") or "미상"
    m = re.search(r"중위소득\s*(\d+)\s*%", type_target)
    if m:
        x = int(m.group(1))
        if income_pct is not None:
            return ("안" if income_pct <= x else "밖"), f"사업안 중위소득 {income_pct}% vs 유형 {x}% 이하"
        if inc_type == "소득무관":
            return "밖", f"사업안은 소득 기준 없음 vs 유형 중위소득 {x}% 이하 → 대상이 유형보다 넓음"
        return "확인불가", f"유형 대상에 중위소득 {x}% 기준이 있으나 사업안 소득 기준을 % 로 확인 못 함"
    if re.search(r"기초생활수급|차상위", type_target):
        if inc_type in ("기초생활수급", "차상위"):
            return "안", f"사업안 소득 자격 {inc_type} vs 유형 대상 '{type_target}'"
        if inc_type in ("소득무관", "중위소득기준"):
            return "밖", f"사업안 소득 자격 {inc_type} → 유형 대상(수급·차상위)보다 넓음"
        return "확인불가", "유형 대상이 수급·차상위인데 사업안 소득 자격을 확인 못 함"
    ages = re.findall(r"(\d+)\s*세\s*(이상|이하|미만)", type_target)
    if ages:
        lo = next((int(n) for n, k in ages if k == "이상"), None)
        hi = next((int(n) - (1 if k == "미만" else 0) for n, k in ages if k in ("이하", "미만")), None)
        pmin, pmax = prof.get("age_min"), prof.get("age_max")
        if (lo is not None and pmin is None) or (hi is not None and pmax is None):
            return "확인불가", f"유형 대상에 연령 기준({type_target})이 있으나 사업안 연령을 확인 못 함"
        ok = (lo is None or pmin >= lo) and (hi is None or pmax <= hi)
        return ("안" if ok else "밖"), f"사업안 연령 {pmin}~{pmax} vs 유형 {lo}~{hi}"
    return "안", f"유형 대상이 넓음('{type_target}')"


def baseline_profile(text):
    """M0 규칙 기준선: LLM 없이 정규식으로 금액·주기·소득·연령을 읽는다(E2 사전 등록 §2)."""
    amts = parse_amounts(text)
    won, cyc = (amts[0] if amts else (None, ""))
    cycle = "월" if cyc == "월" else "연" if cyc == "연" else "1회" if "1회" in cyc else ""
    pct = re.search(r"중위소득\s*(\d+)\s*%", text)
    if re.search(r"소득\s*(기준\s*)?(없|무관)|소득에\s*관계\s*없", text):
        inc_type = "소득무관"
    elif pct:
        inc_type = "중위소득기준"
    elif re.search(r"차상위", text):
        inc_type = "차상위"
    elif re.search(r"수급자|기초생활", text):
        inc_type = "기초생활수급"
    else:
        inc_type = "미상"
    lo = re.search(r"(\d+)\s*세\s*이상", text)
    hi = re.search(r"(\d+)\s*세\s*(이하|미만)", text)
    prof = {"income_type": inc_type, "income_median_pct": int(pct.group(1)) if pct else None,
            "age_min": int(lo.group(1)) if lo else None,
            "age_max": (int(hi.group(1)) - (1 if hi.group(2) == "미만" else 0)) if hi else None}
    return won, cycle, prof


def eval_fields(rep, org):
    """라벨 칸과 같은 형식의 도구 판정(E2 사전 등록 §3). 중복 조건은 판단하지 않으므로 '언급 없음'으로 둔다."""
    v2 = rep.get("v2")
    if v2:  # M2: 유형·협의제외는 LLM 선택, 대상·상한은 v1과 같은 규칙
        type_no = v2["type_no"]
        target, amount = (v2["대상판정"], v2["상한판정"]) if type_no != "해당없음" else ("", "")
        excluded = v2["excluded"]
    else:
        top = rep["fast"][0] if rep["fast"] else None
        type_no = top["연번"] if top and top["사업명일치"] > 0 else "해당없음"
        target = top["대상판정"] if type_no != "해당없음" else ""
        amount = top["상한판정"] if type_no != "해당없음" else ""
        excluded = "예" if rep["exclude"] else "아니오"
    if excluded == "예":
        v = "협의제외"
    elif is_wide(org, bool((rep.get("input") or {}).get("v5"))):
        v = "일반"
    elif type_no == "해당없음":
        v = "일반"
    elif "밖" in (target, amount):
        v = "일반"
    elif (v2 or {}).get("type_match") == "가까움":  # v5 C6: 급여 방식이 다른 가까운 유형은 사람이 확인
        v = "확인불가"
    elif "확인불가" in (target, amount):
        v = "확인불가"
    elif (v2 or {}).get("중복위반") == "예":  # v3: 사람 순서도와 같이 중복·보충 조건 위반이면 일반
        v = "일반"
    else:
        v = "신속"
        if any(not g["통과"] for g in (v2 or {}).get("guards") or []):  # v5.3: 점검에 걸리면 신속을 권하지 않는다
            v = "확인불가"
    return {"유형연번": type_no, "대상": target, "상한": amount, "협의제외": excluded, "유형판정": v}


def extract_proposal(text, backend):
    """자유 서술 사업안 → 서식에 필요한 값 + 표준 조건(schema.ITEM_SCHEMA). 같은 입력은 캐시를 쓴다.
    서술형 값(target·content·criteria·region)과 표준 조건의 근거 구절은 원문에 그대로 있는지 검사한다."""
    from llm import ask, cache_tag
    from schema import INSTRUCTION, ITEM_SCHEMA, verify_evidence
    key = hashlib.sha1(f"{backend}\n{text}{cache_tag() if backend == 'codex' else ''}".encode("utf-8")).hexdigest()[:16]
    cache = PROPOSAL_CACHE / f"{key}.json"
    if cache.exists():
        out = json.loads(cache.read_text(encoding="utf-8"))
    else:
        nullable = lambda t: {"type": [t, "null"]}
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["target", "content", "criteria", "amount_won", "cycle", "region", "item"],
                  "properties": {"target": nullable("string"), "content": nullable("string"), "criteria": nullable("string"),
                                 "amount_won": nullable("integer"), "cycle": {"type": "string", "enum": ["월", "연", "1회", "미상"]},
                                 "region": nullable("string"), "item": ITEM_SCHEMA}}
        instruction = ("지자체 복지사업안(자유 서술)에서 협의 서식에 필요한 값을 뽑는다.\n"
                       "- target(지원대상), content(지원내용), criteria(선정기준: 소득·거주·연령), region(거주지 한정)은 원문에서 그대로 복사한 구절이다. 없으면 null.\n"
                       "- amount_won: 1인(가구)당 지원액을 원 단위 정수로. 금액이 여러 개면 가장 큰 것 하나. 없으면 null. cycle은 그 금액의 지급 주기.\n"
                       "- item: 아래 규칙을 따르는 표준 조건이다. item.id는 'P'.\n" + INSTRUCTION)
        res, sec = ask(backend, instruction, {"사업": [{"id": "P", "원문": text}]}, schema)
        out = {"backend": backend, "sec": round(sec, 1), "result": res}
        PROPOSAL_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    res = out["result"]
    src = norm_ws(text)
    failed = [k for k in ("target", "content", "criteria", "region") if res.get(k) and norm_ws(res[k]) not in src]
    failed += verify_evidence(res["item"], text)
    return res, failed, out.get("sec")


# v2 유형 고르기 규칙: 판정기준 ②를 옮김. 6번 예외는 유형 이름과 개발 세트 392(출생순위별 출산축하금 → 해당없음)·435(다자녀 양육수당 → 6번)에 근거한다.
V2_TYPE_RULES = """[유형 고르기] 사업안이 '유형목록'(2026 신속협의 유형 79개) 중 어느 것에 해당하는지 하나를 고른다.
- 먼저 급여 항목(무엇을 주는가: 현금의 명목, 물품, 서비스, 비용의 종류)이 같은 유형을 찾고, 그중 대상이 가장 가까운 것 하나를 고른다.
- 급여 항목이 같은 유형이 없으면 '해당없음'이다. 낱말만 겹치는 유형은 고르지 않는다. 예: '청년 정장 구입비'는 20번(면접 서비스)과 급여 항목이 달라 해당없음.
- 대상이 유형보다 넓거나 금액이 상한을 넘어도 급여 항목이 같으면 그 유형을 고른다. 범위 안/밖은 따로 판단한다.
- 예외: 6번(출산축하금·양육수당)은 유형 이름대로 '2자녀 이상 다자녀' 사업에만 고른다. 첫째부터 주는 출산축하금·양육수당은 6번이 아니다.
- 광역(본청)·교육청 사업이어도 맞는 유형이 있으면 고른다.
- type_evidence는 판단의 근거가 된 사업안 원문 구절을 그대로 복사한다(없으면 null). type_reason은 한두 문장. alt_types는 함께 검토할 만한 다른 유형(없으면 빈 배열).
"""
V2_EXCLUDE_RULES = """[협의제외] 아래 '협의제외 목록 요약'(2026 지침 Ⅱ.3)에 비추어 사업안이 협의제외인지 정한다.
- '제외되는 것'에 해당하고, 그 칸의 '단서'와 '2.1 적용불가'에 걸리지 않으면 excluded='예'다. exclude_clause에 범주 이름을, exclude_evidence에 근거가 된 사업안 원문 구절을 그대로 쓴다.
- 신속 유형 목록에 같은 사업이 있으면 협의대상(excluded='아니오')으로 본다.
- '확인불가'는 고를 수 없다. 확정할 수 없으면 excluded='아니오'로 두고 exclude_clause에 '제외 사유 미확정'이라고 쓴다.
"""


# v5 C6: 급여 항목이 같은 유형이 없을 때 '가까운 유형'을 구분한다. 개발 세트 사업은 예로 넣지 않는다.
V5_NEAR_RULES = """[같음·가까움] type_match로 고른 유형이 얼마나 맞는지 답한다.
- 급여 항목이 같으면 type_match='같음'이다.
- 급여 항목이 같은 유형이 없더라도, 같은 분야에서 사업의 목적과 대상이 같고 지원 방식(현금 지급·바우처·서비스 본인부담금 지원·물품 등)만 다른 유형이 있으면, 해당없음 대신 그 유형을 type_no로 고르고 type_match='가까움'으로 둔다. 이 경우 담당자가 그 유형으로 볼지 확인한다.
- 사업안에 급여 내용이 적혀 있지 않아 같은지 판단할 수 없지만 사업명·대상으로 보아 가장 가까운 유형이 하나 있으면 그 유형을 고르고 type_match='가까움'으로 둔다.
- 낱말만 겹치거나 목적이 다른 유형은 가까움이 아니다. 그런 유형밖에 없으면 type_no='해당없음', type_match=null이다.
"""


# v3 추가 대조: 합성 S3(중복·보충 조건 위반을 못 봄)·S5(지원수준 칸의 지역 조건을 못 봄)에서 신속을 잘못 권한 것을 막는다.
REGION_COND = re.compile(r"인구소멸|인구감소|농산어촌|농어촌|대중교통 취약")  # 유형 칸의 지역 조건(17·33·48번)
V3_CHECK_RULES = """[고른 유형과 대조] type_no가 해당없음이 아니면 두 가지를 더 판단한다. 해당없음이면 둘 다 null이다.
- target_in: 고른 유형의 '대상'과 '지원수준' 칸에 적힌 자격 조건(지역·소득·연령·직업·가구 등) 안에 사업안의 대상이 들어가면 '안'이다. 사업안 대상이 그보다 넓거나 조건을 충족하지 않으면 '밖', 원문으로 판단할 수 없으면 '확인불가'다. 금액 상한은 여기서 보지 않는다. target_evidence는 근거가 된 사업안 원문 구절이다(없으면 null).
- dup_violation: 고른 유형의 '중복·보충조건'을 사업안이 어긴다는 근거가 원문에 있으면 '위반', 없으면 '언급 없음'이다. 조건이 없는 유형이면 '언급 없음'이다. dup_evidence는 근거 구절이다(없으면 null).
"""


# v5.4 피드백 선례(사전등록 §11): 담당자가 결재한 기록(승인·고침) 가운데 비슷한 사업을 찾아 LLM에 참고로 준다.
V6_PREC_RULES = """[담당자 확정 선례] '확정 선례'는 담당자가 이전에 결재한 비슷한 사업의 최종 판정이다.
- 사업안과 급여 항목·대상이 같은 선례가 있으면 그 선례의 유형(또는 해당없음)과 협의제외 판단을 따른다. 선례를 따랐으면 type_reason에 '선례 ○○'이라고 적는다.
- 사업 내용이 다르면 선례를 따르지 않는다. 선례끼리 판정이 다르면 사업안과 더 비슷한 쪽을 따르고 그 사실을 type_reason에 적는다.
- 선례는 유형과 협의제외를 고르는 데만 쓴다. 금액·소득 같은 값은 반드시 사업안 원문에서만 읽는다.
"""


def load_feedback(path):
    """피드백 저장소(jsonl)에서 승인된 기록만 읽는다. 한 줄 = {id, name, org, text, final{유형연번, 협의제외, 유형판정}, reason, status}."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("status") == "승인":
                rows.append(r)
    return rows


def find_precedents(name, text, store, k=3, min_sim=0.12, skip_id=None):
    """사업명·원문이 비슷한 선례 k개. 같은 사례(skip_id)와 원문이 똑같은 기록은 뺀다(평가 때 정답이 새지 않게)."""
    cand = [r for r in store if r.get("id") != skip_id and norm_ws(r.get("text", "")) != norm_ws(text)]
    if not cand:
        return []
    tf = Tfidf([r["name"] + " " + r.get("text", "")[:300] for r in cand])
    out = []
    for sim, i in tf.query(name + " " + (text or "")[:300], k):
        if sim >= min_sim:
            r = cand[i]
            out.append({"선례": r["id"], "사업명": r["name"], "요청기관": r.get("org", ""), "내용": cell(r.get("text", ""), 220),
                        "확정": r["final"], "담당자 메모": r.get("reason") or "", "유사도": round(sim, 2)})
    return out


def select_type_v2(name, org, text, fast, backend, v3=False, v5=False, precedents=None):
    """v2: 79개 유형 전체에서 유형 하나(또는 해당없음)와 협의제외 여부를 근거 구절과 함께 고른다. v3면 대상 조건·중복 조건도 본다. 같은 입력은 캐시를 쓴다."""
    from llm import ask, cache_tag
    ex_list = CRITERIA.read_text(encoding="utf-8").split("## 2. 협의제외 목록 요약")[1].split("\n---")[0]
    instruction = ("지자체 사회보장 신설·변경 협의를 준비하는 담당자를 돕는다. 판정의 초안이며 최종 판단은 사람이 한다.\n"
                   + V2_TYPE_RULES + (V5_NEAR_RULES if v5 else "") + (V3_CHECK_RULES if v3 else "") + V2_EXCLUDE_RULES
                   + (V6_PREC_RULES if precedents else "") + "\n[협의제외 목록 요약]\n" + ex_list)
    nos = [r["연번"] for r in fast] + ["해당없음"]
    schema = {"type": "object", "additionalProperties": False,
              "required": ["type_no", "type_reason", "type_evidence", "alt_types", "excluded", "exclude_clause", "exclude_evidence"],
              "properties": {"type_no": {"type": "string", "enum": nos}, "type_reason": {"type": "string"},
                             "type_evidence": {"type": ["string", "null"]},
                             "alt_types": {"type": "array", "items": {"type": "string", "enum": nos}},
                             "excluded": {"type": "string", "enum": ["예", "아니오"]},
                             "exclude_clause": {"type": ["string", "null"]}, "exclude_evidence": {"type": ["string", "null"]}}}
    if v3:
        schema["required"] += ["target_in", "target_evidence", "dup_violation", "dup_evidence"]
        schema["properties"].update({"target_in": {"type": ["string", "null"], "enum": ["안", "밖", "확인불가", None]},
                                     "target_evidence": {"type": ["string", "null"]},
                                     "dup_violation": {"type": ["string", "null"], "enum": ["위반", "언급 없음", None]},
                                     "dup_evidence": {"type": ["string", "null"]}})
    if v5:
        schema["required"] += ["type_match"]
        schema["properties"]["type_match"] = {"type": ["string", "null"], "enum": ["같음", "가까움", None]}
    payload = {"사업안": {"사업명": name, "요청기관": org, "원문": text},
               "유형목록": [{"연번": r["연번"], "분야": r["분야"], "사업명": r["사업명"], "대상": r["대상"], "지원수준": r["지원수준(최대 상한)"],
                          **({"중복·보충조건": r["중복·보충 조건"]} if v3 else {})} for r in fast]}
    if precedents:
        payload["확정 선례"] = [{k: v for k, v in pr.items() if k != "유사도"} for pr in precedents]
    key_src = (f"v2\n{backend}\n{instruction}\n{name}\n{org}\n{text}" + (f"\n{json.dumps(payload['유형목록'], ensure_ascii=False)}" if v3 else "")
               + (f"\n{json.dumps(payload['확정 선례'], ensure_ascii=False)}" if precedents else "")
               + (cache_tag() if backend == "codex" else ""))
    key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
    cache = PROPOSAL_CACHE / f"{'v5' if v5 else 'v3' if v3 else 'v2'}_{key}.json"
    if cache.exists():
        out = json.loads(cache.read_text(encoding="utf-8"))
    else:
        res, sec = ask(backend, instruction, payload, schema)
        out = {"backend": backend, "sec": round(sec, 1), "result": res}
        PROPOSAL_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    res, src = out["result"], norm_ws(name + " " + text)
    failed = [k for k in ("type_evidence", "exclude_evidence", "target_evidence", "dup_evidence") if res.get(k) and norm_ws(res[k]) not in src]
    return res, failed


def condition_diff(mine, theirs):
    """사업안의 표준 조건과 후보 사업의 구조화 조건을 항목별로 비교한 짧은 문자열."""
    if not mine or not theirs:
        return ""
    parts = []
    for key, label in (("life", "생애"), ("household", "가구"), ("support_form", "형태")):
        a, b = set(mine.get(key) or []), set(theirs.get(key) or [])
        if a or b:
            parts.append(f"{label} {'같음' if a == b else ('겹침' if a & b else '다름')}({','.join(sorted(b)) or '미상'})")
    inc_a = (mine.get("income_type"), mine.get("income_median_pct"))
    inc_b = (theirs.get("income_type"), theirs.get("income_median_pct"))
    parts.append(f"소득 {'같음' if inc_a == inc_b else '다름'}({inc_b[0]}{' ' + str(inc_b[1]) + '%' if inc_b[1] else ''})")
    if theirs.get("region_type") == "거주지한정":
        parts.append(f"거주 {theirs.get('region_name') or '한정'}")
    if any(c.get("join") == "OR" for c in theirs.get("conditions", [])):
        parts.append("OR 조건 있음")
    if any(c.get("exception") for c in theirs.get("conditions", [])):
        parts.append("예외 조건 있음")
    return "; ".join(parts)


def draft_bokjiro(a, rep, loc_by_id):
    """F. 복지로 등록 초안과 기존 등록본 차이표.
    servId가 구조화 결과(LLM, 근거 구절 검증)에 있으면 그 항목을, 없으면 키워드 규칙(후보)을 쓴다. 근거가 없으면 보류."""
    full = " ".join([a.name, a.target, a.content, a.purpose])
    st = load_structured().get(a.servId) if a.servId else None
    src = "LLM 구조화(근거 구절 원문 검증)" if st else "키워드 규칙(후보, v1에서 LLM 구조화로 대체)"
    if st:
        ev_all = "; ".join(c["evidence"] for c in st.get("conditions", []) if c.get("evidence"))[:80]
        life_v = ", ".join(x.replace("임신·출산", "임신 · 출산") for x in st.get("life", [])) or None
        life_w = f"{src}: " + (st.get("age_evidence") or ev_all or "근거 없음 → 보류")
        hh_list = [x for x in st.get("household", []) if x in BOKJIRO_HH]
        hh_v = ", ".join(hh_list) or None
        hh_w = f"{src}: " + (ev_all if hh_list else "가구 조건 없음 → 공백 유지")
        forms = [FORM_MAP.get(x, x) for x in st.get("support_form", [])]
        prov_v = forms[0] if forms else None
        prov_w = f"{src}: support_form={st.get('support_form')}"
        income_note = f"소득 {st.get('income_type')}" + (f" {st.get('income_median_pct')}%" if st.get("income_median_pct") else "") + (f" (근거: {st.get('income_evidence')})" if st.get("income_evidence") else "")
        region_note = f"지역 {st.get('region_type')} {st.get('region_name') or ''} (근거: {st.get('region_evidence') or '없음'})"
    else:
        life = rule_tags(full, LIFE_RULES)
        hh = rule_tags(full, HH_RULES)
        prov = rule_tags(a.content + " " + a.name, PROVISION_RULES)
        life_v = ", ".join(t for t, _ in life) if life else None
        life_w = f"{src}: " + ("; ".join(f"{t}←{k}" for t, k in life) or "일치어 없음")
        hh_v = ", ".join(t for t, _ in hh) if hh else None
        hh_w = f"{src}: " + ("; ".join(f"{t}←{k}" for t, k in hh) or "일치어 없음(소득·가구 조건이 없으면 비워 둠)")
        prov_v = prov[0][0] if prov else None
        prov_w = f"{src}: " + (f"{prov[0][0]}←{prov[0][1]}" if prov else "일치어 없음")
        income_note = region_note = ""
    theme = rule_tags(full, THEME_RULES)
    cyc = next((v for k, v in CYCLE_MAP.items() if k in (a.cycle or "")), None)
    short = bool(a.target and a.content and len(a.target) < 60 and len(a.content) < 60)
    draft = {
        "사업명": (a.name, "입력"),
        "요약(servDgst)": ((f"{a.target}에게 {a.content}을(를) 지원" + (f"하여 {a.purpose}" if a.purpose else "")) if short else None, "입력 조합(목적·대상·내용)" if short else "입력이 길어 보류(v1: LLM 요약)"),
        "생애주기": (life_v, life_w),
        "가구상황": (hh_v, hh_w),
        "관심주제": (", ".join(t for t, _ in theme) if theme else None, "키워드 규칙(후보): " + ("; ".join(f"{t}←{k}" for t, k in theme) or "일치어 없음") + " — 반드시 확인"),
        "지원주기": (cyc, f"입력 주기 '{a.cycle}'" if a.cycle else "입력 없음"),
        "제공유형": (prov_v, prov_w),
        "신청방법": (a.apply or None, "입력" if a.apply else "입력 없음"),
        "지원대상(sprtTrgtCn)": (a.target or None, "입력" + (f"; {income_note}; {region_note}" if income_note else "")),
        "선정기준(slctCritCn)": (a.criteria or None, "입력" if a.criteria else "입력 없음(소득·거주·연령 기준을 적어야 함)"),
        "지원내용(alwServCn)": ((a.content + (f" ({a.amount:,}원/{a.cycle})" if a.amount else "")) or None, "입력"),
        "근거법령(조례)": (a.law or None, "입력" if a.law else "입력 없음"),
    }
    cur = None
    if a.servId:
        cur = loc_by_id.get(a.servId)
        dp = DETAIL / f"{a.servId}.json"
        if dp.exists():
            d = json.load(open(dp, encoding="utf-8"))
            cur = {**(cur or {}), **{"sprtTrgtCn": d.get("sprtTrgtCn", ""), "slctCritCn": d.get("slctCritCn", ""), "alwServCn": d.get("alwServCn", ""), "baslaw": ", ".join(x.get("wlfareInfoReldNm", "") for x in d.get("baslawList", []))}}
    curmap = {"사업명": "servNm", "요약(servDgst)": "servDgst", "생애주기": "lifeNmArray", "가구상황": "trgterIndvdlNmArray", "관심주제": "intrsThemaNmArray", "지원주기": "sprtCycNm", "제공유형": "srvPvsnNm", "신청방법": "aplyMtdNm",
              "지원대상(sprtTrgtCn)": "sprtTrgtCn", "선정기준(slctCritCn)": "slctCritCn", "지원내용(alwServCn)": "alwServCn", "근거법령(조례)": "baslaw"}
    rows = []
    for k, (val, why) in draft.items():
        curv = (cur or {}).get(curmap[k], "") if cur else ""
        if cur is None:
            diff = ""
        elif not str(curv).strip():
            diff = "현재 공백 → 초안 제안" if val else "현재 공백·초안도 보류"
        elif val is None:
            diff = "초안 보류(현재 값 유지)"
        else:
            if k in ("생애주기", "가구상황", "관심주제"):
                same = set(x.strip() for x in curv.split(",") if x.strip()) == set(x.strip() for x in val.split(",") if x.strip())
            else:
                same = re.sub(r"\s+", " ", curv).strip() == re.sub(r"\s+", " ", val).strip()
            diff = "일치" if same else "불일치(검토)"
        rows.append({"항목": k, "초안": cell(val) if val is not None else "보류", "근거": cell(why, 90), "현재 복지로": cell(curv) if cur else "(등록본 없음)", "차이": diff})
    rep["bokjiro"] = {"servId": a.servId, "source": src, "rows": rows, "note": "생애주기·가구상황·제공유형은 구조화 결과(있으면)에서, 관심주제는 규칙 후보. 어휘는 복지로 지자체 서비스 4,828건의 실제 태그값. 보류 항목은 담당자가 채운다. 현행화 시기: 지자체 매년 5~6월(지침 Ⅶ)."}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--org", required=True, help="예: 대구광역시 군위군 / 경상북도 경산시 / 경상북도 본청")
    ap.add_argument("--target", default="", help="지원대상 서술")
    ap.add_argument("--content", default="", help="지원내용 서술")
    ap.add_argument("--purpose", default="", help="사업목적 한 줄(요약 초안에 씀)")
    ap.add_argument("--criteria", default="", help="선정기준 서술(소득·거주·연령)")
    ap.add_argument("--law", default="", help="근거 조례·법령")
    ap.add_argument("--apply", default="", help="신청방법(방문/인터넷/전화/우편)")
    ap.add_argument("--amount", type=int, default=None, help="1인(가구)당 지원액(원)")
    ap.add_argument("--cycle", default="", help="월/연/1회")
    ap.add_argument("--income", type=int, default=None, help="기준중위소득 %% (없으면 생략)")
    ap.add_argument("--region", default="", help="거주지 한정 조건 서술")
    ap.add_argument("--servId", default="", help="기존 복지로 등록본 servId(있으면 차이표)")
    ap.add_argument("--text", default="", help="(v1) 자유 서술 사업안. 비어 있는 인자를 LLM 추출값으로 채운다")
    ap.add_argument("--backend", default="codex", choices=["codex", "agy"], help="--text 추출에 쓸 LLM 백엔드")
    ap.add_argument("--baseline", action="store_true", help="M0 규칙 기준선: --text를 LLM 없이 정규식으로 읽는다")
    ap.add_argument("--v2", action="store_true", help="v2: 유형 고르기·협의제외를 LLM이 근거 구절과 함께 정한다")
    ap.add_argument("--v3", action="store_true", help="v3: v2 + 대상·중복 조건 대조, 유사사업 AI 판정·지역별 묶음")
    ap.add_argument("--v4", action="store_true", help="v4: v3 + 구간별·비율 상한 계산(C1, 30_analysis/v4_개선_사전등록.md)")
    ap.add_argument("--v5", action="store_true", help="v5: v4 + 소득 유형별 비율 상한(C5)·가까운 유형 확인(C6) (30_analysis/v4_개선_사전등록.md §6)")
    ap.add_argument("--feedback", default=None, help="v5.4: 담당자 결재 기록(jsonl). 승인된 비슷한 선례를 유형 선택에 참고로 준다")
    ap.add_argument("--case-id", default=None, help="평가용: 선례에서 이 사례 자신을 뺀다")
    ap.add_argument("--skip-similar", action="store_true", help="v3의 유사사업 AI 판정(C′)을 건너뛴다(E2 평가용)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    a.v4 = a.v4 or a.v5
    a.v3 = a.v3 or a.v4
    a.v2 = a.v2 or a.v3

    rep = {"input": dict(vars(a)), "extraction": None, "exclude": [], "fast": [], "similar": {}, "history": [], "hold": []}
    mine = None
    if a.text and a.baseline:
        won, cycle, mine = baseline_profile(a.text)
        if a.amount is None and won:
            a.amount = won
        if not a.cycle and cycle:
            a.cycle = cycle
        if a.income is None and mine["income_median_pct"]:
            a.income = mine["income_median_pct"]
        rep["extraction"] = {"backend": "M0 정규식", "sec": 0, "filled": {"amount": a.amount, "cycle": a.cycle, "income": a.income},
                             "item": None, "profile": mine, "evidence_failed": []}
    elif a.text:
        res, failed, sec = extract_proposal(a.text, a.backend)
        mine = res["item"]
        filled = {}
        for attr, val in (("target", res.get("target")), ("content", res.get("content")), ("criteria", res.get("criteria")),
                          ("region", res.get("region")), ("amount", res.get("amount_won")),
                          ("cycle", None if res.get("cycle") == "미상" else res.get("cycle")),
                          ("income", mine.get("income_median_pct"))):
            if val not in (None, "") and getattr(a, attr) in (None, ""):
                setattr(a, attr, val)
                filled[attr] = val
        rep["extraction"] = {"backend": a.backend, "sec": sec, "filled": filled, "item": mine, "evidence_failed": failed}
        if failed:
            rep["hold"].append(f"LLM 추출값 중 원문에 그대로 없는 항목 {failed} → 담당자 확인")
        if mine.get("income_type") in ("기초생활수급", "차상위", "기타소득기준") and a.income is None:
            rep["hold"].append(f"소득 기준이 '{mine.get('income_type')}'로 표현돼 중위소득 %로 바꾸지 않음 → 유형 대상의 중위소득 기준과는 담당자가 대조")

    org = a.org.split() or [""]  # 합성 사례처럼 기관이 없으면 기초지자체로 본다
    sido, sgg = org[0], (org[-1] if len(org) > 1 else "")
    full = " ".join([a.name, a.target, a.content])
    kws = toks(full)

    # A. 협의제외 후보
    for label, kw, src in EXCLUDE_RULES:
        hit = [k for k in kw if k in full]
        if hit:
            rep["exclude"].append({"유형": label, "일치어": hit, "출처": src})

    # B. 신속협의 유형 대조
    fast = load_csv(FAST)
    name_kws = toks(a.name)
    scored = []
    for r in fast:
        text = r["사업명"] + " " + r["대상"]
        # 사업명끼리 겹치는 낱말을 3배로 친다(서술이 길면 '가구'·'다자녀' 같은 공통어가 순위를 흔들기 때문)
        ov = 3 * sum(1 for w in name_kws if w in r["사업명"]) + sum(1 for w in kws if w in text)
        if ov:
            scored.append((ov, r))
    scored.sort(key=lambda x: -x[0])
    ann_in = annualize(a.amount, a.cycle) if a.amount else None
    prof = mine or {}  # 사업안의 소득·연령 정보(M1: LLM 추출, M0: 정규식)
    for ov, r in scored[:3]:
        amount_v, a_why = amount_check(ann_in, r["지원수준(최대 상한)"])
        target_v, t_why = target_check(r["대상"], a.income, prof)
        verdict = "범위 밖" if "밖" in (amount_v, target_v) else ("확인불가" if "확인불가" in (amount_v, target_v) else "범위 안")
        rep["fast"].append({"연번": r["연번"], "분야": r["분야"], "유형": r["사업명"], "대상": r["대상"], "상한": r["지원수준(최대 상한)"],
                            "중복조건": r["중복·보충 조건"], "확인필요": r["확인필요"], "일치어수": ov,
                            "사업명일치": sum(1 for w in name_kws if w in r["사업명"]),
                            "대상판정": target_v, "상한판정": amount_v, "판정후보": verdict, "근거": [t_why, a_why]})
    if a.v2:
        body = a.text or "\n".join(x for x in (a.target, a.criteria, a.content) if x)
        precs = find_precedents(a.name, body, load_feedback(a.feedback), skip_id=a.case_id) if (a.v5 and a.feedback) else []
        v2, v2_failed = select_type_v2(a.name, a.org, body, fast, a.backend, v3=a.v3, v5=a.v5, precedents=precs or None)
        v56 = []
        if a.v5 and v2["type_no"] == "해당없음":  # v5.6 F3′: 이름·상한 조건이 엇갈리는 유형을 뺐으면 판정은 두고 확인 항목으로 알린다
            # (§13 결과: 6번으로 올리는 첫 판(F3)은 회귀 139건 중 5건에 걸려 사람 판정과 4건이 어긋났다(판정 86 → 83). 사람 판정은
            #  첫째아 포함 사업을 대부분 6번이 아니라고 봤으므로, 판정은 LLM 답(해당없음)대로 두고 엇갈림만 담당자에게 보인다.)
            own = own_text(body)
            for no, cf in NAME_CAP_CONFLICT.items():
                if cf["topic"].search(a.name + " " + own) and cf["first"].search(own):
                    v2 = {**v2, "conflict_note": cf["note"] + " (도구는 6번이 아니라고 보고 일반으로 냄)"}
                    v56.append("F3알림")
                    break
        row = next((r for r in fast if r["연번"] == v2["type_no"]), None)
        t_v, t_why = target_check(row["대상"], a.income, prof) if row else ("", "")
        if a.v5 and row:  # v5.6 F4
            t_v, t_why, hit = target_check_v56(row["대상"], a.income, prof)
            v56 += hit
        if a.v4:
            check = amount_check_v5 if a.v5 else amount_check_v4
            ann_chk, per_note = ann_in, ""
            if a.v5:  # v5.1 D3
                cands, unknown_count = period_annual(own_text(body))  # v5.6 F1
                if period_annual(body)[0] != cands:
                    v56.append("F1")
                if cands and (ann_in is None or max(cands) > ann_in):
                    ann_chk, per_note = max(cands), f"; 주기 환산: 연 {max(cands):,}원으로 봄"
            m_v, m_why = check(ann_chk, row["지원수준(최대 상한)"], " ".join([a.name, body]), prof) if row else ("", "")
            if a.v5 and row:
                m_why += per_note
                if unknown_count and m_v == "안":
                    m_v, m_why = "확인불가", m_why + "; 지급 주기(회당·격주 등)를 연 총액으로 바꾸지 못해 확인 필요"
                mm = MULTI_YEAR.search(own_text(body))
                if mm and m_v == "밖":  # v5.6 F2: 총액이 상한 이하인 '안'은 그대로 둔다(나눠 주면 해마다는 더 적다)
                    m_v, m_why = "확인불가", m_why + f"; 여러 해에 나눠 주는 총액일 수 있음('{mm.group(0)}') → 해마다 주는 금액으로 다시 대조 필요"
                    v56.append("F2")
            if row and t_v == "확인불가" and "중위소득" in row["대상"]:
                ref = income_reference(body)
                if ref:
                    t_why = t_why + "; " + ref
        else:
            m_v, m_why = amount_check(ann_in, row["지원수준(최대 상한)"]) if row else ("", "")
        dup = ""
        if a.v3 and row:
            # v3.1: LLM 대상 대조는 유형 칸에 지역 조건이 있을 때만 쓴다(17·33·48번). 모든 유형에 쓰면 거주 요건처럼
            # 대상을 좁히는 조건까지 '밖'으로 봐서 개발 세트 신속 사례(428·429·474, E2b 838)를 틀렸다(11/5 v3 첫판).
            llm_t = v2.get("target_in") or "확인불가"
            if REGION_COND.search(row["대상"] + " " + row["지원수준(최대 상한)"]) and llm_t in ("밖", "확인불가") and t_v != "밖":
                t_v, t_why = llm_t, t_why + f"; LLM 지역 조건 대조: {llm_t} (근거: {v2.get('target_evidence') or '-'})"
            dup = "예" if v2.get("dup_violation") == "위반" else "아니오"
        rep["v2"] = {**v2, "유형": row["사업명"] if row else "", "대상판정": t_v, "상한판정": m_v, "근거": [t_why, m_why],
                     "중복위반": dup, "evidence_failed": v2_failed}
        if a.v5:
            rep["v2"]["precedents"] = precs
            rep["v2"]["v56"] = v56
        if a.v5 and row:  # v5.3 방어장치
            basis = "비율" if "비율" in m_why else ("금액" if ann_chk is not None else "")
            ev_fail = list(v2_failed) + list((rep.get("extraction") or {}).get("evidence_failed") or [])
            g = guards(body, a.content or body, a.amount, ann_chk, basis, ev_fail, unknown_count)
            rep["v2"]["guards"] = [{"점검": n, "통과": ok, "설명": why} for n, ok, why in g]
            bad = [f"{n}: {why}" for n, ok, why in g if not ok]
            if bad:
                rep["hold"].append("신속 권고 전 점검에서 걸림 → " + " / ".join(bad))
        if v2_failed:
            rep["hold"].append(f"v2 유형·협의제외 근거 구절 중 원문에 그대로 없는 항목 {v2_failed} → 담당자 확인")

    # C. 유사사업 후보
    loc = load_csv(LOCAL)
    loc_by_id = {l["servId"]: l for l in loc}
    docs = [l["servNm"] + " " + l["servDgst"] for l in loc]
    tf = Tfidf(docs)
    q = a.name + " " + a.target + " " + a.content

    structured = load_structured()

    def pack(res):
        return [{"servId": loc[i]["servId"], "시도": loc[i]["ctpvNm"], "시군구": loc[i]["sggNm"], "사업명": loc[i]["servNm"], "요약": loc[i]["servDgst"][:80], "점수": round(s, 3),
                 "조건차이": condition_diff(mine, structured.get(loc[i]["servId"]))} for s, i in res]
    rep["similar"]["전국"] = pack(tf.query(q, 5))
    same_sgg = [l["sggNm"] == sgg for l in loc]
    rep["similar"]["같은시군구"] = pack(tf.query(q, 5, same_sgg)) if sgg else []
    prov = [(l["ctpvNm"] == sido and not l["sggNm"].strip()) for l in loc]
    rep["similar"]["같은시도(광역본청)"] = pack(tf.query(q, 5, prov)) if any(prov) else []
    cen = load_csv(CENTRAL) if CENTRAL.exists() else []
    if cen:
        tfc = Tfidf([c["서비스명"] + " " + c["서비스요약"] for c in cen])
        rep["similar"]["중앙부처"] = [{"servId": cen[i]["서비스아이디"], "시도": "중앙", "시군구": cen[i]["소관부처명"], "사업명": cen[i]["서비스명"],
                                    "요약": cen[i]["서비스요약"][:80], "점수": round(s, 3), "조건차이": ""} for s, i in tfc.query(q, 5)]
    rep["similar"]["주의"] = ("복지로 공개본은 현행화된 사업만 담는다. 광역 사업 목록이 비면 '광역 중복 미확인'으로 보류한다. "
                            "중앙부처 사업은 이름·요약 기준 후보이고 지원조건 원문은 없다. 조건 차이는 구조화된 지자체 사업(대구·경북 426건)에만 표시한다.")

    # C′(v3). 유사사업 AI 판정 + 지역별 묶음. 후보 = TF-IDF 상위 30 ∪ 태그+키워드 상위 30 ∪ 같은 지자체·광역 본청의 낱말 겹침 상위 20
    if a.v3 and not a.skip_similar:
        from similar import b2_rank, judge_similar, relation
        same_area = [l["servId"] for l in loc if l["ctpvNm"] == sido and (l["sggNm"] or "") in (sgg if sgg != "본청" else "", "")
                     and any(w in l["servNm"] for w in toks(a.name))][:20]
        cands = list(dict.fromkeys([loc[i]["servId"] for _, i in tf.query(a.name, 30)] + [loc[i]["servId"] for i in b2_rank(a.org, a.name, loc)][:30] + same_area))
        proj = {"기관": a.org, "사업명": a.name, "신설변경": "미상"}
        proj.update({k: v for k, v in (("지원대상", a.target), ("선정기준", a.criteria), ("지원내용", a.content)) if v})
        from llm import cache_tag
        ckey = hashlib.sha1((json.dumps([proj, cands], ensure_ascii=False) + cache_tag()).encode("utf-8")).hexdigest()[:16]
        rec = judge_similar(proj, cands, loc_by_id, PROPOSAL_CACHE / f"e1v3_{ckey}.json", seed_key=ckey, clarify=True, backend=a.backend)
        order = {s: n for n, s in enumerate(cands)}
        groups = {g: [] for g in ("같은 지자체", "같은 광역 본청", "같은 시도", "다른 시도")}
        for s, v in rec["labels"].items():
            if v["판정"] in ("동일", "유사"):
                l = loc_by_id[s]
                groups[relation(a.org, l)].append({"servId": s, "시도": l["ctpvNm"], "시군구": l["sggNm"], "사업명": l["servNm"], "판정": v["판정"], "근거": v["근거"]})
        for g in groups.values():
            g.sort(key=lambda x: (x["판정"] != "동일", order[x["servId"]]))
        rep["similar_v3"] = {"groups": groups, "후보수": len(cands), "미응답": rec.get("missing", []),
                             "주의": "AI 판정(동일·유사)만 보인다. E1 측정에서 같은 지자체·광역 후보의 AI 정밀도가 낮았다(5/15). 반드시 원문을 확인한다."}

    # D. 협의 이력
    hist = load_csv(HIST)

    def nrm(s):
        return re.sub(r"[\s\(\)\[\]·ㆍ,\.\-_/「」『』]", "", re.sub(r"^\(.*?\)\s*|^\[.*?\]\s*", "", s))
    hs = []
    for h in hist:
        sc = difflib.SequenceMatcher(None, nrm(a.name), nrm(h["사업명"])).ratio()
        kw = sum(1 for w in kws if w in h["사업명"])
        hs.append((sc + 0.1 * kw, h))
    hs.sort(key=lambda x: -x[0])
    rep["history"] = [{"연번": h["연번"], "기관": h["협의요청기관"], "신설변경": h["신설변경"], "사업명": h["사업명"], "결과": h["협의결과"], "점수": round(s, 2)} for s, h in hs[:5]]
    rep["history_note"] = "2025년 협의완료 안건(사업명·기관·결과만). 승인 사유·조건 조정 내용은 없다."

    # E. 보류
    if a.amount is None:
        rep["hold"].append("지원액이 없어 상한 대조 불가")
    if not a.cycle:
        rep["hold"].append("지급 주기(월/연/1회)가 없어 연환산 불가")
    if a.income is None and not (mine and mine.get("income_type") == "소득무관"):
        rep["hold"].append("소득 기준이 없어 중위소득 요건 대조 불가(유형에 기준이 있는 경우)")
    if not rep["similar"]["같은시도(광역본청)"]:
        rep["hold"].append("광역 본청 사업 중 문자 기준 유사 후보 없음 → 광역 중복은 내용으로 확인 필요" if any(prov)
                           else "광역(시도) 사업 목록 미확보 → 광역 중복 미확인")
    rep["hold"].append("중앙부처 사업은 이름·요약 기준 후보만 제시(지원조건 원문 미확보) → 중앙 중복·보충은 담당자 확인" if cen
                       else "중앙부처 목록 파일이 없어 중앙 중복 미확인")

    rep["eval"] = eval_fields(rep, a.org)
    if a.v5:  # v5.4: '확인불가'에도 가장 그럴듯한 답을 잠정 권고로 붙인다. 확정은 담당자 결재. 채점(eval)은 바꾸지 않는다.
        e = rep["eval"]
        if e["유형판정"] != "확인불가":
            tent = e["유형판정"]
        elif e["유형연번"] == "해당없음" or "밖" in (e["대상"], e["상한"]):
            tent = "일반"
        else:
            tent = "신속"
        checks = []
        if e["유형판정"] == "확인불가":
            v2r = rep.get("v2") or {}
            if v2r.get("conflict_note"):
                checks.append(v2r["conflict_note"])
            elif v2r.get("type_match") == "가까움":
                checks.append(f"유형 {e['유형연번']}번이 급여 방식만 다른 가까운 유형임 → 이 유형으로 볼지")
            if e["대상"] == "확인불가":
                checks.append("대상 범위: " + cell((v2r.get("근거") or ["", ""])[0], 90))
            if e["상한"] == "확인불가":
                checks.append("상한: " + cell((v2r.get("근거") or ["", ""])[1], 90))
            checks += [f"{g['점검']}: {g['설명']}" for g in v2r.get("guards") or [] if not g["통과"]]
        if (rep.get("v2") or {}).get("conflict_note") and rep["v2"]["conflict_note"] not in checks:  # v5.6 F3′: 판정과 상관없이 보인다
            checks.insert(0, rep["v2"]["conflict_note"])
        rep["tentative"] = {"권고": tent, "결재필요": True, "확인항목": checks,
                            "설명": "확인 항목이 남은 권고는 담당자 결재 전에는 확정이 아니다" if checks else "확인 항목 없음. 그래도 판정은 담당자가 한다"}

    # F. 복지로 등록 초안·차이표
    frows = draft_bokjiro(a, rep, loc_by_id)

    # 출력
    L = []
    L.append(f"# 협의 준비 초안 (v1) — {a.name} / {a.org}\n")
    L.append("> 판정 아님. 담당자 확인용 초안. 출처: 2026 협의운용지침(사회보장위원회 2026-03-03, 신속 유형 표 11/2 원문 검수), 복지로 지자체 복지서비스(2026-11 수집), 중앙부처 복지서비스정보, 2025 협의완료 부록.\n")
    ex = rep["extraction"]
    if ex:
        L.append(f"## 0. 사업안에서 뽑은 값 (LLM {ex['backend']}, 근거 구절 원문 대조)")
        L.append("| 항목 | 값 | 비고 |\n|---|---|---|")
        for k, v in ex["filled"].items():
            L.append(f"| {k} | {cell(v, 80)} | {'원문에 그대로 없음 → 확인' if k in ex['evidence_failed'] else 'LLM 추출(명시 인자 없음)'} |")
        it = ex["item"] or {"life": [], "household": [], "income_type": (ex.get("profile") or {}).get("income_type", "미상"),
                            "income_median_pct": (ex.get("profile") or {}).get("income_median_pct"), "region_type": "미상", "conditions": []}
        L.append(f"| 생애주기·가구 | {', '.join(it['life']) or '미상'} / {', '.join(it['household']) or '미상'} | 근거: {cell(it.get('age_evidence') or '-', 40)} |")
        L.append(f"| 소득·지역 | {it['income_type']}{' ' + str(it['income_median_pct']) + '%' if it['income_median_pct'] else ''} / {it['region_type']} {it.get('region_name') or ''} | 근거: {cell(it.get('income_evidence') or '-', 40)} |")
        for c in it.get("conditions", []):
            L.append(f"| 조건({c['join']}{', 예외' if c['exception'] else ''}) | {cell(c['text'], 60)} | 근거: {cell(c['evidence'], 50)} |")
        L.append(f"\n> 근거 구절 불일치: {ex['evidence_failed'] or '없음'}. 명시한 인자는 추출값보다 우선한다.\n")
    L.append("## A. 협의제외 후보")
    L += [f"- {e['유형']}: 일치어 {e['일치어']} ({e['출처']})" for e in rep["exclude"]] or ["- 해당 키워드 없음(협의 대상으로 가정; 지침 Ⅱ.3 전문 확인)"]
    if rep.get("v2"):
        v = rep["v2"]
        L.append(f"- **v2 지침 대조**: 협의제외 {v['excluded']} — {v['exclude_clause'] or '-'} (근거: {cell(v['exclude_evidence'] or '-', 60)})")
    if rep.get("tentative"):
        t = rep["tentative"]
        L.append(f"\n> **잠정 권고: {t['권고']}** (도구 판정: {rep['eval']['유형판정']}) · 담당자 결재 필요")
        for c in t["확인항목"]:
            L.append(f"> - 확인할 것: {c}")
        for pr in (rep.get("v2") or {}).get("precedents") or []:
            L.append(f"> - 참고한 담당자 확정 선례 {pr['선례']} {cell(pr['사업명'], 30)} → 유형 {pr['확정'].get('유형연번')}, {pr['확정'].get('유형판정')}")
    L.append("\n## B. 서식 1-2 사전 체크리스트 초안 (신속협의)")
    if rep.get("v2"):
        v = rep["v2"]
        L.append(f"> **v2 유형 선택**: {v['type_no']}{' · ' + v['유형'] if v['유형'] else ''} → 대상 {v['대상판정'] or '-'}, 상한 {v['상한판정'] or '-'}. "
                 f"이유: {cell(v['type_reason'], 120)} (근거: {cell(v['type_evidence'] or '-', 60)}; 함께 볼 유형 {', '.join(v['alt_types']) or '없음'})\n")
        if v.get("중복위반"):
            L.append(f"> **v3 대조**: 대상 — {cell(v['근거'][0], 120)} · 중복·보충 조건 {'위반' if v['중복위반'] == '예' else '위반 근거 없음'}"
                     f"{' (근거: ' + cell(v.get('dup_evidence') or '-', 60) + ')' if v['중복위반'] == '예' else ''}\n")
    L.append("| 항목 | 초안 | 근거 |\n|---|---|---|")
    L.append(f"| 1 기초지방자치단체인가 | {'예' if sgg and sgg != '본청' else '아니오(광역·중앙은 신속 대상 아님)'} | 지침 Ⅱ.5 |")
    if rep["fast"]:
        f0 = rep["fast"][0]
        L.append(f"| 2 신속협의 목록의 동일(유사) 사업 | 후보: {f0['분야']} / {f0['유형']} (연번 {f0['연번']}) | 신속협의_유형_2026.csv |")
        L.append(f"| 5 대상·지원수준 범위 내 | **{f0['판정후보']}** | {'; '.join(f0['근거'])} |")
    else:
        L.append("| 2 신속협의 목록의 동일(유사) 사업 | 후보 없음 → 일반협의 경로 검토 | |")
    L.append(f"| 3 유사 광역사업 확인 | {'후보 ' + str(len(rep['similar']['같은시도(광역본청)'])) + '건' if rep['similar']['같은시도(광역본청)'] else '**문자 기준 후보 없음 → 내용 확인(보류)**'} | 복지로 공개본 |")
    L.append("| 4 광역사업과 중복 제거 | 담당자 확인 | |")
    for f in rep["fast"][1:]:
        L.append(f"- 다른 유형 후보: {f['분야']} / {f['유형']} → {f['판정후보']} ({'; '.join(f['근거'])})")
    L.append("\n## C. 서식 1-1 자가진단 ② 유사·중복성 초안 (일반협의)")
    for key in ("같은시군구", "같은시도(광역본청)", "전국", "중앙부처"):
        if key not in rep["similar"]:
            continue
        L.append(f"### {key}")
        L += [f"- [{s['servId']}] {s['시도']} {s['시군구']} — {s['사업명']} ({s['점수']}) : {s['요약']}" + (f"  \n  조건 차이: {s['조건차이']}" if s.get("조건차이") else "")
              for s in rep["similar"][key]] or ["- 후보 없음"]
    L.append(f"\n> {rep['similar']['주의']}")
    if rep.get("similar_v3"):
        sv = rep["similar_v3"]
        L.append(f"\n## C′. 비교 대상 후보 — AI 판정, 지역별 (v3; 후보 {sv['후보수']}개 중 동일·유사)")
        for g, items in sv["groups"].items():
            show = items if g != "다른 시도" else items[:5]
            L.append(f"### {g} ({len(items)}건{', 앞 5건만 표시' if g == '다른 시도' and len(items) > 5 else ''})")
            L += [f"- **{x['판정']}** [{x['servId']}] {x['시도']} {x['시군구'] or '(본청)'} — {x['사업명']}  \n  근거: {x['근거']}" for x in show] or ["- 없음"]
        L.append(f"\n> {sv['주의']}")
    L.append("\n## D. 관련 협의 이력 (2025 협의완료 부록)")
    L += [f"- #{h['연번']} {h['기관']} {h['신설변경']} — {h['사업명']} → {h['결과']}" for h in rep["history"]]
    L.append(f"\n> {rep['history_note']}")
    L.append("\n## E. 확인하지 못한 항목 (보류)")
    L += [f"- {h}" for h in rep["hold"]]
    L.append("\n## F. 복지로 등록 초안 · 현행화 차이표 (협의 완료 뒤, 지침 Ⅶ)")
    L.append("| 항목 | 초안 | 근거 | 현재 복지로 | 차이 |\n|---|---|---|---|---|")
    for r in frows:
        L.append(f"| {r['항목']} | {r['초안']} | {r['근거']} | {r['현재 복지로']} | {r['차이']} |")
    L.append(f"\n> 출처: {rep['bokjiro']['source']}. {rep['bokjiro']['note']}")
    md = "\n".join(L)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
