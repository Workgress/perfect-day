from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock, local_day_bounds, parse_timezone, to_utc
from app.modules.biorhythm import engine
from app.modules.biorhythm.cache import BiorhythmCache, CacheParameters, build_cache_key
from app.modules.biorhythm.config import ALGORITHM_VERSION
from app.modules.biorhythm.types import (
    BiorhythmSnapshot,
    CriticalDay,
    CriticalDays,
    Forecast,
    ForecastPeriod,
    Step,
)
from app.modules.users.schemas import ProfileResponse
from app.modules.users.service import ProfileService

SNAPSHOT_ADAPTER = TypeAdapter(BiorhythmSnapshot)
FORECAST_ADAPTER = TypeAdapter(Forecast)
CRITICAL_DAYS_ADAPTER = TypeAdapter(CriticalDays)


class OnboardingRequiredError(ValueError):
    code = "ONBOARDING_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Сначала завершите настройку профиля")


def _utc_key(at: datetime) -> str:
    return to_utc(at).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class _Context:
    user_id: UUID
    birth_utc: datetime
    tz: ZoneInfo
    birth_data: CacheParameters


def _birth_data(profile: ProfileResponse, birth_utc: datetime) -> CacheParameters:
    return {
        "birth_date": profile.birth_date.isoformat() if profile.birth_date is not None else None,
        "birth_time": profile.birth_time.isoformat() if profile.birth_time is not None else None,
        "birth_time_known": profile.birth_time_known,
        "birth_tz": profile.birth_tz,
        "birth_at_utc": _utc_key(birth_utc),
    }


def _range_days(start: date, end: date) -> int:
    if (
        not isinstance(start, date)
        or isinstance(start, datetime)
        or not isinstance(end, date)
        or isinstance(end, datetime)
    ):
        raise engine.ForecastValidationError(
            "range", "INVALID_DATE", "Укажите локальные даты без времени"
        )
    return (end - start).days + 1


def _check_birth(at: datetime, birth_utc: datetime, field: str) -> None:
    if at < birth_utc:
        raise engine.ForecastValidationError(
            field, "BEFORE_BIRTH", "Нельзя запрашивать значения до момента рождения"
        )


class BiorhythmService:
    """Read-only use cases. user_id must come from the authenticated caller."""

    def __init__(self, session: AsyncSession, cache: BiorhythmCache, clock: Clock) -> None:
        self.profiles = ProfileService(session, clock)
        self.cache = cache
        self.clock = clock

    async def _context(self, user_id: UUID) -> _Context:
        profile = await self.profiles.get_profile(user_id)
        if (
            profile is None
            or profile.onboarding_completed_at is None
            or profile.birth_at_utc is None
        ):
            raise OnboardingRequiredError()
        birth_utc = to_utc(profile.birth_at_utc)
        return _Context(
            user_id, birth_utc, parse_timezone(profile.timezone), _birth_data(profile, birth_utc)
        )

    def _key(self, context: _Context, request: CacheParameters) -> str:
        return build_cache_key(
            context.user_id, context.birth_data, context.tz.key, request, prefix=self.cache.prefix
        )

    async def get_snapshot(self, user_id: UUID, at: datetime | None = None) -> BiorhythmSnapshot:
        context = await self._context(user_id)
        at_utc = to_utc(self.clock.now() if at is None else at)
        _check_birth(at_utc, context.birth_utc, "at")
        day = at_utc.astimezone(context.tz).date()
        # Resolve calendar validity before any cache access.
        local_day_bounds(day, context.tz)
        key = self._key(context, {"kind": "snapshot", "at": _utc_key(at_utc)})

        def calculate() -> BiorhythmSnapshot:
            state = engine.snapshot(context.birth_utc, at_utc)
            return BiorhythmSnapshot(
                algorithm_version=ALGORITHM_VERSION,
                timezone=context.tz.key,
                at=state.at,
                date=day,
                cycles=state.cycles,
                critical=engine.critical_info(context.birth_utc, day, context.tz),
            )

        return await self.cache.get_or_compute(key, SNAPSHOT_ADAPTER, calculate)

    async def get_series(
        self, user_id: UUID, start: date, end: date, step: Step = Step.DAY
    ) -> Forecast:
        context = await self._context(user_id)
        days = _range_days(start, end)
        moments = engine.time_grid(start, days, context.tz, step)
        _check_birth(moments[0], context.birth_utc, "from")
        key = self._key(
            context,
            {
                "kind": "series",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "step": Step(step).value,
            },
        )
        return await self.cache.get_or_compute(
            key,
            FORECAST_ADAPTER,
            lambda: engine.forecast(context.birth_utc, start, days, context.tz, step),
        )

    async def get_forecast(self, user_id: UUID, period: ForecastPeriod) -> Forecast:
        context = await self._context(user_id)
        params = engine.forecast_range(self.clock.now(), period, context.tz)
        moments = engine.time_grid(params.start, params.days, context.tz, params.step)
        _check_birth(moments[0], context.birth_utc, "from")
        end = params.start + timedelta(days=params.days - 1)
        key = self._key(
            context,
            {
                "kind": "forecast",
                "period": params.period.value,
                "from": params.start.isoformat(),
                "to": end.isoformat(),
                "step": params.step.value,
            },
        )
        return await self.cache.get_or_compute(
            key,
            FORECAST_ADAPTER,
            lambda: replace(
                engine.forecast(
                    context.birth_utc, params.start, params.days, context.tz, params.step
                ),
                period=params.period,
            ),
        )

    async def get_critical_days(self, user_id: UUID, start: date, end: date) -> CriticalDays:
        context = await self._context(user_id)
        days = _range_days(start, end)
        moments = engine.time_grid(start, days, context.tz, Step.HOUR)
        _check_birth(moments[0], context.birth_utc, "from")
        key = self._key(
            context,
            {
                "kind": "critical_days",
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )

        def calculate() -> CriticalDays:
            critical_days = []
            for offset in range(days):
                day = start + timedelta(days=offset)
                critical = engine.critical_info(context.birth_utc, day, context.tz)
                if critical.level:
                    critical_days.append(
                        CriticalDay(day, critical.level, critical.kind, critical.crossings)
                    )
            return CriticalDays(ALGORITHM_VERSION, context.tz.key, start, end, tuple(critical_days))

        return await self.cache.get_or_compute(key, CRITICAL_DAYS_ADAPTER, calculate)
