"""Rehearsal cases and the evidence each one uses."""

from dataclasses import asdict, dataclass, field

RULES = "contracts/rules.md"
ERROR = "contracts/schemas/error.json"
SERVER = "server/spec.md"
ORDER = "contracts/openapi/app.yaml §APP-07"
DERIVED_FIELDS = {
    "ack-device": ("actions[0].device", "fixture_unknown_01"),
    "ack-command": ("actions[0].cmd", "fixture_unknown"),
    "ack-value": ("actions[0].value.temp_c", 999),
}


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    group: str
    source: str
    app: str
    hub: str
    house: str
    shell: str
    arm: str
    test: str = ""
    action: dict = field(default_factory=dict)
    needs: str = ""
    household: str | None = None

    def entry(self, household):
        needs = self.needs
        if self.household and self.household != household:
            needs = f"{self.household} fixture"
        return {**asdict(self), "needs": needs, "reproducible": not needs}


CASES = [
    Case("invalid-image", "읽을 수 없는 이미지", "order", f"synthetic · {RULES}:89 · App OpenAPI POST /v1/orders",
         "공유 요청 400 invalid_image", "새 계획 없음", "변화 없음", "공유 실패, 회차 미진입",
         "다음 공유 요청을 한 번 거절합니다. 앱에서 공유하거나 아래 샘플을 공유하세요.",
         "test_order_responses[invalid-image]", {"fault": {"group": "app", "kind": "status", "status": 400,
          "route": "order", "count": 1}}),
    Case("read-failed", "상품 읽기 실패", "order", f"synthetic outcome · common.json#EpisodeStatus · {SERVER}:513",
         "202 후 회차 read_failed, 상품 0개", "새 계획 없음", "변화 없음", "회차는 있으나 판단 근거 없음",
         "다음 공유에 적용합니다. 읽기 완료 시각까지 진행하세요.",
         "test_read_failed", {"share_mode": "read_failed"}),
    Case("duplicate-share", "같은 공유 재전송", "order", f"{RULES}:64",
         "동일 source_id에 200, 같은 episode_id", "한 회차의 계획", "중복 준비 없음", "회차 추가 없음",
         "회차에서 샘플 공유 후 같은 요청 재전송을 누르세요. 실제 앱의 동일 source_id 재전송도 관찰할 수 있습니다.",
         "test_order_responses[duplicate-share]"),
    Case("paused-share", "일시정지 중 공유 후 재개", "order", f"{RULES}:73 · common.json#EpisodeStatus",
         "공유 202 paused_skip, 재개 후 새 공유 가능", "paused: true → false", "새 동작 없음, 실행 중 효과 유지",
         "일시정지한 회차에 판단 근거 없음", "가구를 일시정지합니다. 공유한 뒤 앱 또는 회차에서 재개하세요.",
         "test_pause_and_paused_share", {"pause": True}),
    Case("second-capture", "조용한 시간 중 두 번째 캡처", "order",
         f"ep_9031/timeline.md:7 · {RULES}:10,81 · {SERVER}:505",
         "다른 source_id에 202, 같은 episode_id", "연장된 판단 후 계획 하나",
         "중복 준비 없음", "같은 회차, 조용한 시간 연장",
         "생일 샘플을 공유한 뒤 조용한 시간이 끝나기 전에 두 번째 캡처를 누르세요.",
         "test_second_capture", {"episode": "ep_9031", "share_mode": "second_capture", "pace": "server", "next": True},
         household="h_042"),
    Case("order-edit", "주문 수정 접수", "order", ORDER,
         "PUT에 202 received", "기록된 재판단 계획 없음", "변화 없음", "접수된 주문의 기존 기록",
         "상품이 보이는 회차에서 앱의 주문 수정 요청을 보내세요. 이 경로는 접수 응답만 재현합니다.",
         "test_order_responses[order-edit]"),
    Case("stale-edit", "주문 수정 충돌", "order", f"synthetic · {ERROR} · common.json#ErrorCode · {ORDER}",
         "다음 수정 요청 409 stale_revision", "새 계획 없음", "변화 없음", "기존 회차 유지",
         "앱에서 주문을 수정하세요. 주문 수정 계약에는 버전 필드와 409 응답 정의가 없습니다.",
         "test_order_responses[stale-edit]", {"fault": {"group": "app", "kind": "status", "status": 409,
          "route": "edit", "count": 1}}),
    Case("edit-rejudge", "주문 수정 뒤 재판단", "order", "contracts/schemas/order_edit.json",
         "수정된 상품과 카드", "이미 시작한 작업은 유지", "후속 작업만 바뀜", "수정된 근거",
         "", needs="recorded corrected items, rationale, card and plan after the edit"),
    Case("birthday", "생일 주문 전체", "results", "ep_9031",
         "준비 카드와 상품 알림", "카드 작업과 상품 작업을 받음", "기록된 조건에 따라 청소·안전·조명·오븐",
         "상품부터 허브 장부까지", "다음 공유를 생일로 선택합니다.",
         "test_recorded_results[birthday]", {"episode": "ep_9031"}, household="h_042"),
    Case("groceries", "장보기 · 의도 없음", "results", "ep_9150/rationale.json",
         "상품과 보관 안내, 준비 카드 없음", "상품 알림 계획", "택배 후 냉장고 안내",
         "기록에 있는 none_reason", "다음 공유를 장보기로 선택합니다.",
         "test_recorded_results[groceries]", {"episode": "ep_9150"}, household="h_042"),
    Case("held", "일정 대기 카드", "results", "ep_9120/card.held.json",
         "held 카드, 시작 시각 없음", "일정 대기 작업은 아직 계획에 없음", "상품 작업은 별도로 대기",
         "캘린더 판단 근거 기록은 없음", "h_051 fixture에서 다음 공유를 예약합니다.",
         "test_recorded_results[held]", {"episode": "ep_9120"}, household="h_051"),
    Case("calendar", "기록된 일정 적용", "results", "ep_9120/calendar.json · card.found.json · plan.v2.json",
         "시각이 정해진 카드, notify: true", "새 버전 풀과 ack", "찾은 시각에 준비",
         "일정 적용과 새 계획을 확인", "대기 카드가 나온 뒤 누르세요. 기록된 일정을 앱의 캘린더 경로로 보냅니다.",
         "test_recorded_results[calendar]", {"calendar": True}, household="h_051"),
    Case("unclassified", "분류되지 않은 의도", "results", "common.json#ReservedIntent · server/spec.md:729",
         "기록에 맞는 카드", "실행 작업 없음", "기기 실행 없음", "unclassified 근거",
         "", needs="recorded unclassified rationale, card and plan"),
    Case("two-cards", "한 주문에 카드 두 장", "results", f"{RULES}:11",
         "카드 두 장", "같은 회차의 작업", "각 줄 조건에서 동작", "두 의도와 대응 작업",
         "", needs="recorded rationale, two cards and their matching plan"),
    Case("judgment-failed", "읽기 이후 판단 실패", "results", "server/spec.md:421 · contracts/schemas/episode.json",
         "판단 실패를 구별할 계약 응답 필요", "실패 시 계획 공개 기준 확인 필요", "새 실행 없음",
         "실패와 정상 무의도 구분 필요", "", needs="public S2–S4 failure response and an agreed client-visible signal"),
    Case("server-pace", "서버 기본 숫자", "timing", "server/config/numbers.yaml · fixture STAGE_GAPS (assumed)",
         "평상시 읽기·카드 진행", "공개 후 계획", "계획 조건 대기", "단계별 진행",
         "현재 미완료 단계에 적용합니다. 회차가 없거나 판단이 끝났으면 다음 공유에 적용합니다.",
         "test_paces[server]", {"pace": "server"}),
    Case("fast", "빠른 리허설", "timing", "fixture STAGE_GAPS (assumed)",
         "읽기·카드가 빠르게 진행", "계획 조기 공개", "기록된 작업 시각 유지", "짧은 단계 대기",
         "조용한 시간과 판단 간격을 줄입니다. 현재 미완료 단계 또는 다음 공유에 적용합니다.",
         "test_paces[fast]", {"pace": "fast"}),
    Case("slow", "느린 LLM", "timing", "fixture STAGE_GAPS × 4 (assumed)",
         "읽기·카드 지연", "공개 전 새 계획 없음", "새 동작 없음", "남은 단계가 오래 대기",
         "서버 조용한 시간과 판단 간격을 네 배로 늘립니다. 현재 미완료 단계 또는 다음 공유에 적용합니다.",
         "test_paces[slow]", {"pace": "slow"}),
]

