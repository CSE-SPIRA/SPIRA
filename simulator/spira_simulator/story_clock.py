"""Calculate story time from the demo clock's anchors."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ClockState(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    version: int = Field(ge=0)
    real_at: AwareDatetime
    story_at: AwareDatetime
    rate: float = Field(gt=0)
    ramp_until: AwareDatetime | None


def story_now(state: ClockState, real_now: datetime) -> datetime:
    if state.ramp_until is not None and real_now > state.ramp_until:
        reached = state.story_at + (state.ramp_until - state.real_at) * state.rate
        return reached + (real_now - state.ramp_until)
    return state.story_at + (real_now - state.real_at) * state.rate
