/* 상담사 화면: 대기 큐를 주기적으로 다시 불러와 새 상담을 반영한다.
   서버(/agent/queue/items)가 목록 HTML 조각과 건수를 돌려주면, 목록과 "대기 N건" 탭만 바꾼다.
   상담 메모를 쓰는 중에 화면이 통째로 새로고침되지 않도록 상세 영역은 건드리지 않는다. */

const POLL_MS = 15000;
const list = document.querySelector("#queue-items");
const waitingTab = document.querySelector('[data-tab="waiting"]');

async function refreshQueue() {
  if (document.hidden) return;  // 다른 탭을 보고 있을 땐 요청하지 않는다
  const url = new URL(list.dataset.pollUrl, location.origin);
  if (list.dataset.selected) url.searchParams.set("consult_id", list.dataset.selected);
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const { count, html } = await response.json();
    list.innerHTML = html;
    waitingTab.textContent = `대기 ${count}건`;
  } catch (error) {
    // 일시적인 네트워크 오류는 무시하고 다음 주기에 다시 시도한다
  }
}

if (list?.dataset.pollUrl) setInterval(refreshQueue, POLL_MS);
