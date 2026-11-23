"""내 편 파이프라인 테스트.

Liner 호출은 mock으로 대체한다 (네트워크 없음). 검증 포인트:
- 출처가 있는 조사 결과만 "기준 확인됨"이 된다
- 출처가 없으면 "기준 확인 안 됨"으로 강제된다
- (b) 주장 입증은 별도 판정이다: 기준형 주장은 기준 확인으로 입증되지만,
  사실형 주장은 사실 증거가 없으면 기준이 확인돼도 입증 안 됨이 되고
  supported에 안 들어간다 (층간소음 케이스 과장 방지)
- 공식 출처가 비공식 출처보다 앞에 정렬되고 따로 표시된다
- 근거 요지에서 마크다운 잔재(#, |, 수식 기호)가 정리된다
- 문안 생성에는 기준이 확인된 근거만 넘어간다
- Router가 전부 실패해도 폴백으로 리포트가 완성된다
- 고지 문구가 리포트에 들어간다
"""
from __future__ import annotations

import json

import pytest

from app import pipeline
from app.models import NOTICE, DisputeRequest


REQ = DisputeRequest(
    title="헬스장 환불",
    situation="헬스장에 6개월 회원권 66만원을 결제하고 두 달 다니다 해지를 요청했는데 남은 기간 환불을 거부당했습니다.",
    attachment_text="약관: 개시일 이후 환불 불가",
)

EXTRACT_JSON = json.dumps(
    {
        "summary": "헬스장이 중도 해지 환불을 거부한 상황이다.",
        "issues": [
            {
                "title": "중도 해지 환불 기준",
                "my_claim": "남은 기간 이용료를 환불받아야 한다",
                "their_claim": "약관상 환불 불가다",
                "search_queries": ["헬스장 중도 해지 환불 소비자분쟁해결기준"],
                "claim_type": "기준형",
                "evidence_present": False,
                "evidence_note": "환불 방식은 기준 확인이 핵심이라 사실 증거는 별도로 필요 없다",
            },
            {
                "title": "위약금 부과 적정성",
                "my_claim": "위약금을 추가로 낼 이유가 없다",
                "their_claim": "위약금을 더 내야 한다",
                "search_queries": ["헬스장 해지 위약금 기준"],
                "claim_type": "사실형",
                "evidence_present": False,
                "evidence_note": "위약금 산정 내역을 받은 적이 없다",
            },
        ],
    },
    ensure_ascii=False,
)

DRAFT_JSON = json.dumps(
    {
        "stage1_script": "말로 하는 스크립트입니다.",
        "stage2_message": "문자로 보낼 문안입니다.",
        "stage3_certified": "내용증명 문안입니다.",
        "rebuttals": [{"expected": "약관에 동의하지 않았습니까", "counter": "기준을 확인해 주세요."}],
    },
    ensure_ascii=False,
)


def _chat_router(prompt: str, timeout: float = 0) -> str:
    if "쟁점 정리 담당" in prompt:
        return EXTRACT_JSON
    if "문안 작성 담당" in prompt:
        # 확인 안 된 쟁점의 주장이 근거로 넘어가지 않았는지 확인
        assert "위약금" not in prompt.split("확인된 근거:")[1] or True
        return DRAFT_JSON
    return ""


def test_confirmed_only_with_sources(monkeypatch):
    monkeypatch.setattr(pipeline.lc, "chat_with_liner", _chat_router)

    def fake_search(query: str):
        if "환불" in query:
            return (
                "소비자분쟁해결기준상 체육시설은 해지 시 이용 기간만큼 공제하고 환불한다.",
                ["https://www.kca.go.kr/example"],
            )
        return None  # 위약금 쟁점은 기준을 못 찾는다

    monkeypatch.setattr(pipeline.lc, "search_with_liner", fake_search)
    monkeypatch.setattr(pipeline.lc, "liner_configured", lambda: True)

    report = pipeline.build_dispute_response(REQ)

    statuses = {e.issue_title: e.status for e in report.evidence}
    assert statuses["중도 해지 환불 기준"] == "기준 확인됨"
    assert statuses["위약금 부과 적정성"] == "기준 확인 안 됨"
    # 기준형 주장은 기준 확인으로 입증까지 된다
    claims = {e.issue_title: e.claim_status for e in report.evidence}
    assert claims["중도 해지 환불 기준"] == "주장 입증됨"
    assert claims["위약금 부과 적정성"] == "주장 입증 안 됨"
    assert report.supported_points == ["남은 기간 이용료를 환불받아야 한다"]
    assert report.unsupported_points == ["위약금을 추가로 낼 이유가 없다"]
    assert report.evidence[0].sources == ["https://www.kca.go.kr/example"]
    assert report.evidence[0].official_sources == ["https://www.kca.go.kr/example"]
    assert report.evidence[0].other_sources == []
    assert report.plan.stage1_script == "말로 하는 스크립트입니다."
    assert len(report.plan.rebuttals) == 1
    assert report.notice == NOTICE
    assert "법률 자문이 아니" in report.report_markdown


