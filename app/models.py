"""입출력 스키마 — 내 편 (분쟁 대응 에이전트).

억울한 분쟁 상황을 자유 서술로 받으면 쟁점을 추출하고, 쟁점마다
관련 법령·소비자분쟁해결기준·소비자원 분쟁조정 사례를 실시간으로
조사해, 내 주장의 근거가 확인되는 부분과 확인이 안 되는 부분을
나눈 뒤 단계별 대응 문안(말 → 문자/메일 → 내용증명)과 상대의
예상 반박·재대응까지 만든다.

근거 분류는 두 단계로 나눈다 (과장 방지):
- (a) 기준 확인: 이 쟁점에 적용되는 법령·기준·사례가 존재한다는 것이
  출처와 함께 확인됐는가. Search가 실제 출처 URL을 돌려줬을 때만
  "기준 확인됨"이 된다.
- (b) 주장 입증: 내 구체적 주장이 뒷받침되는가. 기준형 주장(기준이
  정한 권리·환불·배상 방식)은 기준이 확인되면 입증으로 보지만,
  사실형 주장(상대의 책임, 피해 사실, 금액의 적정성 등)은 측정 자료·
  영수증·기록 같은 사실 증거가 제시되지 않으면 기준이 확인돼도
  "주장 입증 안 됨"으로 강제한다. 기준이 있다는 것과 내 사건에서
  그 주장이 성립한다는 것은 다른 문제이기 때문이다.

정직성 규칙 (코드로 강제한다):
- 문안은 확인된 기준만 인용한다. 입증 안 된 주장은 문안에서 사실로
  단정하지 않고, 결과 화면에 따로 표시해 사용자가 알 수 있게 한다.
- 법령명·기준명은 조사 답변에 실제로 나온 것만 쓴다. 조사 결과에
  없는 근거는 만들지 않는다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# (a) 기준 확인 — 적용되는 법령·기준·사례의 존재가 출처로 확인됐는가
STANDARD_CONFIRMED = "기준 확인됨"
STANDARD_UNCONFIRMED = "기준 확인 안 됨"
STANDARD_STATUSES = [STANDARD_CONFIRMED, STANDARD_UNCONFIRMED]

# (b) 주장 입증 — 내 구체적 주장이 뒷받침되는가
CLAIM_PROVEN = "주장 입증됨"
CLAIM_NOT_PROVEN = "주장 입증 안 됨"
CLAIM_STATUSES = [CLAIM_PROVEN, CLAIM_NOT_PROVEN]

# 주장 유형 — 기준형은 기준 확인만으로 입증 가능, 사실형은 사실 증거 필요
CLAIM_TYPE_STANDARD = "기준형"
CLAIM_TYPE_FACTUAL = "사실형"
CLAIM_TYPES = [CLAIM_TYPE_STANDARD, CLAIM_TYPE_FACTUAL]

NOTICE = (
    "이 결과는 공개된 법령·소비자분쟁해결기준·분쟁조정 사례를 조사한 "
    "정보 제공과 문안 작성 보조입니다. 법률 자문이 아니며, 구체적인 "
    "사안의 판단은 변호사 등 전문가 상담이 필요합니다. '기준 확인됨'은 "
    "적용되는 법령·기준이 있다는 뜻일 뿐 내 주장이 입증됐다는 뜻이 "
    "아닙니다. '주장 입증 안 됨'으로 표시된 부분은 사실 증거가 더 "
    "필요한 것이니 단정하지 마세요."
)


class DisputeRequest(BaseModel):
    title: str = Field(default="분쟁 상담", description="분쟁 이름")
    situation: str = Field(
        min_length=10, description="억울한 분쟁 상황 자유 서술"
    )
    attachment_text: str = Field(
        default="",
        description="상대가 한 말, 약관·영수증·문자 등 관련 문서 텍스트 (선택)",
    )


class Issue(BaseModel):
    title: str = Field(description="쟁점 제목")
    my_claim: str = Field(description="이 쟁점에 대한 내 주장")
    their_claim: str = Field(default="", description="상대의 주장·입장 (알려진 경우)")
    search_queries: list[str] = Field(
        default_factory=list,
        description="근거 조사용 검색 쿼리 (법령·분쟁해결기준·조정 사례 중심)",
    )
    claim_type: str = Field(
        default=CLAIM_TYPE_FACTUAL,
        description=(
            "기준형: 기준이 정한 권리·환불·배상 방식에 대한 주장이라 기준 "
            "확인만으로 뒷받침됨. 사실형: 상대의 책임·피해 사실·금액 적정성 "
            "등 사실관계 입증이 별도로 필요한 주장"
        ),
    )
    evidence_present: bool = Field(
        default=False,
        description="사용자가 측정 자료·영수증·계약서·공식 접수 기록 같은 사실 증거를 제시했는가",
    )
    evidence_note: str = Field(
        default="", description="제시된 증거가 무엇인지, 또는 무엇이 없는지"
    )

    @field_validator("claim_type")
    @classmethod
    def check_claim_type(cls, v: str) -> str:
        if v not in CLAIM_TYPES:
            raise ValueError(f"알 수 없는 주장 유형: {v}")
        return v


class Evidence(BaseModel):
    issue_title: str
    status: str = Field(description="기준 확인됨 | 기준 확인 안 됨 (a단계)")
    claim_status: str = Field(
        default=CLAIM_NOT_PROVEN, description="주장 입증됨 | 주장 입증 안 됨 (b단계)"
    )
    claim_basis: str = Field(
        default="", description="주장 입증 판정의 이유 (무엇이 확인됐고 무엇이 부족한지)"
    )
    finding: str = Field(
        default="", description="조사 답변에서 정리한 근거 요지 (기준이 확인된 경우만)"
    )
    query_used: str = Field(default="", description="실제 사용한 검색 쿼리")
    sources: list[str] = Field(
        default_factory=list,
        description="조사 출처 전체 (공식 출처를 앞에 정렬)",
    )
    official_sources: list[str] = Field(
        default_factory=list, description="정부·공공 도메인 공식 출처"
    )
    other_sources: list[str] = Field(
        default_factory=list, description="비공식 출처 (블로그·SNS·언론 등)"
    )
    engine: str = Field(description="liner | mock — 이 쟁점의 조사 엔진")

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in STANDARD_STATUSES:
            raise ValueError(f"알 수 없는 기준 상태: {v}")
        return v

    @field_validator("claim_status")
    @classmethod
    def check_claim_status(cls, v: str) -> str:
        if v not in CLAIM_STATUSES:
            raise ValueError(f"알 수 없는 주장 상태: {v}")
        return v


class Rebuttal(BaseModel):
    expected: str = Field(description="상대가 할 것으로 예상되는 반박")
    counter: str = Field(description="그 반박에 대한 재대응 문장")


class ResponsePlan(BaseModel):
    stage1_script: str = Field(default="", description="1단계: 말로 할 스크립트")
    stage2_message: str = Field(default="", description="2단계: 문자·메일 문안")
    stage3_certified: str = Field(default="", description="3단계: 내용증명 문안")
    rebuttals: list[Rebuttal] = Field(default_factory=list)


class DisputeReport(BaseModel):
    title: str
    summary: str = Field(description="상황 요약")
    issues: list[Issue] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    supported_points: list[str] = Field(
        default_factory=list, description="주장 입증까지 된 내 주장 (b단계 통과)"
    )
    unsupported_points: list[str] = Field(
        default_factory=list,
        description="주장 입증이 안 된 내 주장 (기준 미확인 또는 사실 증거 부족)",
    )
    plan: ResponsePlan = Field(default_factory=ResponsePlan)
    report_markdown: str = Field(default="", description="리포트 한 장 (마크다운)")
    notice: str = Field(default=NOTICE, description="법률 자문 아님 고지")
    engine: str = Field(description="liner | mock | mixed — 사용한 엔진")
