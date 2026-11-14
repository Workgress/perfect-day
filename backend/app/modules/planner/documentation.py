"""Portable rules and approved onboarding examples, shared with the fixture exporter."""

from typing import Any

from app.modules.biorhythm.config import ALGORITHM_VERSION as BIO_VERSION
from app.modules.biorhythm.config import PERIODS, PHASE_BOUNDARIES
from app.modules.planner import config


def rules() -> dict[str, Any]:
    return {
        "algorithm_version": config.ALGORITHM_VERSION,
        "biorhythm_version": BIO_VERSION,
        "time": {
            "birth_scale": "UTC; unknown birth time is 12:00 UTC",
            "intervals": "half-open UTC",
            "local_day": "IANA zone; DST may give 23/25 hours",
            "grid_step_minutes": config.GRID_STEP_MINUTES,
            "grid_anchor": "local work_start; ceil now in elapsed UTC time",
            "duration": "exact elapsed minutes; whole tasks only",
        },
        "energy": {
            "period_days": {key.value: value for key, value in PERIODS.items()},
            "phase_boundaries": list(PHASE_BOUNDARIES),
            "profile_hours": list(config.PROFILE_HOURS),
            "profiles": {
                key.value: list(value) for key, value in config.CIRCADIAN_PROFILES.items()
            },
            "chronotype_shift_hours": dict(config.CHRONOTYPE_SHIFT_HOURS),
            "formula": "duration-weighted mean(c_T(local_hour - shift) * "
            "(0.75 + 0.25 * sin(2*pi*t/P)))",
            "samples": "15-minute midpoint pieces, exact shorter last piece; UTC elapsed time",
            "routine": "mean(1 - max(physical_score, emotional_score, intellectual_score))",
            "peak_window_threshold": config.PEAK_WINDOW_THRESHOLD,
            "preferred_start_bonus": config.PREFERRED_START_BONUS,
            "preferred_tolerance_minutes": config.PREFERRED_START_TOLERANCE_MINUTES,
        },
        "selection": {
            "sort": [
                "priority ascending rank",
                "intensity descending",
                "duration descending",
                "created_at ascending",
                "UUID/index ascending",
            ],
            "priority_rank": dict(config.PRIORITY_ORDER),
            "intensity_rank": dict(config.TASK_INTENSITY),
            "same_kind_neighbor_penalty": config.SAME_KIND_PENALTY,
            "tie": "strictly greater score replaces best; exact tie keeps earliest UTC start; "
            "no rounding before selection",
            "optimality": "deterministic greedy, not a global optimum",
        },
        "constraints": {
            "high_intensity_types": sorted(config.HIGH_INTENSITY_KINDS),
            "high_intensity_cap_minutes": config.HIGH_INTENSITY_CAP_MINUTES,
            "intensity_gap_minutes": config.INTENSITY_GAP_MINUTES,
            "short_continuous_limit_minutes": config.CONTINUOUS_SHORT_LIMIT_MINUTES,
            "long_continuous_limit_minutes": config.CONTINUOUS_LONG_LIMIT_MINUTES,
            "short_break_minutes": config.SHORT_BREAK_MINUTES,
            "long_break_minutes": config.LONG_BREAK_MINUTES,
            "break_rule": "maximum applicable break, not sum; lunch/rest can fulfill it",
            "deadline": "inclusive local calendar date -> exclusive next local midnight",
        },
        "load": {
            "critical_factors": [1, 0.8, 0.65, 0.5],
            "any_minimum_multiplier": 0.9,
            "phase_reference": "local noon; earlier occurrence if repeated",
            "capacity": "floor((elapsed work minutes - union of system intervals) * load_factor)",
            "intensity_cap": "floor(240 * load_factor)",
            "overload": "planned_minutes > 0.85 * capacity, or unscheduled work",
            "mandatory_rest_minutes": 30,
            "mandatory_rest_count_by_level": [0, 0, 1, 2],
        },
        "moves": {
            "horizon_days": 7,
            "automatic_modes": ["replan"],
            "eligible": "critical source; unpinned/unstarted intellectual or physical; "
            "high priority OR duration >= 60; deadline permits",
            "target": "nearest explicitly known working noncritical day, relevant noon cycle >= 0, "
            "whole task and every resident task fit",
            "advice": "prefers confirmed cycle >= 0.5, otherwise nearest; never mutates dates",
            "unknown_day": "not assumed empty",
            "persistence": "source + accepted future_plans in one transaction",
        },
        "replan": {
            "retain": ["past", "started", "done", "current pins", "begun system intervals"],
            "boundary": "saved start == now counts as begun; end == now is past",
            "skipped": "retain elapsed history visually; exclude from load and fatigue",
            "history_edits": "missing historical snapshots or incompatible "
            "duration/start changes fail",
        },
    }


REQUEST_EXAMPLE: dict[str, Any] = {
    "planned_date": "2026-11-14",
    "tasks": [{"title": "Первые задачи", "type": "routine", "duration_min": 17}],
}
PREVIEW_EXAMPLE: dict[str, Any] = {
    "planned_date": "2026-11-14",
    "timezone": "UTC",
    "slots": [
        {
            "task_index": 0,
            "start_time": "08:00:00",
            "end_time": "08:17:00",
            "explanation": "Рутинная задача размещена в доступном рабочем окне",
        }
    ],
    "unscheduled_task_indexes": [],
}
DESCRIPTION = f"""
Версия планировщика `{config.ALGORITHM_VERSION}`. Рабочее окно и IANA-пояс берутся из
сохранённого профиля; фиксированный `wake_time` и выходной по умолчанию не запрещают явно
запрошенный текущий день. Все интервалы считаются в UTC, длительности — в реальных минутах.
Сетка 15 минут привязана к work_start, начало не раньше now; задача неделима.
Типы: intellectual/physical/creative/routine. Детерминированная жадная сортировка:
приоритет, интенсивность, длительность, время создания, ID.
Точное равенство оценки — ранний UTC старт.
Энергия — среднее по интервалу c_T * (0.75 + 0.25 * sin(2*pi*t/P)), с профилем хронотипа.
Приоритет не умножает оценку. Для рутины используется 1 - max трёх оценок.
Критические дни снижают бюджет до 80/65/50%, любой минимум дополнительно умножает на 0.9;
двойной/тройной день требует 1/2 блока отдыха по 30 минут. Бюджеты округляются вниз один раз.
Обед, перерывы и отдых исключаются из доступных интервалов. Preview/initial не переносят
первые задачи на другую дату. Персональные ответы — Cache-Control: no-store.
Preview возвращает только исходные индексы и местные HH:mm:00, без постоянных task ID.
Частичный preview — 200; та же нехватка места при complete — 409 PLAN_CAPACITY_EXCEEDED.
Каждый исходный индекс встречается ровно один раз: в slots или unscheduled_task_indexes.
Полные правила и эталоны: contracts/fixtures/planner_cases.json, проверка генератором --check.
Этот внутренний формат эталонов не является публичным CRUD-контрактом.
""".strip()
