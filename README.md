# 협의 준비 도우미

지자체가 사회보장 사업을 새로 만들거나 바꿀 때 보건복지부와 협의하는 서식을, 공개 데이터와 원문 근거로 채워 주는 시제품입니다. 정확도는 미리 고정한 정답으로 재고, 그 기록을 함께 둡니다.

- 「2026 사회보장 데이터를 활용한 AI 혁신 아이디어 경진대회」(대구가톨릭대학교·한국사회보장정보원)에 2026년 11월 14일 제출했고, 11월 25일 서류심사에서 떨어졌습니다. 탈락 사유와 점수는 알려지지 않았습니다.
- 제출한 제안서: [`제안서/제안서_v1.15.pdf`](제안서/제안서_v1.15.pdf)

> **English summary.** A prototype that drafts the consultation forms Korean local governments file with the Ministry of Health and Welfare when they create or change a social-security program: it picks the matching fast-track type out of 79, checks eligibility and benefit caps against the guideline, and finds existing programs to compare, citing the source sentence for every value and flagging what it cannot verify. Accuracy was measured against answer keys frozen before each run (pre-registered, sha256-recorded). On 79 held-out consultation cases the LLM found the right type more often than a keyword rule (27 vs 22 of 35), but its final fast-track/general verdict was barely better than the rule (56 vs 54 of 79). Submitted to a 2026 public-sector idea contest; not shortlisted.

## 무엇을 하나

사업안(협의요청서 글이나 복지로 등록 원문)을 넣으면 아래를 냅니다. 판정은 담당자가 합니다.

1. 대상·선정기준·지원내용을 뽑고, 뽑은 값마다 원문 구절을 붙여 원문과 맞는지 확인합니다(LLM).
2. 협의제외 여부와 79개 신속협의 유형 가운데 맞는 유형을 고릅니다(LLM).
3. 대상과 지원 상한을 규칙 코드로 대조합니다. 구간별·비율 상한, 지급 주기 환산, 광역·기초 구분을 다룹니다.
4. 비교할 기존 사업 후보를 '동일·유사·무관'으로 판정하고, 같은 지자체·광역 / 같은 시도 / 다른 시도로 묶습니다(LLM).
5. 근거가 없거나 확인하지 못한 항목은 '확인 필요'로 넘깁니다. 신속을 권하기 전에 여섯 가지 점검(근거 구절, 지급 주기, 지시문 의심, 금액 출처, 금액 범위, 더 큰 금액)을 통과해야 합니다.

## 잰 결과

정답은 도구를 돌리기 전에 사람이 판정해 고정했습니다(`data/labels/`, 해시는 `data/labels/README.md`). 아래는 개발에 쓰지 않은 시험 사례입니다.

| 지표 | 표본 | 비교 기준 | AI |
|---|---|---|---|
| 해당 유형이 있는 사업안의 유형 찾기 | 대구·경북 밖 협의 사례 79건 중 35건 | 키워드 규칙 22/35 | 27/35 |
| 유형이 없는 사업안에 유형을 잘못 붙임(적을수록 좋음) | 같은 79건 중 44건 | 규칙 16 | 5 |
| 최종 판정(협의제외·신속·일반) | 79건 | 규칙 54/79, '항상 일반' 35/79 | 56/79 |
| 신속을 잘못 권함 | 79건 | 규칙 2 | 3 |
| 비교 대상 판정 | 대구·경북 협의 96건의 후보 675쌍 | 사업명 유사도 정밀도 93%·재현율 72% | 정밀도 90%·재현율 90% |