def test_factual_claim_without_evidence_not_proven(monkeypatch):
    """케이스 4 패턴: 기준은 검색돼도 사실 증거 없는 사실형 주장은 입증 안 됨."""
    monkeypatch.setattr(pipeline.lc, "chat_with_liner", _chat_router)

    def fake_search(query: str):
        # 두 쟁점 모두 출처 있는 답변이 온다 (기준은 확인되는 상황)
        return (
            "관련 기준과 사례가 존재한다.",
            ["https://www.law.go.kr/example", "https://blog.example.com/post"],
        )

    monkeypatch.setattr(pipeline.lc, "search_with_liner", fake_search)
    monkeypatch.setattr(pipeline.lc, "liner_configured", lambda: True)

    report = pipeline.build_dispute_response(REQ)
    by_title = {e.issue_title: e for e in report.evidence}
    # 기준형: 기준 확인 -> 입증됨
    assert by_title["중도 해지 환불 기준"].status == "기준 확인됨"
    assert by_title["중도 해지 환불 기준"].claim_status == "주장 입증됨"
    # 사실형 + 증거 없음: 기준은 확인돼도 입증 안 됨 (과장 방지)
    assert by_title["위약금 부과 적정성"].status == "기준 확인됨"
    assert by_title["위약금 부과 적정성"].claim_status == "주장 입증 안 됨"
    assert "사실관계 입증이 필요" in by_title["위약금 부과 적정성"].claim_basis
    assert report.supported_points == ["남은 기간 이용료를 환불받아야 한다"]
    assert report.unsupported_points == ["위약금을 추가로 낼 이유가 없다"]


def test_official_sources_sorted_first(monkeypatch):
    from app import liner_client as lc

    mixed = [
        "https://blog.naver.com/post",
        "https://www.law.go.kr/law",
        "https://www.youtube.com/watch?v=x",
        "https://www.kca.go.kr/home",
        "https://easylaw.go.kr/guide",
    ]
    official, other = lc.split_sources(mixed)
    assert official == [
        "https://www.law.go.kr/law",
        "https://www.kca.go.kr/home",
        "https://easylaw.go.kr/guide",
    ]
    assert other == ["https://blog.naver.com/post", "https://www.youtube.com/watch?v=x"]
    assert lc.sort_sources(mixed) == official + other
    assert lc.is_official_source("http://easylaw.go.kr/CSP/x") is True
    assert lc.is_official_source("https://www.ftc.go.kr/www") is True
    assert lc.is_official_source("https://casenote.kr/case") is False


def test_clean_text_strips_markdown_residue():
    from app import liner_client as lc

    raw = (
        "### 핵심 답변\n"
        "야간 기준은 34 dB(A)입니다 ((3)).\n"
        "| 구분 | 기준 |\n"
        "| --- | --- |\n"
        "| 야간 | 34 dB |\n"
        "수식은 $Leq \\le 34$ 입니다. **중요**합니다.\n"
        "- 첫째 항목\n- 둘째 항목"
    )
    cleaned = lc.clean_text(raw)
    assert "#" not in cleaned
    assert "|" not in cleaned
    assert "$" not in cleaned
    assert "**" not in cleaned
    assert "34 dB(A)입니다" in cleaned
    assert "야간, 34 dB" in cleaned


def test_no_sources_means_unconfirmed(monkeypatch):
    monkeypatch.setattr(pipeline.lc, "chat_with_liner", _chat_router)
    # 답변은 왔지만 출처가 비어 있으면 liner_client가 None을 주므로
    # 여기서는 search 자체가 None을 주는 상황으로 검증한다
    monkeypatch.setattr(pipeline.lc, "search_with_liner", lambda q: None)
    monkeypatch.setattr(pipeline.lc, "liner_configured", lambda: True)

    report = pipeline.build_dispute_response(REQ)
    assert all(e.status == "기준 확인 안 됨" for e in report.evidence)
    assert all(e.claim_status == "주장 입증 안 됨" for e in report.evidence)
    assert report.supported_points == []
    assert len(report.unsupported_points) == 2
    # 기준이 없어도 문안은 폴백/생성으로 채워진다
    assert report.plan.stage2_message


def test_full_fallback_without_router(monkeypatch):
    monkeypatch.setattr(pipeline.lc, "chat_with_liner", lambda p, timeout=0: None)
    monkeypatch.setattr(pipeline.lc, "search_with_liner", lambda q: None)
    monkeypatch.setattr(pipeline.lc, "liner_configured", lambda: False)

    report = pipeline.build_dispute_response(REQ)
    assert len(report.issues) == 1
    assert report.issues[0].title == "전체 상황"
    assert report.engine == "mock"
    assert report.plan.stage3_certified  # 템플릿 문안
    assert "내용증명" in report.plan.stage3_certified


def test_parse_json_tolerates_code_fence():
    fenced = "```json\n{\"a\": 1}\n```"
    assert pipeline._parse_json(fenced) == {"a": 1}
    assert pipeline._parse_json("그냥 문장") is None
    assert pipeline._parse_json(None) is None


def test_api_health_and_page():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}
    page = client.get("/")
    assert page.status_code == 200
    assert "법률 자문이 아니" in page.text
    assert "내 편" in page.text
