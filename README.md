# Cloak Scrape Adapter

Firecrawl의 Playwright 마이크로서비스 HTTP 계약을 clean-room 방식으로
독립 구현한 Python 기반 CloakBrowser 어댑터다.

이 프로젝트는 **Firecrawl-compatible, unofficial** 프로젝트이며 Firecrawl
또는 CloakHQ의 공식 프로젝트가 아니다.

## 사용 목적

기존 Compose에서 브라우저 서비스의 이미지 값만 교체한다.

```yaml
services:
  firecrawl-playwright:
    image: ghcr.io/juilpark/cloak-scrape-adapter:0.1.0
```

Firecrawl 쪽 URL은 그대로 유지한다.

```yaml
PLAYWRIGHT_MICROSERVICE_URL: http://firecrawl-playwright:3000/scrape
```

이미지만 교체해도 동작한다. 다만 컨테이너를 다시 만들 때 약 200MB의
CloakBrowser Chromium을 재다운로드하지 않으려면 cache volume을 추가하는
편이 좋다.

```yaml
services:
  firecrawl-playwright:
    volumes:
      - cloakbrowser-cache:/home/app/.cloakbrowser

volumes:
  cloakbrowser-cache:
```

## 제공 기능

- `GET /health`
- `POST /scrape`
- 기본 포트 `3000`
- 프로세스당 CloakBrowser 하나
- 요청당 격리된 BrowserContext와 Page
- 동시 페이지 제한
- 최초 URL, 리다이렉트, 서브리소스의 SSRF 검사
- JSON과 text 응답의 원문 보존
- 선택적 전역 프록시

## 빠른 실행

```bash
docker run --rm \
  --name cloak-scrape-adapter \
  -p 3000:3000 \
  ghcr.io/juilpark/cloak-scrape-adapter:0.1.0
```

첫 브라우저 시작 때 CloakHQ 공식 채널에서 바이너리를 다운로드한다. 최신
빌드 또는 구독 등급에 따라 `CLOAKBROWSER_LICENSE_KEY`가 필요할 수 있다.
키는 이미지 빌드 인자에 넣지 않고 런타임 secret으로만 전달한다.

```bash
docker run --rm \
  -p 3000:3000 \
  -e CLOAKBROWSER_LICENSE_KEY \
  -v cloakbrowser-cache:/home/app/.cloakbrowser \
  ghcr.io/juilpark/cloak-scrape-adapter:0.1.0
```

## API

### `GET /health`

단순 프로세스 생존 여부가 아니라 BrowserContext와 Page 생성 가능 여부를
확인한다.

```bash
curl http://localhost:3000/health
```

```json
{
  "status": "healthy",
  "maxConcurrentPages": 10,
  "activePages": 0
}
```

초기 브라우저 시작, 라이선스 확인 또는 바이너리 다운로드가 실패하면
프로세스 시작 자체가 실패한다. 이미 시작된 프로세스에서 새 Context/Page
생성이 실패하면 `/health`는 `503`과 비밀 값이 없는 오류를 반환한다.

### `POST /scrape`

```bash
curl -X POST http://localhost:3000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "wait_after_load": 0,
    "timeout": 15000,
    "headers": {
      "Accept-Language": "ko-KR"
    },
    "check_selector": "h1",
    "skip_tls_verification": false
  }'
```

```json
{
  "content": "<html>...</html>",
  "pageStatusCode": 200,
  "contentType": "text/html"
}
```

| 필드 | 필수 | 기본값 | 설명 |
|---|---:|---:|---|
| `url` | 예 | 없음 | `http` 또는 `https` URL |
| `wait_after_load` | 아니요 | `0` | load 이후 추가 대기(ms) |
| `timeout` | 아니요 | `15000` | 탐색과 selector 제한 시간(ms) |
| `headers` | 아니요 | 없음 | 페이지 요청 헤더 |
| `check_selector` | 아니요 | 없음 | 나타날 때까지 기다릴 selector |
| `skip_tls_verification` | 아니요 | `false` | TLS 인증서 검증 생략 |

원격 서버의 4xx/5xx는 어댑터 HTTP `200` 본문의 `pageStatusCode`와
`pageError`로 전달한다. 어댑터 자체의 잘못된 요청은 `400`, 내부 실행 오류는
`500`, 차단된 목적지는 HTTP `200` 본문의 `pageStatusCode: 403`으로
표현한다.

`application/json`과 `text/plain` 응답은 HTML로 감싸지 않고 원문 body를
반환한다.

