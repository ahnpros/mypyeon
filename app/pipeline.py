"""핵심 파이프라인 — 내 편 (분쟁 대응 에이전트).

흐름: 상황 서술 → 쟁점 추출(Router) → 쟁점별 근거 조사(Search) →
(a) 기준 확인 / (b) 주장 입증 2단계 분류 → 단계별 대응 문안
생성(Router, 확인된 기준만 인용).

정직성 규칙:
- (a) 기준 확인: Search가 답변과 실제 출처 URL을 함께 돌려줬을 때만
  "기준 확인됨"이다. 실패하면 "기준 확인 안 됨"으로 강제한다.
- (b) 주장 입증: 기준형 주장은 기준이 확인되면 입증으로 본다.
  사실형 주장(책임·피해 사실·금액 적정성)은 사용자가 측정 자료·
  영수증·기록 같은 사실 증거를 제시했을 때만 입증이 되고, 증거가
  없으면 기준이 확인돼도 "주장 입증 안 됨"으로 강제한다. 관련
  기준이 검색됐다는 이유만으로 내 주장이 입증됐다고 표시하지 않는다.
- 문안 생성에는 확인된 기준만 근거로 넘긴다. 입증 안 된 주장은
  단정 금지 목록으로 따로 표시한다.
- Router 호출이 실패하면 폴백(단일 쟁점, 템플릿 문안)으로 흐름을
  유지하되, 엔진 표시에 그대로 드러낸다.
"""
from __future__ import annotations

import json
import re

from . import liner_client as lc
from .models import (
    CLAIM_NOT_PROVEN,
    CLAIM_PROVEN,
    CLAIM_TYPE_FACTUAL,
    CLAIM_TYPE_STANDARD,
    STANDARD_CONFIRMED,
    STANDARD_UNCONFIRMED,
    DisputeReport,
    DisputeRequest,
    Evidence,
    Issue,
    Rebuttal,
    ResponsePlan,
)

MAX_ISSUES = 4
MAX_QUERIES_PER_ISSUE = 2
FINDING_MAX_CHARS = 1200


def _parse_json(text: str | None) -> dict | None:
    """Router 답변에서 JSON 객체를 꺼낸다. 실패하면 None."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 쟁점 추출


def extract_issues(req: DisputeRequest) -> tuple[str, list[Issue], str]:
    """상황 서술에서 요약과 쟁점을 뽑는다. 반환: (요약, 쟁점 목록, 엔진)."""
    prompt = f"""너는 소비자 분쟁 상담의 쟁점 정리 담당이다. 아래 상황을 읽고 JSON만 출력해라. 설명 문장이나 마크다운 코드펜스는 쓰지 마라.

출력 형식:
{{"summary": "상황 요약 2~3문장", "issues": [{{"title": "쟁점 제목", "my_claim": "내 주장 한 문장", "their_claim": "상대 주장 한 문장 (모르면 빈 문자열)", "search_queries": ["쿼리1", "쿼리2"], "claim_type": "기준형 또는 사실형", "evidence_present": true 또는 false, "evidence_note": "제시된 증거 또는 부족한 증거 한 문장"}}]}}

규칙:
- 쟁점은 최대 {MAX_ISSUES}개. 실제로 다투는 지점만 뽑아라.
- search_queries는 관련 법령, 소비자분쟁해결기준, 한국소비자원 분쟁조정 사례를 찾기 위한 검색어다. 쟁점마다 2개씩 만들어라.
- claim_type은 주장을 뒷받침하는 데 무엇이 필요한지로 정해라.
  - "기준형": 기준이 정한 권리·환불 방식·배상 산정 방식에 대한 주장. 예: "중도 해지하면 남은 기간 이용료를 기준에 따라 환불받아야 한다", "배상액은 구입가와 경과 기간을 반영한 기준으로 산정해야 한다". 적용 기준이 확인되면 뒷받침되는 주장이다.
  - "사실형": 상대의 책임 성립, 피해 사실, 인과관계, 특정 금액의 적정성처럼 사실관계 입증이 별도로 필요한 주장. 예: "위층 이웃에게 손해배상 책임이 있다", "손해배상 1천만원이 적정하다", "강사가 바뀐 것은 학원의 귀책사유다".
