# 웹 DB 스키마 (공용 DB의 웹 전용 테이블)

공용 DB(`.env` 의 `DB_*`) 안에 RAG 지식베이스 `financial_consulting_qa` 와 **같이** 있다. 아래 5개가 웹(Flask) 전용 테이블이고,
`web/app/models/` 의 SQLAlchemy 모델과 1:1 이다. 구조를 바꿨다면 `cd web && flask --app app reset-db --yes` 로 웹 테이블만 다시 만든다
(`db.create_all()` 은 이미 있는 테이블의 컬럼 변경을 반영하지 않는다). 지식베이스는 모델에 없어서 건드리지 않는다.

## ERD

```mermaid
erDiagram
    customer  ||--o{ consult : "상담 시작"
    employee  |o--o{ consult : "상담 완료(담당)"
    consult   ||--o{ message : "대화"
    consult   ||--o{ consult_transfer : "분야 재배정 기록"
    employee  ||--o{ consult_transfer : "재배정한 상담사"

    customer {
        int customer_id PK
        string name "이관 시점에 입력(그 전엔 익명)"
        timestamptz created_at
    }
    employee {
        int employee_id PK
        string name
        string email UK
        string password_hash
        enum role "agent | admin"
        string department "은행/보험/증권 (관리자는 NULL)"
        timestamptz created_at
    }
    consult {
        int consult_id PK
        int customer_id FK
        int employee_id FK "상담을 완료한 상담사, AI 단독 종료면 NULL"
        string category "현재 배정 분야 (상담사가 재배정하면 변경)"
        string ai_category "이관 시점 AI 판단 분야 (불변, 오류율 계산용)"
        string topic
        float confidence
        enum status "chatting | ended | waiting_realtime | waiting_next_day | completed"
        enum handoff_reason "customer_request | action_request | no_basis | low_confidence | ai_error | user_dissatisfied"
        text handoff_detail "AI가 알려준 상세 사유"
        enum queue_type "realtime | next_day (이관 시점 영업시간 내/외, 불변)"
        enum satisfaction "satisfied | dissatisfied (상담 1건당 1회)"
        text summary "상담사 상담 메모 (저장하면 상담 종료)"
        timestamptz handoff_at "상담사 연결 접수 시각"
        timestamptz closed_at "고객 종료 또는 상담사 완료 시각"
        timestamptz created_at
        timestamptz updated_at
    }
    message {
        int message_id PK
        int consult_id FK
        enum sender "customer | ai"
        text content
        json sources "AI 답변일 때만: 근거 상담 사례(예상 꼬리질문/답변 포함)"
        timestamptz created_at
    }
    consult_transfer {
        int transfer_id PK
        int consult_id FK
        int employee_id FK "재배정한 상담사"
        string from_category
        string to_category
        text reason
        timestamptz created_at
    }
```

## 상담 상태 흐름

```
chatting(AI 상담 중) ─ 고객이 [상담 종료] ─▶ ended
        │
        └ 고객이 [상담사 연결] + 이름 입력 ─▶ waiting_realtime(영업시간 내) / waiting_next_day(영업시간 외)
                                                  └ 상담사가 상담 메모 저장 ─▶ completed
```

- 상담사는 **자기 `department` 와 같은 `category`** 의 대기 건(+ `category` 가 NULL 인 미분류 건)만 본다.
- 상담사는 고객과 대화하지 않는다. 마지막 단계는 상담 메모(`summary`) 저장이다.
- **AI 단독 해결** = `status = ended` 이고 `satisfaction` 이 불만족이 아닌 건.
- **AI 분류 오류율** = (`consult_transfer` 가 1건 이상인 상담) / (`handoff_at` 이 있는 상담). `ai_category` 별로도 낼 수 있다. *(재배정 기능과 대시보드 표시는 상담사 화면 개선 단계에서 구현)*

## 이전(로컬 개발 단계) 구조에서 바뀐 점

| 테이블 | 변경 |
|---|---|
| `consult` | **추가** `ai_category`, `handoff_detail`, `handoff_at`, `closed_at` · **변경** `status` 값(`ai_resolved`·`in_progress` 제거, `chatting`·`ended` 추가), `handoff_reason` 값(`ai_low_confidence` 제거, 5종 세분화), `summary` 는 상담사 메모로 용도 확정 |
| `message` | **추가** `sources`(JSON) · **변경** `sender` 에서 `agent` 제거 |
| `consult_transfer` | **신규** |
| `customer`, `employee` | 변경 없음 (`employee.department` 는 상담사에게 필수) |
