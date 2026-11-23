"""Liner Platform 연동 — 내 편 (분쟁 대응 에이전트).

project-quote(견적체크)와 같은 방식:
- Base URL: https://platform.liner.com/api/v1
- 근거 조사는 AI Search API (POST /agents/search)를 쓴다. 근거 있는
  답변(answer)과 실제 검색 출처(references)를 함께 돌려주므로, 출처는
  모델이 지어낸 문자열이 아니라 검색 결과의 URL을 그대로 쓴다.
  인증은 x-api-key 헤더, stream=false 단건 JSON 응답.
- 쟁점 추출과 문안 생성은 Router API (POST /chat/completions,
  모델 liner-gpt-router, Authorization: Bearer)를 쓴다. Router는 웹
  검색을 하지 않으므로 근거 조사 자체에는 쓰지 않는다 — 조사는
  Search, 구조화와 문안 작성은 Router가 맡는다.

키가 없거나 호출이 실패하면 None을 돌려주고, 호출자는 폴백 경로를
탄다. 키는 코드에 직접 적지 않는다 (.env.example 참고).
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx

DEFAULT_BASE = "https://platform.liner.com/api/v1"
SEARCH_TIMEOUT = 240.0  # Search Agent 상한(300초) 아래에서 넉넉히
CHAT_TIMEOUT = 60.0
CHAT_LONG_TIMEOUT = 150.0  # 문안 생성처럼 출력이 긴 호출용
MAX_SOURCES = 6


def _base() -> str:
    return (os.environ.get("LINER_API_BASE") or DEFAULT_BASE).rstrip("/")


def liner_configured() -> bool:
    return bool(os.environ.get("LINER_API_KEY"))


def _post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict | None:
    """POST JSON 단건 호출. 실패하면 None.

    실행 환경 호환: 일부 환경의 no_proxy 표기(대괄호 IPv6)를 httpx가
    파싱하지 못해 InvalidURL로 즉시 실패하는 경우가 있다. 그때만
    trust_env를 끄고 표준 프록시 환경 변수를 명시해 재시도한다.
    """
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.InvalidURL:
        proxy = (
            os.environ.get("https_proxy")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("http_proxy")
            or os.environ.get("HTTP_PROXY")
        )
        try:
            with httpx.Client(trust_env=False, proxy=proxy, timeout=timeout) as c:
                r = c.post(url, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception:
            return None
    except Exception:
        return None


def chat_with_liner(prompt: str, timeout: float = CHAT_TIMEOUT) -> str | None:
    """Router API 채팅 호출 (웹 검색 없음). 실패하면 None."""
    key = os.environ.get("LINER_API_KEY")
    if not key:
        return None
    model = os.environ.get("LINER_MODEL") or "liner-gpt-router"
    data = _post_json(
        f"{_base()}/chat/completions",
        {"Authorization": f"Bearer {key}"},
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout,
    )
    if not data:
        return None
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def search_with_liner(query: str) -> tuple[str, list[str]] | None:
    """AI Search API 단건 호출. 성공하면 (답변 텍스트, 출처 URL 목록).

    출처는 references의 실제 URL만 쓴다. 답변이 없거나 출처가 비어 있으면
    근거 없는 결과라 실패(None)로 취급한다.
    """
    key = os.environ.get("LINER_API_KEY")
    if not key:
        return None
    data = _post_json(
        f"{_base()}/agents/search",
        {"x-api-key": key, "Content-Type": "application/json"},
        {
            "messages": [{"role": "user", "content": query}],
            "lang": "ko",
            "stream": False,
        },
        SEARCH_TIMEOUT,
    )
    if not data:
        return None
    answer = (data.get("answer") or "").strip()
    if not answer:
        return None
    urls: list[str] = []
    for ref in data.get("references") or []:
        if isinstance(ref, dict):
            url = (ref.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
        if len(urls) >= MAX_SOURCES:
            break
    if not urls:
        return None
    return answer, urls


# ------------------------------------------------------------ 출처 품질


def is_official_source(url: str) -> bool:
    """정부·공공 도메인(.go.kr) 출처인가. law.go.kr, easylaw.go.kr,
    ftc.go.kr, kca.go.kr, 지방자치단체 사이트 등이 여기에 든다."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "go.kr" or host.endswith(".go.kr")


def split_sources(urls: list[str]) -> tuple[list[str], list[str]]:
    """출처를 (공식, 비공식)으로 나눈다. 각 그룹 안의 순서는 유지한다."""
    official = [u for u in urls if is_official_source(u)]
    other = [u for u in urls if not is_official_source(u)]
    return official, other


def sort_sources(urls: list[str]) -> list[str]:
    """공식 출처를 앞으로 정렬한 전체 목록."""
    official, other = split_sources(urls)
    return official + other


# ------------------------------------------------------------ 텍스트 정리


def clean_text(text: str) -> str:
    """조사 답변을 화면 표시용 평문으로 정리한다.

    인용 마커(((18)), [12])와 마크다운 잔재를 걷어낸다: 제목 기호(#),
    표 기호(|)와 표 구분선, 글머리 기호, 굵은 글씨 표시, 마크다운
    링크, LaTeX 수식 구분자($$, \\(, \\))와 수식 명령 일부.
    """
    text = re.sub(r"\(\(\d+\)\)", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    # 마크다운 링크 [텍스트](url) -> 텍스트
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # 표 구분선 행 (|---|---| 처럼 기호만 있는 행)과 수평선 행 제거
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and set(stripped) <= set("|: -—") and "--" in stripped:
            continue
        lines.append(line)
    text = "\n".join(lines)
    # 표 기호는 열 구분이므로 쉼표로 바꾼다
    text = text.replace("|", ", ")
    # 수식 구분자와 흔한 LaTeX 명령 제거 (내용 숫자는 남긴다)
    text = text.replace("$$", " ").replace("$", " ")
    text = re.sub(r"\\[()\[\]]", " ", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf|le|ge|times|cdot)\b", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    # 제목 기호, 글머리 기호, 인용 기호 제거
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip(" ,")
