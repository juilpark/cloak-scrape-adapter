# AGENTS.md

## 프로젝트 목표

Python 3.12와 CloakBrowser의 비동기 Playwright API로 Firecrawl의
Playwright 마이크로서비스와 호환되는 독립 HTTP 어댑터를 유지한다.

기존 Compose의 브라우저 서비스 이미지 값만 교체해 사용할 수 있어야 하며,
기본적으로 `0.0.0.0:3000`에서 `GET /health`와 `POST /scrape`를 제공한다.

## Clean-room 경계

- Firecrawl 소스 코드를 복사, 번역, 포팅하지 않는다.
- 공개된 HTTP 계약과 외부에서 관찰 가능한 동작만 참고한다.
- Firecrawl의 구현 세부가 필요하면 독립 테스트 케이스로 먼저 표현한다.
- 이 저장소의 코드는 MIT로 배포하며 Firecrawl 또는 CloakHQ의 공식 프로젝트인
  것처럼 표현하지 않는다.
- Firecrawl 코드를 가져와야 하는 변경은 즉시 중단하고 AGPL 적용 범위를
  다시 검토한다.

## 코드 구조

- `src/cloak_scrape_adapter/app.py`: FastAPI 수명주기, 라우트, 예외 매핑
- `src/cloak_scrape_adapter/browser.py`: 브라우저, 동시성, Context/Page 정리
- `src/cloak_scrape_adapter/models.py`: HTTP 모델과 환경 설정
- `src/cloak_scrape_adapter/security.py`: URL, DNS, SSRF 검사
- `tests/`: 실제 브라우저를 시작하지 않는 단위 테스트
- `requirements.lock`: `uv.lock`에서 생성한 Docker runtime 전용 해시 lock

초기 구현은 작게 유지하고 정당한 이유 없이 새 프레임워크나 추상화 계층을
추가하지 않는다.

## 호환 계약

`GET /health`는 실제 BrowserContext와 Page 생성이 가능할 때만 `200`을
반환한다.

```json
{
  "status": "healthy",
  "maxConcurrentPages": 10,
  "activePages": 0
}
```

`POST /scrape`는 다음 필드만 지원한다.

- `url` (필수)
- `wait_after_load` (기본 `0`)
- `timeout` (기본 `15000`)
- `headers`
- `check_selector`
- `skip_tls_verification` (기본 `false`)

원격 HTTP 오류는 어댑터 HTTP `200` 응답 안의 `pageStatusCode`와 선택적
`pageError`로 표현한다. 잘못된 요청은 `400`, 내부 오류는 `500`, 차단된
목적지는 HTTP `200` 본문의 `pageStatusCode: 403`으로 반환한다.

JSON과 `text/plain`은 원문 body를 반환하고 HTML은 렌더링된 DOM을 반환한다.

## 브라우저 수명주기

- 프로세스마다 `launch_async()`로 Browser 하나를 공유한다.
- 요청마다 BrowserContext와 Page를 만들고 `finally`에서 모두 닫는다.
- `MAX_CONCURRENT_PAGES` 크기의 `asyncio.Semaphore`를 사용한다.
- Uvicorn worker는 하나만 사용하고 수평 확장은 컨테이너 복제로 한다.
- 명시적 User-Agent가 없으면 CloakBrowser 기본 fingerprint를 보존한다.
- viewport를 임의로 고정하지 않는다.
- Cookie 헤더는 context cookie jar에 넣고 나머지 헤더만 Page에 설정한다.
- 브라우저 재시작은 한 호출에서 한 번만 시도하며 무한 루프를 만들지 않는다.

## SSRF 보안

- `http`와 `https`만 허용한다.
- 최초 URL, 리다이렉트, 모든 서브리소스를 검사한다.
- 모든 DNS 결과 중 하나라도 loopback, private, link-local, multicast,
  unspecified 또는 reserved이면 차단한다.
- IPv4-mapped IPv6도 IPv4 규칙으로 검사한다.
- DNS 실패와 빈 응답은 기본 차단한다.
- `ALLOW_LOCAL_WEBHOOKS=true`만 명시적인 사설망 접근 허용으로 취급한다.
- URL userinfo, 프록시 비밀번호, 라이선스 키를 로그와 응답에 노출하지 않는다.

애플리케이션의 DNS 검사와 브라우저 연결 사이에는 DNS rebinding race가
남는다. 신뢰할 수 없는 외부 요청을 받는 배포에서는 egress 방화벽 또는
검증 프록시를 함께 사용한다.

## 환경 변수

다음 이름과 기본값을 유지한다.

| 변수 | 기본값 |
|---|---:|
| `PORT` | `3000` |
| `MAX_CONCURRENT_PAGES` | `10` |
| `BLOCK_MEDIA` | `false` |
| `ALLOW_LOCAL_WEBHOOKS` | `false` |
| `HEADLESS` | `true` |
| `CLOAKBROWSER_CACHE_DIR` | `/home/app/.cloakbrowser` |
| `CLOAKBROWSER_AUTO_UPDATE` | `false` |

선택 값은 `PROXY_SERVER`, `PROXY_USERNAME`, `PROXY_PASSWORD`,
`CLOAKBROWSER_LICENSE_KEY`, `CLOAKBROWSER_VERSION`이다.

## 컨테이너와 라이선스

공개 이미지는 CloakBrowser Chromium 바이너리를 포함하면 안 된다.

Docker build와 공개 CI에서 다음을 금지한다.

- `python -m cloakbrowser install`
- `ensure_binary()`
- `launch()` 또는 `launch_async()`
- `FROM cloakhq/cloakbrowser`
- CloakBrowser 이미지에서 바이너리를 복사하는 작업

공개 이미지에는 MIT wrapper와 Chromium 런타임 라이브러리만 설치한다.
바이너리는 최종 운영자가 컨테이너를 처음 실행할 때 CloakHQ 공식 채널에서
직접 다운로드한다. 라이선스 키는 런타임 secret으로만 전달한다.

CloakBrowser Binary License의 재배포 및 OEM/SaaS 조건은 wrapper의 MIT와
별개다. 외부 고객에게 브라우저 기능을 API로 제공하는 변경은 별도 라이선스
확인 없이 진행하지 않는다.

## 검증

변경 전후 다음 명령을 실행한다.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv export --frozen --no-dev --no-emit-project --format requirements-txt \
  --output-file requirements.lock
docker build -t cloak-scrape-adapter:test .
docker run --rm --user 0 --entrypoint python \
  -v "$PWD/scripts/assert_binary_free.py:/tmp/assert_binary_free.py:ro" \
  cloak-scrape-adapter:test /tmp/assert_binary_free.py
```

단위 테스트나 public workflow에서 실제 CloakBrowser를 시작하지 않는다.
라이선스 키와 바이너리가 필요한 통합 테스트는 opt-in으로 분리하고 cache를
artifact나 image layer로 업로드하지 않는다.

`requirements.lock`은 직접 편집하지 않는다. 의존성을 바꾼 경우 위
`uv export` 명령으로 다시 만들고 `uv.lock`과 함께 커밋한다.
