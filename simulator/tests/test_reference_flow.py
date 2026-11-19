from conftest import LIGHT, OVEN, fixture_json
from spira_contracts.plan import Plan


def test_fixture_birthday_effects_and_conditional_restore(world, wire, clock):
    """Drive the World with the fixture's actions without simulating Hub policy."""
    plan = Plan.model_validate(fixture_json("ep_9031/plan.v3.json"))
    tasks = {task.task_id: task for task in plan.tasks}
    display = "mqtt:display_01"
    fridge = "mqtt:fridge_01"
    mood_task = tasks["t_mood#3"]
    display_action, light_action = mood_task.actions
    (set_oven,) = tasks["t_oven#4"].actions
    initial_light = wire.read(LIGHT)
    initial_display = wire.read(display)

    wire.protocol.dispatch(world.home_event, "delivery")
    assert wire.frames[-1][1]["event_type"] == "camera.package_removed"
    for ident in ("t_fridge#5", "t_fridge#6"):
        (notice,) = tasks[ident].actions
        receipt, _ = wire.command(fridge, {"show_notice": notice.value})
        assert receipt["status"] == "ACCEPTED"
        assert wire.read(fridge)["values"]["show_notice"] == notice.value
    (door,) = world.local_change(fridge, "resident", {"door_open": True})
    assert door["event_type"] == "fridge.door_opened"

    assert wire.read(LIGHT)["values"] == initial_light["values"]
    assert wire.read(display)["values"] == initial_display["values"]
    wire.protocol.dispatch(world.home_event, "guests_arrive")
    assert [body["event_type"] for _, body, _, _ in wire.frames[-3:]] == [
        "doorbell.pressed",
        "door_lock.opened",
        "presence.room_occupied",
    ]
    # These dispatches represent messages from a peer. The fixture's trigger policy belongs to Hub.
    for action in mood_task.actions:
        receipt, _ = wire.command(f"mqtt:{action.device}", {action.cmd: action.value})
        assert receipt["status"] == "ACCEPTED"
    prepared_light = wire.read(LIGHT)
    prepared_display = wire.read(display)
    assert prepared_light["values"]["color"] == light_action.value
    assert prepared_display["values"]["play_mood"] == display_action.value

    wire.command(OVEN, {"preset": set_oven.value})
    clock.advance()
    (started,) = world.local_change(OVEN, "guest", {}, start=True)
    (changed,) = world.local_change(LIGHT, "resident", {"color": {"kelvin": 2700}})
    assert started["local_operation"] and changed["local_operation"]
    assert started["operation_id"] is None and changed["operation_id"] is None

    wire.protocol.dispatch(world.home_event, "event_end")
    assert wire.frames[-1][1]["event_type"] == "presence.room_empty"
    light_restore, _ = wire.command(
        LIGHT,
        {"color": initial_light["values"]["color"]},
        expected={"color": prepared_light["revisions"]["color"]},
    )
    display_restore, _ = wire.command(
        display,
        {"play_mood": initial_display["values"]["play_mood"]},
        expected={"play_mood": prepared_display["revisions"]["play_mood"]},
    )
    assert light_restore["status"] == "CONFLICT"
    assert display_restore["status"] == "ACCEPTED"
    assert wire.read(LIGHT)["values"]["color"] == {"kelvin": 2700}
    assert wire.read(display)["values"]["play_mood"] is None
    assert wire.read(OVEN)["job_id"] == started["job_id"]
