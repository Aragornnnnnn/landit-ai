# LAN-373 출시 전 게이트 실측 결과 (2026-08-27 확정)

승인된 두 게이트(EN_AU 의사-화자 E2E, 최종 회귀 지연)의 실측 기록. 실서버 HTTP E2E,
참조 오디오는 실제 CDN(d19azau1un4t7r.cloudfront.net) 서빙으로 수행해 CDN 경로까지 검증했다.

## 게이트 B — 최종 회귀 (골든 셋 12샘플 × 2회, E2E)

**정확일치 24/24.** 1차 실행에서 18/24로 떨어진 원인은 판정용 침묵 컷이 골든 오디오의
1.1초 리드인까지 잘라 판정 유형을 바꾼 것(s2_stress STRESS→SOUND, 원본/컷 대조로 재현
확인). 컷을 "2초 이상 잘릴 때만 적용"으로 고쳐 회복했다. 대칭 트림(참조도 컷)은 다른
샘플에서 미검출 회귀를 만들어 배제했다.

### 지연 기준 재정의 (기획 승인)

원래 문구 "p50 ≤ 5초"는 무오류 경로를 상정한 것이었다. 오류 경로는 묘사 호출(LLM 1회
직렬 추가)이 구조적으로 붙는다 — 묘사(userDisplay·코칭 재료)는 UI 요구사항이라 뺄 수 없다.

| 확정 기준 | 실측 | 판정 |
| --- | --- | --- |
| 무오류 경로 p50 ≤ 5초 | 4.5초 (3.9~5.7) | 통과 |
| 오류 경로 p90 ≤ 12초 | 10.3초 (max 11.1, BE 타임아웃 20초) | 통과 |

**후속 이슈 (필수)**: 오류 경로 7~11초는 실유저가 자주 타는 경로다 — 발음 연습 기능
특성상 특히 초반에는 틀리는 유저가 많을 수 있다("대부분 정상 발음"은 가정이지 사실이
아님). **FE에 분석 중 로딩 UI(진행 표시)가 필요하다.** 앱 이슈로 등록할 것.

## 게이트 A — EN_AU 의사-화자 E2E (Apple Karen/Samantha, 참조=CDN)

1차 실행에서 호주 정상 발화가 4/4 오탐됐다(water flap, can't). 원인: 실제 호주 발화는
flap·BATH 변이로 미국식과 겹치는데, 참조(theia)가 영국식으로 생성된 인스턴스에서 대조가
살아남아 정당한 호주 발음을 벌했다.

### 정책 확정 (기획 추인): EN_AU 억양 대조 전면 비활성화

호주 튜터 유저는 억양 대조 힌트 없이 본 판정(발음·강세)만 받는다. 근거:

- espeak의 호주 발음이 영국과 사실상 동일해 AU 대조는 처음부터 독자적 근거가 약했다
- 실측(게이트 A 1차)에서 정당한 호주 발음이 오탐됐다 — 오탐으로 벌하는 것보다 힌트를
  빼는 것이 낫다 (오탐 제로 원칙)

재실행 결과: 호주 화자 8회 중 7회 깨끗, 1회는 본 판정의 회차 변동(서로 다른 합성 엔진 간
대조, run2 통과)으로 알려진 변동(~1.7%) 범위. 미국식 발화가 AU 기준에서 허용되는 것도
정책대로 확인.

## 게시 개수 세 숫자 정정 (장부)

| 숫자 | 정체 |
| --- | --- |
| **29,157** | 오디오 자산 정본 — 매니페스트 = S3 실측 mp3, 1:1 일치 |
| 29,147 | 전량 배치에서 신규 업로드된 mp3 (기존 샘플 10개 재사용 제외) |
| 29,169 | 진행률 보고에 쓴 잘못된 분모 (기존 객체 11개를 21개로 오산) — 기록상 정정 |

최종 확정은 BE 임포트 후 coverage(빈 배열 2개)로 한다.

## BE 임포트 키 최종본 (2026-08-27 기준 · 이것만 사용)

```
reference EN_US: content/expression-pronunciation-audio/reference/EN_US-8ead1be2c8e9b3b9155ce81c4ba2f0a53c894805a16c5347efeecddf3f9d83e8.json
reference EN_GB: content/expression-pronunciation-audio/reference/EN_GB-d776b0a1216ad49a76e390e2c65055bdd4f01cd7d8f07513c92bd4b72c3eab6e.json
reference EN_AU: content/expression-pronunciation-audio/reference/EN_AU-e2eb9521a3c7bd710d78d71595d035485c0b071a68ca2ccb0bbe372c84a5da2e.json  ★ 신규
be manifest    : content/expression-pronunciation-audio/manifests/be-d2abf4aa4d5651fd5a8097a218f66696a5aa4e5e98af6aaf3cb0f3544a7da759.json
```

- **EN_AU 옛 키(be18ae8f…)는 폐기** — AU 대조 비활성화 전 데이터라, 그 키로 임포트하면
  오탐을 유발하는 낡은 대조 힌트가 DB에 들어간다
- be manifest는 단어 구성이 안 바뀌어 기존 키 그대로
- 임포트에서 500이 나오면 IAM apply(terraform-apply-production) 선행 여부부터 확인
  (AccessDenied가 500으로 매핑되는 알려진 동작)
