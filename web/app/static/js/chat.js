/* 고객 채팅 화면.
   서버(/api/*)와 통신하고, 대화 말풍선과 모달 흐름을 관리한다. 서버 쪽 흐름 설명은 routes/chat.py 참고.

   화면 흐름
     채팅 ─ [상담 종료] ─▶ 확인 ─▶ 만족도(1회) ─┬─ 만족/건너뛰기 ─────────────▶ 마무리
                                                 └─ 불만족 ─▶ "상담사 연결이 필요하신가요?" ─ 아니요 ─▶ 마무리
                                                                                             └ 네 ─▶ 이름 입력 ─▶ 마무리
          └ [상담사 연결] ─▶ 이름 입력 ─▶ 만족도(1회) ─▶ 마무리
     마무리 ─▶ 세션 정리 후 첫 화면(/) 으로 이동 */

const $ = (selector) => document.querySelector(selector);

const els = {
  log: $("#chat-log"),
  form: $("#chat-form"),
  input: $("#chat-input"),
  send: $("#chat-send"),
  endButton: $("#btn-end"),
  handoffButton: $("#btn-handoff"),
  nameForm: $("#name-form"),
  nameInput: $("#field-customer-name"),
};
const modals = {
  end: $("#modal-end"),
  rating: $("#modal-rating"),
  offer: $("#modal-offer"),
  name: $("#modal-name"),
  done: $("#modal-done"),
};

const SUGGESTIONS = [
  "대출 만기 연장하려면 어떻게 해야 하나요?",
  "실손보험 청구에 필요한 서류가 궁금해요",
  "해외주식 거래 수수료가 궁금해요",
  "계좌 해지 방법을 알고 싶어요",
];
const CLOSING = {
  ended: { title: "상담이 종료되었어요", text: "이용해 주셔서 감사합니다. 언제든 다시 찾아주세요." },
  handoffNow: { title: "상담사 연결을 요청했어요", text: "상담사가 곧 내용을 확인할 거예요. 이용해 주셔서 감사합니다." },
  handoffLater: { title: "상담 예약이 접수되었어요", text: "다음 영업일(평일 9~18시)에 상담사가 확인해요. 이용해 주셔서 감사합니다." },
};
const REDIRECT_SECONDS = 8;

const state = {
  busy: false,
  flow: null,                 // "ended"(상담 종료로 시작) | "handoff"(상담사 연결로 시작) | "offer"(불만족 후 연결 선택)
  businessHours: $(".chat").dataset.businessHours === "true",
};

// ---------- 공통 도우미 ----------
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(70000),  // AI 서버 대기(최대 60초)보다 조금 길게
  });
  if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// ---------- 대화 말풍선 ----------
function scrollToBottom() {
  els.log.scrollTop = els.log.scrollHeight;
}

function addRow(className, child) {
  const row = el("div", `bubble-row ${className}`);
  row.append(child);
  els.log.append(row);
  scrollToBottom();
  return row;
}

function addBubble(role, text, extraClass = "") {
  return addRow(`bubble-row--${role}`, el("div", `bubble bubble--${role} ${extraClass}`.trim(), text));
}

function showTyping() {
  const bubble = el("div", "bubble bubble--ai typing");
  bubble.setAttribute("role", "status");
  bubble.append(el("span", "visually-hidden", "답변을 작성하고 있어요"), el("span", "typing__dot"), el("span", "typing__dot"), el("span", "typing__dot"));
  const row = addRow("bubble-row--ai", bubble);
  row.id = "typing";
}

function hideTyping() {
  $("#typing")?.remove();
}

function addActionRow(label, onClick) {
  const button = el("button", "btn btn--secondary btn--sm", label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return addRow("bubble-row--ai", button);
}

function addSuggestions() {
  const chips = el("div", "chips");
  chips.id = "chips";
  for (const text of SUGGESTIONS) {
    const chip = el("button", "chip", text);
    chip.type = "button";
    chip.addEventListener("click", () => sendMessage(text));
    chips.append(chip);
  }
  addRow("bubble-row--ai", chips);
}

// ---------- 입장 인사 ----------
async function showWelcome() {
  showTyping();
  await sleep(450);
  hideTyping();
  addBubble("ai", "안녕하세요! 돈톡 AI 상담이에요. 은행·보험·증권 관련해서 궁금한 점을 편하게 물어보세요.");
  addBubble("ai", "계좌 해지나 이체처럼 실제 처리가 필요한 일은 상담사를 연결해 드려요. 아래 질문으로 바로 시작해도 좋아요.");
  addSuggestions();
}

// ---------- 메시지 보내기 ----------
function setComposerEnabled(enabled) {
  els.input.disabled = !enabled;
  els.send.disabled = !enabled;
}

async function sendMessage(text, { retry = false } = {}) {
  if (state.busy) return;
  state.busy = true;
  setComposerEnabled(false);
  $("#chips")?.parentElement.remove();
  if (!retry) addBubble("me", text);
  showTyping();

  try {
    const data = await api("/api/chat", { message: text });
    hideTyping();
    addBubble("ai", data.answer);
    els.endButton.disabled = false;  // 상담이 생겼으니 종료할 수 있다
    if (data.handoff_needed) addActionRow("상담사 연결하기", openNameModal);
  } catch (error) {
    hideTyping();
    addBubble("ai", "답변을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", "bubble--error");
    addActionRow("다시 시도", () => sendMessage(text, { retry: true }));
  } finally {
    state.busy = false;
    setComposerEnabled(true);
    els.input.focus();
  }
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.input.value.trim();
  if (!text) return;
  els.input.value = "";
  sendMessage(text);
});

