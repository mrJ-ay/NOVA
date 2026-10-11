# NOVA ONEID 전환 안내

NOVA 로그인은 ONEID PKCE 흐름을 사용합니다. 기존 NOVA 계정은 처음 로그인할 때 예전 이메일/비밀번호를 한 번 입력해 ONEID와 연결할 수 있습니다. 연결 정보는 서버의 전용 `oneid_links` 테이블에 저장되고, 해당 계정의 기존 영상 소유자 UUID와 Storage 경로를 유지합니다. 새 NOVA 사용자는 ONEID 계정으로 바로 시작합니다.

## Supabase 준비

`backend/002_oneid_sso.sql`을 NOVA Supabase 프로젝트에서 실행하세요. 이 스크립트는 기존 영상을 수정하지 않고, 기존 계정 연결용 private-to-client RLS 테이블을 만들며 새 ONEID UUID를 저장할 수 있도록 `videos.user_id`의 Supabase Auth 외래 키를 해제합니다.

## Render 환경변수

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` (공개 영상 조회 및 기존 계정의 1회 확인)
- `SUPABASE_SERVICE_ROLE_KEY` (백엔드 전용; 프론트엔드에 넣지 마세요)
- API와 프론트엔드 각각 `ONEID_API_URL` (ONEID 공개 HTTPS 주소)

ONEID 서버의 `ONEID_CLIENT_REDIRECT_URIS`에는 NOVA 프론트엔드의 정확한 `/login.html` 주소를 `nova` 클라이언트로 등록하고, `ONEID_ALLOWED_ORIGINS`에는 프론트엔드 origin을 추가해야 합니다.

## 로컬 개발

NOVA 프론트엔드는 포트 5503, NOVA API는 포트 8003, ONEID는 포트 8000에서 실행하는 구성을 기본으로 합니다. `frontend/oneid-config.js`의 ONEID 주소는 로컬 기본값이며 Render 빌드에서 `ONEID_API_URL` 환경변수로 교체됩니다.