STAGE_NAMES = {
    "received": "공유 접수", "reading": "읽기 시작", "items": "상품 읽기 완료",
    "quiet_window": "조용한 시간 종료", "evidence": "근거", "intents": "의도",
    "tasks": "작업", "published": "카드·계획 공개",
}

CASES += [
    Case(f"stuck-{stage}", f"{title} 단계에서 멈춤", "timing", "fixture STAGE_GAPS (assumed)",
         "직전까지 공개된 회차 상태", "공개까지 새 계획 없음", "새 작업 없음", "해당 단계 대기",
         f"{title} 직전에 멈춥니다. 접수에서 멈추면 회차는 received로 보입니다. 판단 속도에서 해제하세요.",
         f"test_stuck_and_release[{stage}]", {"hold": stage})
    for stage, title in STAGE_NAMES.items()
]

CASES += [
    Case("release-now", "판단 지금 끝내기", "timing", "fixture STAGE_GAPS (assumed)",
         "기록된 최종 판단", "계획 공개", "기록된 작업 조건 대기", "카드·계획까지 진행",
         "공유된 회차의 남은 판단 시각을 지금으로 당깁니다.", "test_stuck_and_release[published]", {"release": True}),
    Case("partial-rationale", "중간 근거만 보기", "timing", "ep_9031/rationale.json · live projection",
         "카드 전, 근거만 받은 상태", "새 계획 없음", "새 동작 없음", "근거 있음, 의도·작업 대기",
         "생일을 공유하고 근거까지 진행합니다. 의도 단계에서 멈춥니다.",
         "test_partial_rationale", {"episode": "ep_9031", "hold": "intents", "next": True}, household="h_042"),
    Case("package", "택배 들이기 · 계획 새 버전", "plans", f"ep_9031/events.json · {RULES}:35,39",
         "상품 알림 상태 갱신", "plans_changed: true, 즉시 풀, released: true", "냉장고 상품 안내",
         "택배 사건 · 새 버전", "생일 또는 장보기 계획이 공개된 뒤 집에서 택배를 들이세요.",
         "test_package_and_event_resend[package]", household="h_042"),
    Case("equal-plan", "같은 계획 버전 재전송", "plans", f"{RULES}:36 · recorded plan",
         "카드 유지", "같은 버전 무시", "동작 반복 없음", "새 수신 장부 없음",
         "허브가 현재 버전을 받은 뒤 누르세요. 다음 풀에 같은 버전을 한 번 보냅니다.",
         "test_control_ignores_replayed_version[equal-plan]", {"plan": "equal"}),
    Case("lower-plan", "이전 계획 버전 재전송", "plans", f"{RULES}:36 · recorded plan history",
         "최신 카드 유지", "이전 버전 무시", "취소된 작업이 돌아오지 않음", "장부의 최신 버전 유지",
         "줄 끄기 등으로 버전을 올리고 허브가 두 버전을 받은 뒤 누르세요. 다음 풀에 이전 버전을 한 번 보냅니다.",
         "test_control_ignores_replayed_version[lower-plan]", {"plan": "lower"}),
]

