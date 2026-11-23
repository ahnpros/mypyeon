"""내 편 — 분쟁 대응 에이전트 API + 단일 웹 화면."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .models import DisputeReport, DisputeRequest
from .pipeline import build_dispute_response

app = FastAPI(title="내 편", version="1.0.0")

PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>내 편 — 분쟁 대응 에이전트</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #f6f6f4; color: #161616; }
  main { max-width: 820px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 28px; margin: 8px 0 4px; }
  .notice { background: #fff3cd; border: 1px solid #e0c96a; border-radius: 8px; padding: 10px 12px; font-size: 13px; }
  label { display: block; font-weight: 700; margin: 18px 0 6px; }
  input[type=text], textarea { width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #bbb; border-radius: 8px; font-size: 15px; }
  textarea { min-height: 130px; }
  button { margin-top: 18px; padding: 12px 22px; font-size: 16px; font-weight: 700; background: #78be20; color: #fff; border: 0; border-radius: 8px; cursor: pointer; }
  button:disabled { opacity: .5; }
  section { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin-top: 18px; }
  section h2 { margin: 0 0 10px; font-size: 19px; }
  .badge-ok { color: #2e7d32; font-weight: 700; }
  .badge-no { color: #b3261e; font-weight: 700; }
  .src { font-size: 13px; word-break: break-all; }
  pre { white-space: pre-wrap; font-family: inherit; font-size: 15px; line-height: 1.55; }
  .finding { font-size: 14px; line-height: 1.6; color: #333; }
</style>
</head>
<body>
<main>
  <h1>내 편</h1>
  <p>억울한 분쟁, 혼자 끙끙대지 마세요. 상황을 적으면 관련 법령과 소비자분쟁해결기준, 분쟁조정 사례를 찾아 근거를 정리하고, 단계별 대응 문안까지 만들어 드립니다.</p>
  <p class="notice">이 서비스는 정보 제공과 문안 작성 보조 도구입니다. 법률 자문이 아니며, 구체적인 판단은 전문가 상담이 필요합니다. 결과에서는 적용 기준이 확인됐는지와 내 주장이 입증됐는지를 나눠 표시합니다. 기준이 있다는 것과 내 주장이 성립한다는 것은 다릅니다.</p>

  <label for="title">분쟁 이름</label>
  <input type="text" id="title" placeholder="예: 헬스장 환불 거부">
  <label for="situation">무슨 일이 있었나요</label>
  <textarea id="situation" placeholder="날짜, 금액, 상대가 한 말을 포함해 자유롭게 적어 주세요."></textarea>
  <label for="attachment">관련 자료 (선택)</label>
  <textarea id="attachment" placeholder="약관, 영수증, 문자 내용을 붙여 넣어 주세요." style="min-height:80px"></textarea>
  <button id="go">근거 찾고 대응 문안 만들기</button>
  <p id="status"></p>
  <div id="result"></div>
</main>
<script>
const $ = id => document.getElementById(id);
function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
$('go').onclick = async () => {
  const btn = $('go'); btn.disabled = true;
  $('status').textContent = '쟁점을 뽑고 근거를 조사하고 있습니다. 1~3분 걸릴 수 있습니다.';
  $('result').innerHTML = '';
  try {
    const res = await fetch('/analyze', { method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title: $('title').value || '분쟁 상담', situation: $('situation').value, attachment_text: $('attachment').value }) });
    if (!res.ok) throw new Error('요청 실패 ' + res.status);
    const r = await res.json();
    render(r);
    $('status').textContent = '';
  } catch (e) { $('status').textContent = '오류가 발생했습니다: ' + e.message; }
  btn.disabled = false;
};
function render(r) {
  let h = '';
  h += '<section><h2>상황 요약</h2><p>' + esc(r.summary) + '</p></section>';
  h += '<section><h2>쟁점과 근거</h2>';
  const evBy = {}; (r.evidence||[]).forEach(e => evBy[e.issue_title] = e);
  (r.issues||[]).forEach(i => {
    const ev = evBy[i.title];
    h += '<h3>' + esc(i.title) + '</h3><p>내 주장: ' + esc(i.my_claim) + '</p>';
    if (i.their_claim) h += '<p>상대 주장: ' + esc(i.their_claim) + '</p>';
    if (ev && ev.status === '기준 확인됨') {
      h += '<p class="badge-ok">기준 확인됨 — 적용되는 법령·기준이 있습니다</p><p class="finding">' + esc(ev.finding) + '</p>';
      (ev.official_sources||[]).forEach(s => h += '<p class="src">공식 출처: <a href="' + esc(s) + '" target="_blank" rel="noopener">' + esc(s) + '</a></p>');
      (ev.other_sources||[]).forEach(s => h += '<p class="src">기타 출처: <a href="' + esc(s) + '" target="_blank" rel="noopener">' + esc(s) + '</a></p>');
    } else {
      h += '<p class="badge-no">기준 확인 안 됨 — 적용 기준을 찾지 못했습니다</p>';
    }
    if (ev) {
      if (ev.claim_status === '주장 입증됨') {
        h += '<p class="badge-ok">주장 입증됨</p>';
      } else {
        h += '<p class="badge-no">주장 입증 안 됨 — 사실 증거가 더 필요합니다</p>';
      }
      if (ev.claim_basis) h += '<p class="finding">' + esc(ev.claim_basis) + '</p>';
    }
  });
  h += '</section>';
  h += '<section><h2>1단계 — 말로 하기</h2><pre>' + esc(r.plan.stage1_script) + '</pre></section>';
  h += '<section><h2>2단계 — 문자·메일로 보내기</h2><pre>' + esc(r.plan.stage2_message) + '</pre></section>';
  h += '<section><h2>3단계 — 내용증명</h2><pre>' + esc(r.plan.stage3_certified) + '</pre></section>';
  if ((r.plan.rebuttals||[]).length) {
    h += '<section><h2>상대의 예상 반박과 재대응</h2>';
    r.plan.rebuttals.forEach(b => { h += '<p><b>예상 반박:</b> ' + esc(b.expected) + '</p><p><b>재대응:</b> ' + esc(b.counter) + '</p>'; });
    h += '</section>';
  }
  h += '<section><h2>꼭 확인하세요</h2><p>' + esc(r.notice) + '</p></section>';
  $('result').innerHTML = h;
}
</script>
</body>
</html>"""


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.post("/analyze", response_model=DisputeReport)
def analyze(req: DisputeRequest) -> DisputeReport:
    """상황 서술 -> 쟁점 추출 -> 근거 조사 -> 단계별 대응 문안.

    기준 확인(적용 법령·기준의 존재)과 주장 입증(내 주장이 사실
    증거로 뒷받침되는지)을 나눠 표시하고, 입증 안 된 주장은
    문안에서 단정하지 않는다.
    """
    return build_dispute_response(req)
