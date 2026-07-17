# LAN-172 Version And Release Automation Implementation Plan

**Goal:** 수동 프로덕션 배포가 성공한 뒤 `ai-v{MAJOR}.{MINOR}.{PATCH}` 태그와 GitHub Release를 생성하고, 같은 릴리즈 규칙을 저장소 문서에 반영합니다.

**Scope:** 별도 애플리케이션 코드, Python 검증기, 테스트 코드는 추가하지 않습니다. 현재 수동 배포 workflow에 필요한 입력과 GitHub 기록 단계만 추가합니다.

## 구현 순서

1. `.github/workflows/deploy-prod-worker.yml`에 필수 `version` 입력을 추가합니다.
2. `main` 브랜치와 `MAJOR.MINOR.PATCH` 형식을 검증하고, 이미 존재하는 `ai-v{version}` 태그를 거부합니다.
3. workflow 권한을 `contents: write`로 올리고 전체 Git 이력을 checkout합니다.
4. ECS 서비스 안정화가 확인된 뒤 annotated tag와 GitHub Release를 생성합니다.
5. `AGENTS.md`, `CONTRIBUTING.md`, `docs/architecture.md`, `design.md`에 실제 workflow와 일치하는 브랜치·버전·승인 규칙을 반영합니다.
6. 변경 파일과 Git diff를 검토합니다.

## 발견 사항

- 현재 프로덕션 배포는 `main`에서 실행하는 수동 `workflow_dispatch`입니다.
- 원격 AI 태그가 아직 없으므로 첫 태그는 배포 workflow의 `version` 입력으로 정합니다.
- workflow가 배포 성공 후 태그를 생성하므로, 배포가 실패하면 태그와 GitHub Release가 생성되지 않습니다.
- PATCH, MINOR, MAJOR 중 어떤 버전을 사용할지는 배포 승인 전에 사람이 결정하고 에이전트는 정책에 맞는 버전을 제안합니다.
- 릴리즈 브랜치 생성 전에 버전이 명시되지 않았다면 에이전트가 먼저 확인하고, workflow 입력에는 같은 버전을 사용합니다.

## 검증

- `git diff --check`로 공백 오류가 없는지 확인합니다.
- workflow에서 태그와 GitHub Release 단계가 ECS 안정화 검증 뒤에 있는지 diff로 확인합니다.
- 문서의 태그 형식, version 입력, 승인 경계가 workflow와 일치하는지 확인합니다.

## 검증 결과

- Ruby YAML 파서로 `.github/workflows/deploy-prod-worker.yml` 문법을 확인했습니다.
- `git diff --check`가 통과했습니다.
- 태그와 GitHub Release 단계가 ECS 안정화 검증 단계 뒤에 위치함을 확인했습니다.
- `actionlint`는 현재 환경에 설치되어 있지 않아 실행하지 못했습니다.