CASES += [
    Case(case_id, f"수신 거절 · {title}", "plans",
         f"derived from ep_9031, changed t_oven#4.{DERIVED_FIELDS[case_id][0]} · {RULES}:40",
         "오븐 줄 failed", "해당 줄 거절, 다른 줄 정상", "오븐 작업 없음", "거절 이유와 failed 줄",
         "다음 생일을 선택합니다. 허브에게 처음 보내는 계획의 오븐 작업 한 필드를 바꿉니다.",
         f"test_control_ack_rejection[{case_id}]", {"episode": "ep_9031", "plan": case_id}, household="h_042")
    for case_id, title in (
        ("ack-device", "알 수 없는 기기"), ("ack-command", "지원하지 않는 명령"), ("ack-value", "범위 밖 값"),
    )
]

CASES += [
    Case("preflight", "실행 직전 계획 확인 실패", "plans", f"synthetic · {RULES}:41,89",
         "실행 결과가 줄에 반영", "blocked: plan_unconfirmed", "새 동작 없음, 기존 안전·복원 유지",
         "계획 풀 503과 차단 기록", "계획 수신 뒤 실행 직전에 누르세요. 차단을 확인하고 해제할 때까지 GET plans에 503을 보냅니다.",
         "test_control_preflight_failure", {"fault": {"group": "hub", "kind": "status", "status": 503,
          "route": "plans", "count": None}}),
    Case("event-resend", "집 이벤트 적용 후 응답 실패", "plans", f"synthetic · {RULES}:62,89",
         "카드에 한 번 반영", "503 뒤 같은 event_id 재전송, 반영 한 번", "중복 실행 없음",
         "같은 이벤트, 새 버전 한 번", "다음 이벤트 배치를 적용한 뒤 503을 보냅니다. 집에서 이벤트를 보내세요.",
         "test_package_and_event_resend[event-resend]", {"fault": {"group": "hub", "kind": "apply_then_fail", "route": "events", "count": 1}}),
    Case("result-resend", "실행 결과 적용 후 응답 실패", "plans", f"synthetic · {RULES}:63,89",
         "줄에 결과 한 번 반영", "503 뒤 같은 result_id 재전송 → duplicate: true", "동작 반복 없음",
         "응답 실패와 재전송", "다음 실행 결과를 적용한 뒤 503을 보냅니다. 계획 작업을 실행하세요.",
         "test_execution_resend", {"fault": {"group": "hub", "kind": "apply_then_fail", "route": "executions", "count": 1}}),
    Case("line-off-before", "실행 전 줄 끄기", "reactions", f"ep_9031/reactions.json · {RULES}:37–38,71",
         "줄 off", "새 버전, cancelled.restore: false", "해당 줄 실행 없음", "꺼진 줄 · 새 버전",
         "시작 전 앱 또는 데모 셸에서 준비 줄을 끄세요.", "test_line_reactions[line-off-before]"),
    Case("line-off-after", "실행 후 줄 끄기", "reactions", f"{RULES}:37–38,71",
         "줄 off, 복원 결과", "새 버전, cancelled.restore: true", "허브가 소유한 효과 복원", "꺼진 줄 · 복원 기록",
         "허브 실행이 기록된 줄을 앱에서 끄세요.", "test_line_reactions[line-off-after]"),
    Case("line-on-after", "시작한 줄 다시 켜기", "reactions", f"{RULES}:71",
         "409 line_started", "새 버전 없음", "다시 실행하지 않음", "꺼진 줄 유지",
         "허브 실행이 기록된 줄을 끈 다음 같은 줄을 다시 켜세요.", "test_line_reactions[line-on-after]"),
    Case("stop", "준비 중지 후 반응 무시", "reactions", f"{RULES}:37–38,72",
         "stopped, 후속 반응 200", "카드 작업 취소, 상품 작업 유지", "시작된 카드 효과 복원",
         "중지된 카드와 복원 기록", "앱에서 카드 중지 후 같은 카드의 줄 반응을 재전송하세요.", "test_stop_ignores_reactions"),
    Case("pause-resume", "가구 일시정지와 재개", "reactions", f"{RULES}:38,73",
         "일시정지 후 재개", "새 버전, 미시작 작업 취소", "실행 중 효과 유지",
         "취소된 줄과 허브 기록", "작업이 남은 회차에서 앱으로 일시정지 후 재개하세요.", "test_pause_and_paused_share"),
    Case("memory-delete", "우리 집 기억 삭제", "reactions", "ep_9031/memory.json · App OpenAPI DELETE memory",
         "204 뒤 기억에서 삭제", "계획 유지", "변화 없음", "기억 목록에서 빠짐",
         "생일을 마쳐 관찰과 기억이 저장되면 앱에서 그 기억을 삭제하세요.", "test_memory_delete"),
]

