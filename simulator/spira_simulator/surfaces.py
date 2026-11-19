"""Presentation data and device controls for the Simulator's household pages."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from math import ceil

from pydantic import HttpUrl, ValidationError

from .profile import Device
from .world import PEOPLE, SEOUL, World

DEVICE_NAMES = {
    "cleaner": "청소기",
    "light": "조명",
    "display": "TV",
    "cooktop": "인덕션",
    "oven": "오븐",
    "fridge": "냉장고",
    "smart_plug": "플러그",
    "speaker": "스피커",
}
ROOM_NAMES = {"living_room": "거실", "kitchen": "주방", "bedroom": "침실"}
SCENES = {
    "kids_party": "공주 화면",
    "party": "파티 화면",
    "calm": "잔잔한 화면",
    "cinema": "영화 화면",
}
PLAYLISTS = {"calm": "잔잔한 음악", "party": "파티 음악", "family": "가족 모임 음악"}
COMMAND_NAMES = {
    "clean": "청소",
    "color": "조명 색상 변경",
    "color_temp": "색온도 변경",
    "play_mood": "분위기 화면",
    "off": "끄기",
    "child_lock": "잠금",
    "set_cook_standby": "굽기 설정 대기",
    "show_notice": "안내 표시",
    "play": "음악 재생",
    "stop": "정지",
}
TRIGGER_NAMES = {
    "package.brought_in": "택배를 들이면",
    "guest_arrived": "손님 오면",
    "event_end": "행사가 끝나면",
}
RESTORE_NAMES = {
    "restored": "되돌림",
    "not_needed": "되돌릴 값 없음",
    "skipped_user_changed": "바뀐 값 유지",
    "failed": "되돌리기 실패",
    "unknown": "되돌림 확인 불가",
    "withheld_end_not_observed": "종료 미관찰로 잠금·차단 유지",
}
OBSERVATION_NAMES = {
    "stale": "오래된 관찰값",
    "missing": "관찰값 누락",
    "unavailable": "관찰 불가",
}
ENTRANCE_EVENTS = {
    "camera.package_removed": ("package", "택배 들임"),
    "doorbell.pressed": ("bell", "초인종 울림"),
    "door_lock.opened": ("door", "문 열림 감지"),
    "presence.room_occupied": ("presence", "손님 있음"),
    "presence.room_empty": ("presence", "손님 나감"),
}

ON = "켜짐"
OFF = "꺼짐"


def peer_viewers(setting: str) -> list[tuple[str, str]]:
    peers = []
    for entry in setting.split(","):
        name, _, url = entry.partition("=")
        if not name.strip():
            continue
        try:
            address = HttpUrl(url.strip())
        except ValidationError:
            continue
        if address.username is None and address.password is None:
            peers.append((name.strip(), str(address)))
    return peers


def display_time(at: str | datetime) -> str:
    try:
        instant = datetime.fromisoformat(at) if isinstance(at, str) else at
        local = instant.astimezone(SEOUL)
    except ValueError:
        return "시각 확인 불가"
    return f"{local.month}/{local.day} {'월화수목금토일'[local.weekday()]} {local:%H:%M}"


def device_name(device: Device) -> str:
    if device.label:
        return {"Kettle plug": "포트 플러그", "Virtual light panel": "조명"}.get(
            device.label, device.label
        )
    return DEVICE_NAMES.get(device.device_type, device.logical_id)


def number_text(value: int | float) -> str:
    return str(value).removesuffix(".0")


def household_content(tile: dict) -> str | None:
    values = tile["values"]
    if not values:
        return None
    match tile["device_type"]:
        case "light":
            color = values.get("color") or {}
            if values.get("power") is False:
                return OFF
            if "kelvin" in color:
                return f"{number_text(color['kelvin'])}K"
            if all(key in color for key in ("hue", "saturation", "brightness")):
                hue, saturation, brightness = (
                    color[key] for key in ("hue", "saturation", "brightness")
                )
                name = "분홍" if hue == 330 and saturation else "색상"
                return f"{name} {number_text(hue)}/{number_text(saturation)}/{number_text(brightness)}"
        case "display":
            scene = values.get("play_mood")
            return SCENES.get(scene.get("scene"), "화면 켜짐") if scene else OFF
        case "oven":
            preset = values.get("preset") or {}
            content = [f"{number_text(preset['temp_c'])}°"] if preset else []
            match values.get("job_status"):
                case "running":
                    due = tile.get("job_due")
                    if due:
                        observed_at = datetime.fromisoformat(tile["observed_at"])
                        remaining = datetime.fromisoformat(due) - observed_at
                        minutes = max(0, ceil(remaining.total_seconds() / 60))
                        content.append(f"{minutes}분 남음")
                    return " · ".join([*content, "굽는 중"])
                case "completed":
                    return "다 구움"
                case "stopped":
                    return "굽기 중지"
            if content:
                return " · ".join([*content, f"{number_text(preset['minutes'])}분", "대기"])
            return OFF
        case "fridge":
            notice = values.get("show_notice")
            return notice if notice is not None else "평소 화면"
        case "cleaner":
            return {
                "running": "청소 중",
                "completed": "청소 끝",
                "stopped": "청소 중지",
                "idle": "대기 중",
            }.get(values.get("job_status"))
        case "cooktop":
            if values.get("in_use"):
                return "사용 중"
            if "child_lock" in values:
                return "잠금" if values["child_lock"] else "잠금 해제"
        case "speaker":
            play = values.get("play")
            if play:
                return f"{PLAYLISTS.get(play['playlist'], '음악 재생')} · 볼륨 {number_text(play['volume'])}"
            return "재생 안 함"
    if "power" in values:
        return ON if values["power"] else OFF
    return None


def latest_change(fact: dict) -> tuple[str, str] | None:
    if fact["actor"] == "spira":
        return "spira", "SPIRA"
    if fact["actor"] == "device_self":
        return None
    if fact["actor"] in PEOPLE and fact.get("actor_name"):
        path = {"device_panel": "기기 패널", "other_app": "가전 앱"}.get(
            fact.get("action_path")
        )
        name = fact["actor_name"]
        return "person", f"{name} · {path}" if path else name
    return "unknown", "누가 바꿨는지 모름"


def tiles(world: World, snapshot: dict, changes: dict | None = None) -> list[dict]:
    result = []
    for report in snapshot["devices"]:
        target = report["target"]
        device = world.devices[target]
        status = report["observation"]
        result.append(
            {
                "id": device.logical_id,
                "name": device_name(device),
                "room": device.room,
                "content": household_content(report),
                "observation": status,
                "observation_label": OBSERVATION_NAMES.get(status),
                "observed_at": display_time(report["observed_at"]),
                "substrate": "가상" if device.substrate == "virtual" else "실물",
                "physical": device.substrate == "physical",
                "class_a": device.local_operation_reporting,
                "assumption": device.assumption,
                "change": (
                    changes.get(target)
                    if changes is not None and status == "current"
                    else None
                ),
            }
        )
    return result


def viewer_world(world: World) -> dict:
    with world.store.lock:
        now = world.clock()
        snapshot = world.snapshot(for_display=True)
        truth = world.store.latest_truth()
    changes = {
        fact["target"]: latest_change(fact)
        for fact in truth
        if fact["logical_id"] is not None
    }
    entrance = {}
    for fact in truth:
        event = ENTRANCE_EVENTS.get(fact["event_type"])
        if fact["logical_id"] is None and event:
            sensor, label = event
            entrance[sensor] = {"label": label, "at": display_time(fact["occurred_at"])}
    return {
        "clock": display_time(now),
        "clock_at": now.isoformat(),
        "tiles": tiles(world, snapshot, changes),
        "entrance": list(entrance.values()),
    }


def planned_value(command: str, value) -> str | None:
    """The target of a planned action, in household words (device-level only)."""
    if not isinstance(value, dict):
        return None
    match command:
        case "play_mood":
            return SCENES.get(value.get("scene"))
        case "color" if all(k in value for k in ("hue", "saturation", "brightness")):
            name = "분홍" if value["hue"] == 330 and value["saturation"] else "색상"
            return f"{name} {number_text(value['hue'])}/{number_text(value['saturation'])}/{number_text(value['brightness'])}"
        case "color_temp" if "kelvin" in value:
            return f"{number_text(value['kelvin'])}K"
        case "set_cook_standby" if "temp_c" in value:
            minutes = value.get("minutes")
            return f"{number_text(value['temp_c'])}°" + (f" {number_text(minutes)}분" if minutes else "")
        case "play" if value.get("playlist"):
            return PLAYLISTS.get(value["playlist"], "음악 재생")
    return None


def viewer_plan(data: dict, device_names: dict) -> tuple[dict, list[dict]]:
    planned = defaultdict(list)
    for row in data["preparation"] + data["notices"]:
        wait = row["wait"]
        planned[row["device"]].append(
            {
                "action": " ".join(
                    part for part in (
                        COMMAND_NAMES.get(row["command"], row["command"]),
                        planned_value(row["command"], row.get("target_value")),
                    ) if part
                ),
                "wait": TRIGGER_NAMES.get(wait) or display_time(wait),
            }
        )
    restores = [
        {
            "device": device_names.get(row["device"], row["device"]),
            "outcome": RESTORE_NAMES[row["status"]],
            "substrate": {"virtual": "가상", "physical": "실물 · 미검증"}.get(
                row["substrate"], "기기 유형 미확인"
            ),
            "at": display_time(row["at"]),
            "pending": row.get("delivery") == "not_delivered",
        }
        for row in data["restores"]
    ]
    return planned, restores


@dataclass(frozen=True)
class Control:
    key: str
    label: str
    values: dict = field(default_factory=dict)
    start: bool = False
    panel_only: bool = False


def device_controls(device: Device, *, appliance: bool) -> list[Control]:
    if device.substrate != "virtual":
        return []
    commands = set(device.commands)
    controls = []
    if "color_temp" in commands:
        controls.extend(
            Control(
                f"kelvin_{kelvin}", f"{kelvin}K로 변경", {"color": {"kelvin": kelvin}}
            )
            for kelvin in (2700, 4000, 6500)
        )
    if "play_mood" in commands:
        controls.extend(
            Control(scene, f"{label} 켜기", {"play_mood": {"scene": scene}})
            for scene, label in SCENES.items()
        )
    if "off" in commands and device.device_type == "display":
        controls.append(Control("display_off", "끄기", {"play_mood": None}))
    if "off" in commands or device.device_type == "light":
        controls.extend(
            (
                Control("power_on", "켜기", {"power": True}),
                Control("power_off", "끄기", {"power": False}),
            )
        )
    if "child_lock" in commands:
        controls.extend(
            (
                Control("lock", "잠그기", {"child_lock": True}),
                Control("unlock", "잠금 해제", {"child_lock": False}),
            )
        )
    if "clean" in commands:
        controls.extend(
            (
                Control(
                    "clean",
                    "청소 시작",
                    {"clean": {"room": ROOM_NAMES.get(device.room, device.room)}},
                ),
                Control("stop_clean", "청소 중지", {"clean": None}),
            )
        )
    if "play" in commands:
        controls.append(
            Control(
                "play",
                "가족 모임 음악 재생",
                {"play": {"playlist": "family", "volume": 30}},
            )
        )
    if "stop" in commands:
        controls.append(Control("stop", "음악 정지", {"play": None}))
    if (
        device.device_type == "oven"
        and device.job
        and device.job.trigger_property is None
    ):
        controls.append(Control("start", "굽기 시작", start=True))
    if device.device_type == "fridge":
        controls.append(
            Control("open_door", "문 열기", {"door_open": True}, panel_only=True)
        )
    return [
        control
        for control in controls
        if not (appliance and control.panel_only)
        and all(
            key in device.properties
            and device.properties[key].local_write
            and device.properties[key].accepts(value)
            for key, value in control.values.items()
        )
    ]
