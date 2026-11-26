"""Calculate story time from the demo clock's anchors."""

from datetime import datetime, timedelta

from pydantic import Field

from hub.spira_hub.story_clock import ClockState as HubClockState
from hub.spira_hub.story_clock import story_now


class ClockState(HubClockState):
    rate: float = Field(ge=0)


class StoryClock:
    def __init__(self, real_now: datetime):
        self.state = ClockState(version=1, real_at=real_now, story_at=real_now, rate=1, ramp_until=None)

    def set(self, target: datetime, real_now: datetime):
        self.state = ClockState(
            version=self.state.version + 1, real_at=real_now, story_at=target, rate=1, ramp_until=None,
        )

    def set_rate(self, rate: float, real_now: datetime):
        self.state = ClockState(
            version=self.state.version + 1, real_at=real_now,
            story_at=story_now(self.state, real_now), rate=rate, ramp_until=None,
        )

    def rate_at(self, real_now: datetime):
        if self.state.ramp_until is not None and real_now >= self.state.ramp_until:
            return 1.0
        return self.state.rate

    def pause(self, real_now: datetime):
        if self.state.rate:
            self.resume_rate = 1 if self.state.ramp_until else self.state.rate
            self.set_rate(0, real_now)

    def resume(self, real_now: datetime):
        if not self.state.rate:
            self.set_rate(self.resume_rate, real_now)

    def seconds_until(self, target: datetime, real_now: datetime):
        gap = (target - story_now(self.state, real_now)).total_seconds()
        if gap <= 0:
            return 0.0
        rate = self.rate_at(real_now)
        if not rate:
            return None
        ramp = self.state.ramp_until
        if ramp and ramp > real_now:
            remaining = (ramp - real_now).total_seconds()
            if gap > remaining * rate:
                return remaining + gap - remaining * rate
        return gap / rate

    def advance(self, target: datetime, real_now: datetime, over_seconds: float):
        current = story_now(self.state, real_now)
        if target <= current:
            raise ValueError("The target must be after story time")
        self.state = ClockState(
            version=self.state.version + 1, real_at=real_now, story_at=current,
            rate=(target - current).total_seconds() / over_seconds,
            ramp_until=real_now + timedelta(seconds=over_seconds),
        )
