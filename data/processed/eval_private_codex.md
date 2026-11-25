# 추출 정확도 (private, codex, 2026-11-02 11:05)

사람 라벨 40건. 기준선은 복지로 기존 태그(생애주기·가구상황만 있고 나머지 항목은 태그 자체가 없음).
정규화: '미상' = 빈 목록, 오타(융지→융자, 바우처/이용권→바우처·이용권), 소득 자격에 여러 값을 적은 라벨은 모델 값이 그 안에 있으면 일치.

| 항목 | 모델 일치(원 채점) | 모델 일치(정규화) | 모델 자카드(정규화) | 기존 태그 일치(정규화) | 기존 태그 자카드 |
|---|---:|---:|---:|---:|---:|
| life | 25% | 72% | 0.79 | 55% | 0.64 |
| household | 40% | 45% | 0.50 | 35% | 0.40 |
| income_type | 65% | 85% | 0.85 | 태그 없음 | 태그 없음 |
| income_median_pct | 100% | 100% | 1.00 | 태그 없음 | 태그 없음 |
| region_type | 90% | 90% | 0.90 | 태그 없음 | 태그 없음 |
| support_form | 80% | 82% | 0.88 | 태그 없음 | 태그 없음 |

근거 구절 불일치 비율: 0%

## 정규화 뒤에도 남은 불일치

| id | 항목 | 사람 | 모델 |
|---|---|---|---|
| PRV0322 | life | 아동;청소년 | ['아동', '청소년', '청년'] |
| PRV0008 | life | 청년 | [] |
| PRV0033 | life | 아동;청소년 | ['아동'] |
| PRV0015 | life | 아동;청소년 | ['아동'] |
| PRV0184 | life | 아동;청소년 | ['영유아', '아동', '청소년'] |
| PRV0240 | life | 미상 | ['아동'] |
| PRV0074 | life | 미상 | ['아동'] |
| PRV0007 | life | 청년 | [] |
| PRV0230 | life | 아동;청소년;청년 | ['아동'] |
| PRV0117 | life | 미상 | ['노년'] |
| PRV0046 | life | 미상 | ['아동', '청소년', '노년'] |
| PRV0068 | household | None | ['저소득'] |
| PRV0322 | household | None | ['저소득'] |
| PRV0185 | household | None | ['한부모·조손', '기타'] |
| PRV0303 | household | None | ['다문화·탈북민'] |
| PRV0100 | household | None | ['한부모·조손'] |
| PRV0033 | household | None | ['장애인'] |
| PRV0279 | household | None | ['저소득'] |
| PRV0015 | household | 저소득 | ['저소득', '장애인'] |
| PRV0163 | household | None | ['다문화·탈북민'] |
| PRV0134 | household | None | ['장애인'] |
| PRV0184 | household | None | ['장애인'] |
| PRV0240 | household | None | ['장애인'] |
| PRV0238 | household | None | ['다문화·탈북민'] |
| PRV0289 | household | 저소득 | ['장애인', '저소득'] |
| PRV0300 | household | None | ['다문화·탈북민'] |
| PRV0293 | household | 미상 | ['장애인'] |
| PRV0321 | household | 저소득 | ['저소득', '장애인'] |
| PRV0007 | household | 저소득 | [] |
| PRV0042 | household | None | ['다문화·탈북민'] |
| PRV0230 | household | 저소득 | ['저소득', '한부모·조손'] |
| PRV0117 | household | None | ['저소득', '장애인'] |
| PRV0046 | household | None | ['저소득', '장애인', '1인가구', '기타'] |
| PRV0054 | income_type | 소득무관 | 미상 |
| PRV0141 | income_type | 미상 | 기타소득기준 |
| PRV0279 | income_type | 미상 | 기초생활수급 |
| PRV0195 | income_type | 기초생활수급;차상위 | 기타소득기준 |
| PRV0117 | income_type | 미상 | 차상위 |
| PRV0046 | income_type | 미상 | 기타소득기준 |
| PRV0054 | region_type | 지역무관 | 미상 |
| PRV0210 | region_type | 지역무관 | 미상 |
| PRV0195 | region_type | 미상 | 지역무관 |
| PRV0117 | region_type | 미상 | 거주지한정 |
| PRV0008 | support_form | 현금 | ['현금', '현물'] |
| PRV0240 | support_form | 미상 | ['현물'] |
| PRV0195 | support_form | 현금;현물;서비스 | ['현금', '현물'] |
| PRV0043 | support_form | 바우처,이용권 | ['서비스'] |
| PRV0042 | support_form | 현금 | ['현물', '현금'] |
| PRV0117 | support_form | 미상 | ['서비스'] |
| PRV0046 | support_form | 현금;서비스 | ['현금', '현물', '서비스'] |
