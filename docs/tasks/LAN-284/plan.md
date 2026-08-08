# LAN-284 작업 계획

- [x] 사용자 checkout과 분리된 `feat/LAN-284` worktree를 `origin/develop` 기준으로 생성한다.
- [x] SSM Run Command helper의 입력 검증, 상태 조회, 실패 전파, 비밀 출력 방지 계약을 shell test로 작성한다.
- [x] ECS 검증 성공 후 동일한 `${GITHUB_SHA}`를 AI 개발 EC2에 배포하도록 workflow를 연결한다.
- [x] shell test와 전체 unittest로 변경을 검증한다.

## 구현 결정.

- helper는 `/opt/landit/bin/deploy-service ai <40자 소문자 SHA>`만 실행한다.
- SSM의 일시적인 `InvocationDoesNotExist`만 최대 30회까지 재시도하며, 다른 AWS 오류와 terminal status는 즉시 실패한다.
- AWS CLI의 원문 오류와 command output은 workflow 로그로 전달하지 않는다.

## 검증 결과.

- `bash .github/scripts/test/deploy-ec2-service_test.sh`가 통과했다.
- `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 241개 테스트를 실행해 통과했다.
- `bash -n`, workflow 단계 순서·입력 전달 정적 확인, `git diff --check`가 통과했다.
- Task 7 재검증에서 shell test와 기존 가상환경을 읽기 전용으로 사용한 `PYTHONDONTWRITEBYTECODE=1 /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 다시 통과했고 unittest 241개를 실행했다. IaC·BE와 교차 검토해 ECS 검증 다음에 같은 SHA만 EC2로 전달되고, 실제 `EC2_INSTANCE_ID` 등록·EC2 배포·DNS·health 관찰은 미실행임을 확인했다.
