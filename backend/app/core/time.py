from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FrozenClock:
    instant: datetime

    def __post_init__(self) -> None:
        to_utc(self.instant)

    def now(self) -> datetime:
        return to_utc(self.instant)


class LocalTimeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def to_utc(instant: datetime) -> datetime:
    if instant.utcoffset() is None:
        raise ValueError("Момент времени должен содержать часовой пояс")
    return instant.astimezone(UTC)


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Укажите существующий часовой пояс IANA") from exc


def local_time_candidates(local: datetime, tz: ZoneInfo) -> tuple[datetime, ...]:
    """Return distinct, valid UTC instants for a naive wall-clock reading."""
    if local.tzinfo is not None:
        raise ValueError("Локальное время должно быть без часового пояса")
    candidates = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if instant.astimezone(tz).replace(tzinfo=None) == local:
            candidates.add(instant)
    return tuple(sorted(candidates))


def local_to_utc(local: datetime, tz: ZoneInfo) -> datetime:
    candidates = local_time_candidates(local, tz)
    if not candidates:
        raise LocalTimeError(
            "LOCAL_TIME_NONEXISTENT", "Указанное время отсутствует из-за смены часового пояса"
        )
    if len(candidates) > 1:
        raise LocalTimeError(
            "LOCAL_TIME_AMBIGUOUS", "Указанное время повторяется из-за смены часового пояса"
        )
    return candidates[0]


def _day_boundary(day: date, tz: ZoneInfo) -> datetime:
    midnight = datetime.combine(day, time.min)
    candidates = local_time_candidates(midnight, tz)
    if candidates:
        return candidates[0]

    # An imaginary midnight lies inside a forward clock jump. Its two fold
    # interpretations bracket the transition, including whole skipped dates.
    bounds = sorted(midnight.replace(tzinfo=tz, fold=f).astimezone(UTC) for f in (0, 1))
    low, high = bounds
    tick = timedelta(microseconds=1)
    while high - low > tick:
        middle = low + (high - low) // 2
        if middle.astimezone(tz).replace(tzinfo=None) >= midnight:
            high = middle
        else:
            low = middle
    return high


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC half-open interval; its duration need not be 24 hours."""
    start = _day_boundary(day, tz)
    if start.astimezone(tz).date() != day:
        raise LocalTimeError("LOCAL_DATE_NONEXISTENT", "Указанная локальная дата не существует")
    end = _day_boundary(day + timedelta(days=1), tz)
    return start, end