AVAILABILITY = [
    ("latency", "응답 지연", "app", "latency", "응답 1.5초 지연", "계획에 따른 진행", "다음 앱 요청 한 번"),
    ("internal", "서버 내부 오류", "app", "status", "500 internal", "계획에 따른 진행", "다음 앱 요청 한 번", 500),
    ("app-unavailable", "앱 연결 불가", "app", "status", "503", "계획에 따른 진행", "다음 앱 요청 한 번", 503),
    ("hub-unavailable", "허브 연결 불가", "hub", "status", "기존 카드 유지", "503 뒤 요청 재시도", "다음 허브 요청 한 번", 503),
    ("app-drop", "앱 연결 끊김", "app", "drop", "응답 본문 수신 실패", "계획에 따른 진행", "다음 앱 요청 한 번"),
    ("hub-drop", "허브 연결 끊김", "hub", "drop", "결과 반영 지연 가능", "응답 본문 수신 실패", "다음 허브 요청 한 번"),
    ("app-unauthorized", "앱 인증 거절", "app", "status", "401 unauthorized", "계획에 따른 진행", "다음 앱 요청 한 번", 401),
    ("forbidden", "접근 거절", "app", "status", "403 forbidden", "계획에 따른 진행", "다음 앱 요청 한 번", 403),
    ("not-found", "앱 대상 없음", "app", "status", "404 not_found", "계획에 따른 진행", "다음 앱 요청 한 번", 404),
    ("health", "상태 확인 저하", "health", "status", "기존 카드 유지", "계획 경로는 계속 응답", "상태 확인 요청 전체", 503),
    ("no-clock", "시계 경로 없음", "clock", "status", "기존 카드 유지", "시계 읽기 404", "GET 시계 요청 전체", 404),
]

for case_id, title, group, kind, app, hub, arm, *status in AVAILABILITY:
    fault = {"group": group, "kind": kind, "count": None if group in ("health", "clock") else 1}
    if status:
        fault["status"] = status[0]
    if kind == "latency":
        fault["delay_ms"] = 1500
    if group == "clock":
        fault["route"] = "clock-read"
    source = f"synthetic · {RULES}:89"
    if group == "health":
        source += " · contracts/schemas/health.json"
    shell = {"clock": "시계 읽기 중단", "health": "상태 확인 503 degraded"}.get(group, "요청 기록에 지연 또는 오류")
    CASES.append(Case(case_id, title, "reactions" if case_id == "app-unauthorized" else "availability",
                      source, app, hub, "새 동작은 확인된 계획에 따름", shell, f"{arm}에 적용합니다.",
                      f"test_availability[{case_id}]", {"fault": fault}))

CASES_BY_ID = {case.id: case for case in CASES}
