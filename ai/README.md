# AI Server

현재 FastAPI 기반 AI 서버를 구축 중입니다.

## 실행 확인

서버가 실행된 상태에서 아래 주소로 접속할 수 있습니다.

### Health Check(구축중 --아직 쓰지마세요!)

```text
http://localhost:8000/health
```

### Swagger UI (구축중-- > 아직 쓰지마세요! 곧 추가예정)

```text
http://localhost:8000/docs
```

Swagger UI에서 현재 구현된 API 목록과 Request / Response 형식을 확인하고 직접 요청을 테스트할 수 있습니다.

### OpenAPI Schema

```text
http://localhost:8000/openapi.json
```

외부 서버 또는 다른 서비스에서 연동할 경우 FastAPI 서버 주소와 포트를 기준으로 API를 호출합니다.

예:

```text
http://<AI_SERVER_HOST>:8000
```

현재 API 및 AI 파이프라인은 계속 구현 중이며, 엔드포인트와 응답 형식은 변경될 수 있습니다.