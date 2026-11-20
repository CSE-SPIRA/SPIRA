"""Korean display text for recorded Hub facts and outcomes."""

DEVICE_NAMES = {
    "cleaner": "청소기", "light": "조명", "display": "TV", "cooktop": "인덕션",
    "oven": "오븐", "fridge": "냉장고", "smart_plug": "플러그", "speaker": "스피커",
}
HOME_EVENTS = {
    "package.brought_in": ("현관", "택배 들임"),
    "guest_arrived": ("현관", "손님 도착"),
    "event_end": ("—", "일정 끝 관찰"),
}
DEVICE_EVENTS = {"started": "시작", "stopped": "멈춤", "completed": "끝남", "door_opened": "문 열림"}
SCENES = {"kids_party": "어린이 파티", "party": "파티", "calm": "차분한 분위기", "cinema": "영화"}
PLAYLISTS = {"calm": "잔잔한 음악", "party": "파티 음악", "family": "가족 음악"}
RUN_STATUS = {
    "dispatching": "응답 확인 중", "blocked": "실행 보류", "failed": "실행 실패",
    "unknown": "실행 여부 모름", "unverifiable": "실행 확인 안 됨",
}
RESTORE_STATUS = {
    "dispatching": "되돌리는 중", "failed": "되돌리기 실패", "unknown": "되돌림 확인 안 됨",
    "not_needed": "되돌릴 것 없음", "withheld_end_not_observed": "그대로 (끝 확인 안 됨)",
}


def device_words(device_id, devices):
    device = devices.get(device_id)
    return (device.label or DEVICE_NAMES.get(device.type, device_id)) if device else device_id


def plan_words(version, count, task_devices, devices):
    what = [f'계획 v{version["plan_version"]} 받음']
    if count is not None:
        what.append(f"할 일 {count}")
    rejected = version["ack"]["packet"]["rejected_tasks"]
    if rejected:
        what.append(f"받지 못한 일 {len(rejected)}")
    changes = version["changes"]
    if changes:
        for item in changes["cancelled"]:
            task_id = item["task_id"]
            labels = [device_words(device, devices) for device in task_devices.get((version["plan_id"], task_id), [])]
            what.append(f'{", ".join(labels) or task_id} 취소')
        if any(change["from"].get("released") is False and change["to"].get("released") is True
               for change in changes["triggers_changed"]):
            what.append("택배 기다림 해제")
    return " · ".join(what)


def number_words(value):
    return str(int(value)) if type(value) is float and value.is_integer() else str(value)


def property_words(prop, value):
    if prop == "power" and (type(value) is bool or value in ("on", "off")):
        return "켜짐" if value is True or value == "on" else "꺼짐"
    if prop == "child_lock" and type(value) is bool:
        return "잠금" if value else "잠금 해제"
    if prop == "show_notice":
        return "평소 화면" if value is None else "안내 표시"
    if prop in ("play_mood", "scene"):
        if isinstance(value, dict) and isinstance(scene := value.get("scene"), str):
            return f"{SCENES.get(scene, scene)} 화면"
        if value is None:
            return "꺼짐"
    if prop == "play":
        if isinstance(value, dict) and isinstance(playlist := value.get("playlist"), str):
            volume = value.get("volume")
            return f"{PLAYLISTS.get(playlist, playlist)} · 볼륨 {number_words(volume)}"
        if value is None:
            return "꺼짐"
    if prop in ("color", "color_temp") and isinstance(value, dict):
        if "kelvin" in value:
            return f'{number_words(value["kelvin"])}K'
        if "hue" in value:
            return f'색조 {number_words(value["hue"])}°'
    if prop == "preset" and isinstance(value, dict) and {"temp_c", "minutes"} <= value.keys():
        return f'{number_words(value["temp_c"])}° {number_words(value["minutes"])}분 대기'
    return None


def run_words(cmd, value, status):
    if cmd == "clean":
        what = "청소 끝" if status == "completed" else "청소 시작" if status == "running" else "청소"
    elif cmd in ("child_lock", "off", "stop", "show_notice"):
        what = {"child_lock": "잠금", "off": "끔", "stop": "멈춤", "show_notice": "안내 표시"}[cmd]
    else:
        prop = {"set_cook_standby": "preset"}.get(cmd, cmd)
        what = property_words(prop, value) or f"{cmd} 요청"
    if status in RUN_STATUS:
        return f"{what} · {RUN_STATUS[status]}"
    return what


def restore_words(status, writes, originals):
    if status == "skipped_user_changed":
        partial = any(
            attempt["status"] == "restored" or (
                attempt["status"] == "skipped_user_changed" and (attempt["ack"] or {}).get("status") == "ACCEPTED"
            ) for attempt in writes
        )
        kept = "일부 그대로" if partial else "그대로"
        released = [claim for attempt in originals for claim in attempt["claims"].values() if not claim["owned"]]
        if released and all(claim.get("released_by") == "user" for claim in released):
            return f"{kept} (사람이 바꿈)"
        return f"{kept} (기기 상태가 바뀜)"
    if status == "restored":
        values = [property_words(prop, value) for attempt in writes if attempt["status"] == "restored"
                  for prop, value in attempt["desired"].items()]
        return "되돌림 → " + " · ".join(values) if values and all(values) else "되돌림"
    return RESTORE_STATUS[status]


def event_words(event, devices):
    event_type = event["type"]
    if event_type in HOME_EVENTS:
        return HOME_EVENTS[event_type]
    label = device_words(event["source"], devices)
    suffix = event_type.rsplit(".", 1)[-1]
    if suffix == "changed":
        payload = event["payload"]
        before = property_words(payload["property"], payload["from"])
        after = property_words(payload["property"], payload["to"])
        what = f"{before} → {after}" if before and after else (f"{after}로 바뀜" if after else "설정 바뀜")
        return label, what
    return label, DEVICE_EVENTS.get(suffix, event_type)