- evidence_present는 이 쟁점의 주장을 뒷받침할 사실 증거(측정 자료, 녹음, 사진, 영수증, 계약서, 문자 기록, 공식 접수 기록, 진단서 등)를 사용자가 상황이나 첨부 자료에서 실제로 제시했는지다. 감정이나 주장만 있고 증거가 없으면 false다. 영수증·계약서처럼 분쟁 자체의 기본 서류만 있고 다투는 사실(피해 정도, 소음 수치 등)에 대한 증거가 없으면 그 쟁점은 false다.
- evidence_note에는 제시된 증거가 무엇인지, 또는 무엇이 없어서 입증이 부족한지 적어라.
- 없는 사실을 지어내지 마라. 상황에 없는 금액·날짜·약속은 넣지 마라.

상황:
{req.situation}

첨부 자료 (상대의 말, 약관, 영수증, 문자 등):
{req.attachment_text or "(없음)"}"""
    data = _parse_json(lc.chat_with_liner(prompt))
    if data and isinstance(data.get("issues"), list) and data["issues"]:
        issues: list[Issue] = []
        for raw in data["issues"][:MAX_ISSUES]:
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            queries = [
                str(q).strip()
                for q in (raw.get("search_queries") or [])
                if str(q).strip()
            ][:MAX_QUERIES_PER_ISSUE]
            if not queries:
                queries = [f"{raw['title']} 소비자분쟁해결기준"]
            claim_type = str(raw.get("claim_type") or "").strip()
            if claim_type not in (CLAIM_TYPE_STANDARD, CLAIM_TYPE_FACTUAL):
                # 분류가 없거나 이상하면 보수적으로 사실형으로 둔다
                claim_type = CLAIM_TYPE_FACTUAL
            issues.append(
                Issue(
                    title=str(raw["title"]).strip(),
                    my_claim=str(raw.get("my_claim") or "").strip(),
                    their_claim=str(raw.get("their_claim") or "").strip(),
                    search_queries=queries,
                    claim_type=claim_type,
                    evidence_present=bool(raw.get("evidence_present")),
                    evidence_note=str(raw.get("evidence_note") or "").strip(),
                )
            )
        if issues:
            summary = str(data.get("summary") or "").strip() or req.situation[:200]
            return summary, issues, "liner"

    # 폴백: 상황 전체를 쟁점 하나로 본다 (엔진 표시에 그대로 드러난다)
    head = req.situation.strip().replace("\n", " ")
    fallback = Issue(
        title="전체 상황",
        my_claim=head[:200],
        their_claim="",
        search_queries=[
            f"{head[:40]} 소비자분쟁해결기준",
            f"{head[:40]} 한국소비자원 분쟁조정 사례",
        ],
    )
    engine = "liner" if lc.liner_configured() else "mock"
    return head[:200], [fallback], engine


# ---------------------------------------------------------------- 근거 조사


def classify_claim(issue: Issue, standard_confirmed: bool) -> tuple[str, str]:
    """(b) 주장 입증 판정. 반환: (주장 상태, 판정 이유).

    코드로 강제하는 규칙:
    - 기준부터 확인 안 되면 입증도 안 된다.
    - 기준형 주장은 기준이 확인되면 입증으로 본다 (기준 자체가
      권리·산정 방식을 정하므로).
    - 사실형 주장은 사용자가 사실 증거를 제시했을 때만 입증으로
      본다. 관련 기준이 검색됐다는 것만으로는 입증이 되지 않는다.
    """
    if not standard_confirmed:
        return (
            CLAIM_NOT_PROVEN,
            "적용되는 법령·기준부터 확인되지 않아 주장을 뒷받침할 근거가 없습니다.",
        )
    if issue.claim_type == CLAIM_TYPE_STANDARD:
        return (
            CLAIM_PROVEN,
            "확인된 법령·기준이 정한 권리·산정 방식에 대한 주장이라, 기준 확인이 곧 뒷받침이 됩니다.",
        )
    if issue.evidence_present:
        note = issue.evidence_note or "사용자가 제시한 증거"
        return (
            CLAIM_PROVEN,
            f"적용 기준이 확인됐고 {note}가 제시돼 주장을 뒷받침합니다. "
            "다만 증거 자체의 진위까지 검증한 것은 아닙니다.",
        )
    note = issue.evidence_note or "측정 자료·기록 같은 사실 증거가 제시되지 않았습니다"
    return (
        CLAIM_NOT_PROVEN,
        f"적용되는 기준은 확인됐지만, 이 주장은 사실관계 입증이 필요합니다. {note} "
        "기준이 존재한다는 것만으로 내 사건에서 주장이 성립하지는 않습니다.",
    )


def research_issue(issue: Issue) -> Evidence:
    """쟁점 하나를 조사한다. 출처와 함께 답변이 온 쿼리만 기준으로 인정.

    출처는 공식(정부·공공) 출처를 앞에 정렬하고 공식/비공식을 나눠 담는다.
    """
    engine = "liner" if lc.liner_configured() else "mock"
    for query in issue.search_queries[:MAX_QUERIES_PER_ISSUE]:
        result = lc.search_with_liner(query)
        if result is None:
            continue
        answer, sources = result
        finding = lc.clean_text(answer)[:FINDING_MAX_CHARS]
        if finding and sources:
            official, other = lc.split_sources(sources)
            claim_status, claim_basis = classify_claim(issue, True)
            return Evidence(
                issue_title=issue.title,
                status=STANDARD_CONFIRMED,
                claim_status=claim_status,
                claim_basis=claim_basis,
                finding=finding,
                query_used=query,
                sources=official + other,
                official_sources=official,
                other_sources=other,
                engine="liner",
            )
    claim_status, claim_basis = classify_claim(issue, False)
    return Evidence(
        issue_title=issue.title,
        status=STANDARD_UNCONFIRMED,
        claim_status=claim_status,
        claim_basis=claim_basis,
        finding="",
        query_used="",
        sources=[],
        official_sources=[],
        other_sources=[],
        engine=engine,
    )


# ---------------------------------------------------------------- 문안 생성


def _confirmed_block(confirmed: list[Evidence]) -> str:
    lines = []
    for ev in confirmed:
        src = ", ".join(ev.sources[:3])
        lines.append(
            f"- 쟁점: {ev.issue_title}\n  근거 요지: {ev.finding}\n  출처: {src}"
        )
    return "\n".join(lines) if lines else "(확인된 근거 없음)"


def _supported_unsupported(
    issues: list[Issue], evidence: list[Evidence]
) -> tuple[list[str], list[str]]:
    """주장 입증(b단계) 기준으로 내 주장을 입증됨/입증 안 됨으로 나눈다."""
    by_title = {i.title: i for i in issues}
    supported = [
        by_title[e.issue_title].my_claim
        for e in evidence
        if e.claim_status == CLAIM_PROVEN and e.issue_title in by_title
    ]
    unsupported = [
        by_title[e.issue_title].my_claim
        for e in evidence
        if e.claim_status != CLAIM_PROVEN and e.issue_title in by_title
    ]
    return supported, unsupported


def draft_plan(
    summary: str,
    issues: list[Issue],
    evidence: list[Evidence],
) -> tuple[ResponsePlan, str]:
    """기준이 확인된 근거만 인용해 단계별 문안과 예상 반박을 만든다."""
    confirmed = [e for e in evidence if e.status == STANDARD_CONFIRMED]
    supported, unsupported = _supported_unsupported(issues, evidence)
    their = [i.their_claim for i in issues if i.their_claim]

    prompt = f"""너는 분쟁 대응 문안 작성 담당이다. 아래 "기준이 확인된 근거"만 인용해서 단계별 대응 문안을 JSON으로만 출력해라. 설명 문장이나 코드펜스는 쓰지 마라.

