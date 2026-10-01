"""공개 화면(랜딩/로그인)과 공통 컴포넌트 테스트. 항상 임시 sqlite DB 를 쓴다."""
import pytest

def test_landing_splits_customer_and_staff(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/chat"' in html and "AI 상담 시작하기" in html    # 고객: 상담 시작
    assert 'href="/login"' in html and "상담사·관리자 로그인" in html  # 직원: 로그인


def test_chat_page_opens_without_intro(client):
    response = client.get("/chat")
    assert response.status_code == 200 and "screen-intro" not in response.get_data(as_text=True)


def test_login_page_has_form_and_back_link(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'id="field-email"' in html and 'id="field-password"' in html and 'href="/"' in html


def test_login_failure_keeps_email_and_shows_alert(client):
    response = client.post("/login", data={"email": "bank@test.com", "password": "wrong"})
    html = response.get_data(as_text=True)
    assert response.status_code == 401
    assert 'role="alert"' in html and 'value="bank@test.com"' in html


def test_login_success_goes_to_agent_queue(client):
    response = client.post("/login", data={"email": "bank@test.com", "password": "test-pass"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/agent/")


def render(app, template: str) -> str:
    with app.test_request_context():
        return app.jinja_env.from_string(template).render()


def test_button_macro_renders_link_or_button(app):
    link = render(app, '{% from "components/button.html" import button %}{{ button("홈", href="/a", variant="ghost", size="sm", **{"data-id": "1"}) }}')
    assert '<a class="btn btn--ghost btn--sm" href="/a"' in link and 'data-id="1"' in link
    submit = render(app, '{% from "components/button.html" import button %}{{ button("저장", type="submit", block=True) }}')
    assert '<button class="btn btn--primary btn--block" type="submit"' in submit and "btn--md" not in submit


def test_field_macro_links_label_and_input(app):
    html = render(app, '{% from "components/field.html" import field %}{{ field("email", "이메일", required=True, hint="안내") }}')
    assert 'for="field-email"' in html and 'id="field-email"' in html and "required" in html and 'aria-describedby="field-email-hint"' in html


def test_alert_macro_uses_role_by_tone(app):
    assert 'role="alert"' in render(app, '{% from "components/alert.html" import alert %}{{ alert("오류") }}')
    assert 'role="status"' in render(app, '{% from "components/alert.html" import alert %}{{ alert("안내", tone="info") }}')


def test_card_and_badge_macros(app):
    html = render(app, '{% from "components/card.html" import card %}{% from "components/badge.html" import badge %}{% call card(title="제목") %}내용{% endcall %}{{ badge("대기", tone="warning") }}')
    assert '<h3 class="card__title">제목</h3>' in html and "내용" in html and 'badge badge--warning' in html
