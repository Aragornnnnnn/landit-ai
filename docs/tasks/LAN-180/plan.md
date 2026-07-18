# LAN-180 작업 계획

- [x] 실제 오류와 표현 선호를 구분하는 회귀 테스트를 추가한다.
- [x] 핵심 교정 차원과 점수·근거·교정 표현의 연결을 검증한다.
- [x] 후보 생성·검수 프롬프트가 한 가지 교정만 다루도록 보강한다.
- [x] 발화에서 확인할 수 없는 구체적인 벤치마크를 일반 문구로 대체한다.
- [x] 익명화한 운영 사례로 실제 OpenRouter 반복 평가를 실행한다.
- [x] 전체 unittest와 OpenAPI 계약을 확인한다.

## 검증 결과.

- `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 통과했다. 173개 테스트를 실행했다.
- OpenAPI에 `primaryFeedbackDimension`과 내부 후보 스키마가 노출되지 않는 것을 확인했다.
- 최종 프롬프트로 OpenRouter에서 6개 사례를 3회씩 평가했으며 18개 결과가 모두 기대 판정과 검증 조건을 통과했다.
