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
- `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 최신 `develop` 기준 243개 테스트를 실행해 통과했다.
- `bash -n`, workflow 단계 순서·입력 전달 정적 확인, `git diff --check`가 통과했다.
- IaC 적용으로 개발 EC2와 전용 SSM 문서를 생성했고, AI `develop` Environment에 `EC2_INSTANCE_ID`를 등록했다. 임시 도메인의 HTTPS와 API→AI 내부 health도 확인했다.
- 최신 `develop` 기준 통합 검증에서 shell test와 기존 가상환경을 읽기 전용으로 사용한 `PYTHONDONTWRITEBYTECODE=1 /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`가 통과했다. 배포 workflow는 ECS를 검증한 뒤 같은 SHA를 EC2에 전달한다.
- 이 PR 병합 후 `workflow_dispatch`로 실제 재배포를 검증한다. 기존 ECS·ALB는 해당 검증과 개발 DNS 전환이 끝날 때까지 유지한다.
