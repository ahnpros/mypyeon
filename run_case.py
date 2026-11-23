"""케이스 실행 — 내 편 파이프라인을 케이스 파일로 전 과정 실행한다.

사용법 (project-mypyeon/ 디렉터리에서):
    python3 run_case.py samples/case1_gym.json
    python3 run_case.py samples/case1_gym.json samples/case1_report.json
    python3 run_case.py samples/case1_gym.json --mock

.env가 있으면 키를 환경 변수로 읽어 Liner 실연동을 시도한다
(키 값은 출력하지 않는다). --mock을 주면 키를 무시하고 폴백으로 돈다.
두 번째 인자로 경로를 주면 리포트 전체를 JSON으로 저장한다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent


def load_env() -> None:
    env_path = HERE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force_mock = "--mock" in sys.argv
    if not args:
        print("사용법: python3 run_case.py <케이스 JSON> [리포트 저장 경로] [--mock]")
        raise SystemExit(2)
    if force_mock:
        os.environ.pop("LINER_API_KEY", None)
    else:
        load_env()

    from app.models import DisputeRequest
    from app.pipeline import build_dispute_response

    case_path = Path(args[0])
    req = DisputeRequest(**json.loads(case_path.read_text(encoding="utf-8")))

    t0 = time.perf_counter()
    report = build_dispute_response(req)
    elapsed = time.perf_counter() - t0

    print(f"== 내 편 결과 — {report.title} ==")
    print(f"엔진: {report.engine} / 소요 {elapsed:.1f}초")
    print(f"요약: {report.summary}")
    print(f"쟁점 {len(report.issues)}개")
    for ev in report.evidence:
        print(
            f"- [{ev.status} / {ev.claim_status}] {ev.issue_title}: "
            f"출처 {len(ev.sources)}건 (공식 {len(ev.official_sources)}건)"
            + (f" (쿼리: {ev.query_used})" if ev.query_used else "")
        )
    print(f"입증된 주장 {len(report.supported_points)}개 / "
          f"입증 안 된 주장 {len(report.unsupported_points)}개")
    print(f"예상 반박 {len(report.plan.rebuttals)}개")
    if len(args) > 1:
        out = Path(args[1])
        out.write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"리포트 저장: {out}")


if __name__ == "__main__":
    main()