// ---------- 상담 종료 / 상담사 연결 ----------
function reportFailure() {
  addBubble("ai", "처리하지 못했어요. 잠시 후 다시 시도해 주세요.", "bubble--error");
}

els.endButton.addEventListener("click", () => modals.end.showModal());
$("#end-cancel").addEventListener("click", () => modals.end.close());
$("#end-confirm").addEventListener("click", async () => {
  modals.end.close();
  try {
    await api("/api/end");
    state.flow = "ended";
    modals.rating.showModal();
  } catch (error) {
    reportFailure();
  }
});

function openNameModal() {
  modals.name.showModal();
  els.nameInput.focus();
}
els.handoffButton.addEventListener("click", openNameModal);

function cancelName() {
  modals.name.close();
  if (state.flow === "offer") {  // 연결 제안을 받고도 취소하면 상담 종료로 마무리
    state.flow = "ended";
    finish();
  }
}
$("#name-cancel").addEventListener("click", cancelName);
modals.name.addEventListener("cancel", (event) => {  // ESC
  event.preventDefault();
  cancelName();
});

els.nameForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = els.nameInput.value.trim();
  if (!name) return;
  try {
    const result = await api("/api/handoff", { name });
    state.businessHours = result.business_hours ?? state.businessHours;
  } catch (error) {
    modals.name.close();
    reportFailure();
    return;
  }
  modals.name.close();
  if (state.flow === "offer") {
    finish();                       // 만족도는 이미 받았다
  } else {
    state.flow = "handoff";
    modals.rating.showModal();      // 상담사 연결로 끝나는 경우의 만족도(1회)
  }
});

// ---------- 만족도 (상담 하나에 한 번) ----------
async function rate(choice) {
  modals.rating.close();
  const satisfied = choice === "skip" ? null : choice === "yes";
  let offerHandoff = false;
  try {
    ({ offer_handoff: offerHandoff } = await api("/api/feedback", { satisfied }));
  } catch (error) {
    // 평가 저장에 실패해도 고객의 마무리를 막지 않는다
  }
  if (offerHandoff) modals.offer.showModal();
  else finish();
}
for (const button of modals.rating.querySelectorAll("[data-rating]")) {
  button.addEventListener("click", () => rate(button.dataset.rating));
}

$("#offer-no").addEventListener("click", () => {
  modals.offer.close();
  finish();
});
$("#offer-yes").addEventListener("click", () => {
  modals.offer.close();
  state.flow = "offer";
  openNameModal();
});

// 흐름 중간에 ESC 로 모달이 닫혀서 길을 잃지 않도록, 이 모달들은 버튼으로만 닫는다
for (const dialog of [modals.rating, modals.offer, modals.done]) {
  dialog.addEventListener("cancel", (event) => event.preventDefault());
}

// ---------- 마무리 → 첫 화면 ----------
async function goHome() {
  try {
    await api("/api/session/close");  // 고객 세션 정리: 다음 방문은 새 상담으로 시작
  } finally {
    location.href = "/";
  }
}

async function finish() {
  const closing = state.flow === "handoff" || state.flow === "offer"
    ? (state.businessHours ? CLOSING.handoffNow : CLOSING.handoffLater)
    : CLOSING.ended;
  $("#modal-done-title").textContent = closing.title;
  $("#modal-done-text").textContent = closing.text;
  modals.done.showModal();

  for (let remaining = REDIRECT_SECONDS; remaining > 0; remaining -= 1) {
    $("#done-hint").textContent = `${remaining}초 뒤에 첫 화면으로 이동해요`;
    await sleep(1000);
  }
  goHome();
}
$("#done-home").addEventListener("click", goHome);

showWelcome();
