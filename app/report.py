"""리포트 렌더링 — 내 편 결과를 마크다운 한 장으로.

근거는 (a) 기준 확인과 (b) 주장 입증을 나눠 표시한다. 출처는
공식(정부·공공) 출처를 먼저, 비공식 출처를 따로 적는다.
"""
from __future__ import annotations

from .models import CLAIM_PROVEN, STANDARD_CONFIRMED, DisputeReport


def render_markdown(report: DisputeReport) -> str:
    lines: list[str] = []
    lines.append(f"# 내 편 — {report.title}")
    lines.append("")
    lines.append(f"> {report.notice}")
    lines.append("")
    lines.append("## 상황 요약")
    lines.append(report.summary)
    lines.append("")
    lines.append("## 쟁점과 근거")
    ev_by_title = {e.issue_title: e for e in report.evidence}
    for issue in report.issues:
        ev = ev_by_title.get(issue.title)
        lines.append(f"### {issue.title}")
        lines.append(f"- 내 주장: {issue.my_claim} ({issue.claim_type})")
        if issue.their_claim:
            lines.append(f"- 상대 주장: {issue.their_claim}")
        if ev is None:
            lines.append("- 기준: 조사 결과 없음")
            lines.append("- 주장: 입증 안 됨")
        else:
            if ev.status == STANDARD_CONFIRMED:
                lines.append("- 기준: 확인됨 (적용되는 법령·기준·사례가 출처로 확인됨)")
                lines.append(f"- 근거 요지: {ev.finding}")
            else:
                lines.append("- 기준: 확인 안 됨")
            if ev.claim_status == CLAIM_PROVEN:
                lines.append("- 주장: 입증됨")
            else:
                lines.append("- 주장: 입증 안 됨")
            if ev.claim_basis:
                lines.append(f"- 입증 판정 이유: {ev.claim_basis}")
            for src in ev.official_sources:
                lines.append(f"  - 공식 출처: {src}")
            for src in ev.other_sources:
                lines.append(f"  - 기타 출처: {src}")
        lines.append("")
    lines.append("## 입증된 내 주장")
    if report.supported_points:
        for p in report.supported_points:
            lines.append(f"- {p}")
    else:
        lines.append("- (없음)")
    lines.append("")
    lines.append("## 입증되지 않은 내 주장")
    if report.unsupported_points:
        for p in report.unsupported_points:
            lines.append(f"- {p}")
    else:
        lines.append("- (없음)")
    lines.append("")
    lines.append("## 단계별 대응")
    lines.append("### 1단계 — 말로 하기")
    lines.append(report.plan.stage1_script or "(생성되지 않음)")
    lines.append("")
    lines.append("### 2단계 — 문자·메일로 보내기")
    lines.append(report.plan.stage2_message or "(생성되지 않음)")
    lines.append("")
    lines.append("### 3단계 — 내용증명")
    lines.append(report.plan.stage3_certified or "(생성되지 않음)")
    lines.append("")
    if report.plan.rebuttals:
        lines.append("## 상대의 예상 반박과 재대응")
        for r in report.plan.rebuttals:
            lines.append(f"- 예상 반박: {r.expected}")
            lines.append(f"  - 재대응: {r.counter}")
        lines.append("")
    lines.append(f"(엔진: {report.engine})")
    return "\n".join(lines)