출력 형식:
{{"stage1_script": "1단계 말 스크립트", "stage2_message": "2단계 문자·메일 문안", "stage3_certified": "3단계 내용증명 문안", "rebuttals": [{{"expected": "상대의 예상 반박", "counter": "재대응 문장"}}]}}

규칙:
- 인용할 수 있는 근거는 아래 기준이 확인된 근거뿐이다. 기준이 확인됐다는 것은 적용 법령·기준이 존재한다는 뜻이지, 입증 안 된 내 주장이 사실이라는 뜻이 아니다. 입증되지 않은 주장은 문안에서 사실로 단정하지 말고, 기준상 가능한 절차와 증거 확보 방법 안내로 다뤄라. 확인된 근거가 없으면 문안은 증거 확보와 공식 분쟁조정 절차 안내 중심으로 써라.
- stage1_script: 직접 만나거나 전화로 말할 때 그대로 읽을 수 있는 문장. 차분하고 단호하게, 근거를 짧게 언급한다. 5~8문장.
- stage2_message: 문자나 메일로 보낼 문안. 사실관계, 근거, 요청 사항, 답변 기한(예: 7일 이내)을 포함한다.
- stage3_certified: 내용증명 문안. 발신인·수신인 이름과 주소는 [발신인 이름] 같은 자리표시자로 쓰고, 사실관계, 근거, 요구 사항, 기한 내 이행이 없을 경우 한국소비자원 분쟁조정 신청 등 다음 조치를 명시한다.
- rebuttals: 상대가 할 반박 2~3개와 각각에 대한 재대응 문장. 재대응도 확인된 근거 안에서만 써라.
- 금액·날짜는 상황에서 주어진 것만 써라. 없으면 자리표시자로 둬라.
- 없는 법령명·기준명을 만들지 마라.

