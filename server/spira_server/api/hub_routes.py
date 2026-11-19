"""Hub routes (contracts/openapi/hub.yaml). This batch: device list, plan pull and ack.
Events and execution results come with the rest of S6.

Every route: X-API-Key -> household (401), then every household the request names must be that one (403), checked
before anything else is read or written (spec §12.1). The key dependency is declared first so a missing key is
401 before a bad body is 422."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from spira_contracts.ack import Ack
from spira_contracts.devices import Devices
from sqlalchemy import select

from .. import clock
from ..db.engine import lock_household, session_scope
from ..db.models import DeviceList, Episode, Household
from ..pipeline import s5_plan
from .auth import require_hub, same_household
from .bodies import body
from .errors import ApiError

router = APIRouter()

HOUSEHOLD = r"^h_[0-9a-z]+$"
EPISODE = r"^ep_[0-9a-z]+$"


@router.put("/v1/hub/households/{household_id}/devices")
def put_devices(key: str = Depends(require_hub), household_id: str = Path(pattern=HOUSEHOLD),
                data: dict = body(Devices, "devices.json")) -> dict:
    same_household(key, household_id)
    same_household(key, data["household_id"])
    ids = [d["id"] for d in data["devices"]]
    for i, d in enumerate(ids):
        if d in ids[:i]:
            raise ApiError("validation_error", f"Device id {d} appears twice.", {"path": f"devices[{i}].id"})
    with session_scope() as s:
        lock_household(s, household_id)
        stored = s.get(DeviceList, household_id)
        if stored is not None and data["revision"] < stored.revision:
            raise ApiError("stale_revision", f"Stored revision is {stored.revision}.",
                           {"revision": stored.revision})
        if stored is not None and data["revision"] == stored.revision:
            return {"revision": stored.revision}                       # same revision: no change
        if stored is None:
            s.add(DeviceList(household_id=household_id, revision=data["revision"], body=data,
                             updated_at=clock.now()))
        else:                                    # published plans keep their devices_revision
            stored.revision, stored.body, stored.updated_at = data["revision"], data, clock.now()
    return {"revision": data["revision"]}


@router.get("/v1/hub/plans")
def get_plans(key: str = Depends(require_hub), household: str = Query(pattern=HOUSEHOLD)) -> dict:
    same_household(key, household)
    with session_scope() as s:
        h = s.get(Household, household)
        dl = s.get(DeviceList, household)
        return {"household_id": household, "paused": bool(h.paused), "devices_revision": dl.revision if dl else 0,
                "plans": s5_plan.pulled_plans(s, household)}


@router.post("/v1/hub/plans/{plan_id}/ack", status_code=204)
def post_ack(key: str = Depends(require_hub), plan_id: str = Path(pattern=EPISODE),
             data: dict = body(Ack, "ack.json")) -> Response:
    with session_scope() as s:
        owner = s.execute(select(Episode.household_id).where(Episode.id == plan_id)).scalar_one_or_none()
    if owner is None:
        raise ApiError("not_found", "Unknown plan.")
    same_household(key, owner)
    try:
        s5_plan.apply_ack(plan_id, data)
    except s5_plan.AckError as e:
        raise ApiError("validation_error", str(e), {"path": e.path}) from None
    except LookupError:
        raise ApiError("not_found", "Unknown plan version.") from None
    return Response(status_code=204)
