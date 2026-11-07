import re
from datetime import date
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from app.modules.biorhythm.types import ForecastPeriod, Step


def _local_date(value: Any) -> Any:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Укажите локальную дату в формате YYYY-MM-DD")
    return value


LocalDate = Annotated[date, BeforeValidator(_local_date)]


class SnapshotQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: AwareDatetime | None = Field(
        default=None, description="Момент с UTC-смещением; по умолчанию текущее время"
    )


class CriticalDaysQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: LocalDate = Field(alias="from", description="Первая локальная дата включительно")
    end: LocalDate = Field(alias="to", description="Последняя локальная дата включительно")


class SeriesQuery(CriticalDaysQuery):
    step: Step = Field(default=Step.DAY, description="hour — каждый час; day — локальный полдень")


class ForecastQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: ForecastPeriod