상황 요약: {summary}
내 주장 중 입증된 것: {supported or "(없음)"}
내 주장 중 입증되지 않은 것 (단정 금지): {unsupported or "(없음)"}
상대의 알려진 입장: {their or "(알려지지 않음)"}
기준이 확인된 근거:
{_confirmed_block(confirmed)}"""
    data = _parse_json(lc.chat_with_liner(prompt, timeout=lc.CHAT_LONG_TIMEOUT))
    if data and (data.get("stage1_script") or data.get("stage2_message")):
        rebuttals = []
        for raw in data.get("rebuttals") or []:
            if isinstance(raw, dict) and raw.get("expected"):
                rebuttals.append(
                    Rebuttal(
                        expected=str(raw["expected"]).strip(),
                        counter=str(raw.get("counter") or "").strip(),
                    )
                )
        plan = ResponsePlan(
            stage1_script=str(data.get("stage1_script") or "").strip(),
            stage2_message=str(data.get("stage2_message") or "").strip(),
            stage3_certified=str(data.get("stage3_certified") or "").strip(),
            rebuttals=rebuttals[:3],
        )
        return plan, "liner"

    return _template_plan(summary, confirmed), (
        "liner" if lc.liner_configured() else "mock"
    )


def _template_plan(summary: str, confirmed: list[Evidence]) -> ResponsePlan:
    """Router 문안 생성이 실패했을 때의 폴백 템플릿 (확인된 근거만 조립)."""
    if confirmed:
        basis = " / ".join(
            f"{ev.issue_title}: {ev.finding[:120]}" for ev in confirmed
        )
        stage1 = (
            f"이 건에 대해 말씀드리겠습니다. {summary} "
            f"조사해 보니 {basis} 라는 근거가 확인됩니다. "
            "이 기준에 따라 처리해 주시기 바랍니다."
        )
        stage2 = (
            f"안녕하세요. 아래 건에 대해 서면으로 요청드립니다.\n\n"
            f"사실관계: {summary}\n근거: {basis}\n"
            "위 근거에 따른 처리를 요청드리며, 7일 이내에 답변 부탁드립니다."
        )
        stage3 = (
            "내용증명\n수신인: [수신인 이름]\n발신인: [발신인 이름]\n\n"
            f"1. 사실관계\n{summary}\n\n2. 근거\n{basis}\n\n"
            "3. 요구 사항\n위 근거에 따른 조치를 본 서면 도달 후 14일 이내에 "
            "이행해 주시기 바랍니다. 이행되지 않을 경우 한국소비자원 분쟁조정 "
            "신청 등 후속 절차를 진행하겠습니다."
        )
    else:
        stage1 = (
            f"이 건에 대해 말씀드리겠습니다. {summary} "
            "관련 기준을 확인 중이니, 사실관계를 함께 확인하고 처리 방향을 "
            "논의하고 싶습니다."
        )
        stage2 = (
            "안녕하세요. 아래 건에 대해 사실관계 확인을 요청드립니다.\n\n"
            f"사실관계: {summary}\n"
            "관련 자료를 확인한 뒤 다시 연락드리겠습니다."
        )
        stage3 = (
            "내용증명\n수신인: [수신인 이름]\n발신인: [발신인 이름]\n\n"
            f"1. 사실관계\n{summary}\n\n"
            "2. 요청 사항\n사실관계에 대한 귀측의 입장을 서면으로 회신해 "
            "주시기 바랍니다."
        )
    return ResponsePlan(
        stage1_script=stage1,
        stage2_message=stage2,
        stage3_certified=stage3,
        rebuttals=[],
    )


# ---------------------------------------------------------------- 전체 실행


def build_dispute_response(req: DisputeRequest) -> DisputeReport:
    summary, issues, extract_engine = extract_issues(req)
    evidence = [research_issue(issue) for issue in issues]

    supported, unsupported = _supported_unsupported(issues, evidence)

    plan, draft_engine = draft_plan(summary, issues, evidence)

    engines = {extract_engine, draft_engine} | {e.engine for e in evidence}
    overall = engines.pop() if len(engines) == 1 else "mixed"

    report = DisputeReport(
        title=req.title,
        summary=summary,
        issues=issues,
        evidence=evidence,
        supported_points=supported,
        unsupported_points=unsupported,
        plan=plan,
        engine=overall,
    )
    from .report import render_markdown

    report.report_markdown = render_markdown(report)
    return report