## 설정

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `PORT` | `3000` | HTTP 포트 |
| `MAX_CONCURRENT_PAGES` | `10` | 프로세스당 동시 Page 상한 |
| `BLOCK_MEDIA` | `false` | 이미지·오디오·비디오 요청 차단 |
| `ALLOW_LOCAL_WEBHOOKS` | `false` | 사설/비공개 주소 접근 허용 |
| `HEADLESS` | `true` | headless 모드 |
| `PROXY_SERVER` | 없음 | HTTP/SOCKS 프록시 |
| `PROXY_USERNAME` | 없음 | 프록시 사용자명 |
| `PROXY_PASSWORD` | 없음 | 프록시 비밀번호 |
| `CLOAKBROWSER_LICENSE_KEY` | 없음 | 런타임 라이선스 키 |
| `CLOAKBROWSER_CACHE_DIR` | `/home/app/.cloakbrowser` | 바이너리 cache |
| `CLOAKBROWSER_VERSION` | 없음 | 명시적 바이너리 버전 |
| `CLOAKBROWSER_AUTO_UPDATE` | `false` | 자동 업데이트 |

Uvicorn worker는 반드시 하나로 유지한다. 더 많은 처리량은
`MAX_CONCURRENT_PAGES` 또는 컨테이너 replica 수로 조정한다.
기본 이미지는 headless 실행을 대상으로 한다. `HEADLESS=false`는 Xvfb 또는
외부 display가 준비된 별도 이미지에서만 사용한다.

## 보안 경계

기본 설정은 다음 주소를 차단한다.

- loopback
- private
- link-local
- multicast
- unspecified
- reserved
- IPv4-mapped IPv6의 위 주소

검사는 최초 URL뿐 아니라 Playwright routing을 통과하는 리다이렉트와 모든
서브리소스에 적용된다. DNS 응답 중 하나라도 비공개 주소이면 차단한다.

애플리케이션 DNS 검사와 Chromium의 실제 연결 사이에는 피할 수 없는
DNS-rebinding race가 남는다. 인터넷 사용자가 URL을 제출할 수 있는 배포라면
컨테이너 egress 방화벽 또는 목적지 검증 프록시를 함께 적용한다.

서비스 포트는 기본적으로 Docker 내부 네트워크에만 두고, 외부 공개가 필요하면
인증, 요청 크기 제한, rate limit을 제공하는 별도 프록시를 앞에 둔다.

## 라이선스

이 저장소의 독립 구현 코드는 [MIT License](LICENSE)다. Firecrawl 소스 코드는
포함하거나 번역하지 않았으며 공개된 HTTP 계약만 호환 대상으로 삼는다.

CloakBrowser에는 서로 다른 두 라이선스 경계가 있다.

- Python wrapper: MIT
- CloakBrowser Chromium binary: 별도
  [Binary License](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md)

공개 GHCR 이미지는 MIT wrapper만 포함하고 CloakBrowser Chromium 바이너리는
포함하지 않는다. 최종 운영자가 첫 실행 때 공식 CloakHQ 채널에서 직접
다운로드하고 Binary License에 동의한다.

현재 Binary License는 바이너리 재배포를 금지하고, 외부 고객에게 브라우저
기능을 API 또는 hosted workflow로 제공하는 경우 별도의 OEM/SaaS 라이선스를
요구한다. 이 프로젝트를 내부 scraping에 사용하는 것과 제3자용 서비스를
운영하는 것은 라이선스상 같지 않다. 배포 형태에 맞게 CloakHQ와 별도 조건을
확인한다.

자세한 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고한다.

## 로컬 개발

브라우저가 필요 없는 단위 테스트:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Docker runtime은 `uv.lock`에서 생성한 해시 포함 `requirements.lock`을
사용한다. 의존성을 바꾼 뒤 다음 명령으로 함께 갱신한다.

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt \
  --output-file requirements.lock
```

서비스 실행:

```bash
uv run uvicorn cloak_scrape_adapter.app:app \
  --host 0.0.0.0 \
  --port 3000 \
  --workers 1
```

서비스 시작은 `launch_async()`를 호출하므로 첫 실행 시 바이너리가 내려받아질
수 있다. `.cloakbrowser` cache를 Git에 추가하지 않는다.

## Docker 이미지 검증

```bash
docker build -t cloak-scrape-adapter:test .
docker run --rm --user 0 --entrypoint python \
  -v "$PWD/scripts/assert_binary_free.py:/tmp/assert_binary_free.py:ro" \
  cloak-scrape-adapter:test /tmp/assert_binary_free.py
```

Docker build와 공개 GitHub Actions에서는 CloakBrowser를 시작하지 않는다.
workflow는 단위 테스트 후 binary-free 이미지를 확인하고, `linux/amd64`와
`linux/arm64`를 GHCR에 발행한다. 버전 태그와 commit SHA 태그를 만들며
SBOM과 provenance도 함께 발행한다.

실제 CloakBrowser 통합 테스트는 라이선스와 cache 처리가 명확한 환경에서
별도의 opt-in 작업으로 실행한다.