- 판정은 규칙과 거의 같습니다(2건 차이). 확인된 이득은 유형 찾기와 비교 대상을 덜 놓치는 것입니다.
- 개발 세트에서 오른 점수(v5, 99건 중 78 → 86)는 새 시험 40건(E2d)에서 재현되지 않았습니다. `30_analysis/결과_E2d_요약.md`
- 정보공개청구로 받은 실제 협의요청서 6건도 넣어 봤습니다. 광역 4건은 일반, 경산시 건은 지자체가 요청한 구분과 같은 신속으로 나왔습니다. 칠곡군 출산장려금(첫째아 포함)은 지침 6번 유형의 이름('2자녀 이상')과 상한 칸('출생순위 관계없이')이 엇갈리는 경계였습니다. 이 6건에서 결함 4개를 찾아 v5.6에서 고쳤습니다. `30_analysis/결과_정보공개청구.md`

자세한 표는 `30_analysis/결과_E2c_요약.md`, `결과_E2d_요약.md`, `결과_E1_요약.md`, 합친 값은 `data/processed/e2cd_pooled.json`에 있습니다.

## 한계

- 정답은 제안자 한 사람이 판정했고, 협의 실무자의 확인을 받지 못했습니다.
- 표본이 작습니다(유형 판정 79건, 비교 대상 96건).
- 시험 입력은 협의요청서가 아니라 복지로 등록 원문입니다. 실제 요청서는 6건만 넣어 봤고, 이 6건은 결함을 찾은 사례라 성능 근거로 쓰지 않습니다.
- 처리 시간이나 담당자의 검토 부담은 재지 않았습니다.

## 폴더

| 폴더 | 내용 |
|---|---|
| `scripts/` | 코드. 본체는 `consult_prep.py`, 채점은 `run_e2_eval.py`·`run_e1_eval.py`·`run_regress.py`, 구조화는 `structure_services.py`, 비교 대상 판정은 `similar.py`, LLM 호출은 `llm.py` |
| `data/labels/` | 고정한 정답표와 판정 기준 |
| `data/raw/` | 공공데이터포털 파일데이터와 협의운용지침에서 옮긴 표(출처 `data/raw/SOURCES.md`). 민간복지서비스 파일의 이메일 주소는 가렸습니다 |
| `data/raw/foi/` | 정보공개청구 회신 가운데 글자로 옮긴 것(통계, 요청서 전사본). 개인정보가 있는 원본 스캔은 넣지 않았습니다 |
| `data/processed/` | 지자체·민간 사업 구조화 결과, 시험별 실행 출력, 채점 결과 |
| `30_analysis/` | 사전등록, 결과, 버전별 기록. `시제품_예시/E3/`에 시연 화면(HTML) |
| `제안서/` | 제출한 제안서 PDF, 원고, 사실 확인 기록 |

버전: 제안서의 측정값은 v4 기준입니다. v5.x는 그 뒤의 보완이고, 같은 코드에 `--v5`로 켭니다.

## 돌려 보기

Python 3.12에서 썼습니다. LLM은 `scripts/llm.py`가 명령줄 도구(codex, agy)를 불러 씁니다. 측정 때 모델은 OpenAI GPT-6.1 Sol이었습니다. 다른 모델을 쓰려면 `llm.ask`를 바꾸면 됩니다.

채점만 다시 하기(저장된 출력 사용, LLM 호출 없음):

```bash
python -X utf8 scripts/run_e2_eval.py --set e2c --methods M0 M4 --score
```

사업안 하나 넣기:

```bash
python -X utf8 scripts/consult_prep.py --name "장수축하물품 지급 사업" --org "경상북도 경산시" --text "[선정기준] … [지원내용] …" --v2 --v3 --v4 --v5 --skip-similar --out out.md --json out.json
```

## 넣지 않은 것

참가 서류, 정보공개청구 원본 스캔(공무원 성명이 있음), 내려받은 웹 원문(저작권), LLM 응답 캐시와 실행 로그, 내부 작업 메모와 심사 기록.

## 라이선스

코드는 MIT 라이선스입니다(`LICENSE`). 데이터는 각 출처의 이용 조건을 따릅니다(`data/raw/SOURCES.md`). 시연 화면에 넣은 Pretendard GOV 글꼴은 SIL Open Font License 1.1입니다.
