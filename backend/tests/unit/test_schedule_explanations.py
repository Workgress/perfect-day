from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest

from app.modules.biorhythm.engine import percent
from app.modules.planner.contracts import Interval, PlanSlot, UnscheduledTask
from app.modules.planner.energy import score_interval
from app.modules.planner.engine import build_schedule
from app.modules.schedule.explanations import schedule_explanations
from tests.unit.test_planner_policy import DAY, at, context, task


def test_explanation_contains_actual_cycle_profile_preference_duration_and_deadline() -> None:
    item = task(duration=30, preferred_start=time(10), deadline=at(17))
    ctx = context(item)
    result = build_schedule(ctx)
    saved = next(slot for slot in result.slots if slot.task == item.ref)
    rating = score_interval(ctx.profile, item, saved.interval)
    assert rating.cycle_mean is not None and rating.circadian_mean is not None
    text = saved.explanation or ""
    assert f"{percent(rating.cycle_mean):g}%" in text
    assert f"{rating.circadian_mean * 100:.1f}%" in text
    assert "хронотип: голубь" in text
    assert "Предпочтительное начало: 10:00" in text
    assert "Длительность: 30 мин" in text
    assert "Дедлайн: 14.11.2026 17:00 +0000" in text
    exposed = schedule_explanations(result).placement_explanations[0]
    assert exposed.task_id == item.ref.task_id and exposed.explanation == saved.explanation


def test_preference_outside_work_window_is_not_claimed_as_satisfied() -> None:
    item = task(preferred_start=time(23))
    saved = next(slot for slot in build_schedule(context(item)).slots if slot.task == item.ref)
    assert "PREFERRED_TIME" not in saved.reason_codes
    assert "Предпочтительное начало" not in (saved.explanation or "")


@pytest.mark.parametrize("preservation", ["pinned", "started", "past", "done"])
def test_preservation_is_the_displayed_reason_without_rewriting_saved_energy_metadata(
    preservation: str,
) -> None:
    item = task()
    original = build_schedule(context(item))
    saved = next(slot for slot in original.slots if slot.task == item.ref)
    protected = replace(saved, preservation=preservation)
    result = replace(original, slots=(protected,))
    exposed = schedule_explanations(result).placement_explanations[0]
    expected = {
        "pinned": "PINNED_BY_USER",
        "started": "TASK_STARTED",
        "past": "PAST_INTERVAL_PRESERVED",
        "done": "TASK_COMPLETED",
    }
    assert exposed.reason_codes == (expected[preservation],)
    assert exposed.preservation == preservation
    assert "энергии" not in exposed.explanation and "фазе пика" not in exposed.explanation
    assert exposed.start_at == saved.interval.start and exposed.end_at == saved.interval.end
    assert result.slots[0].explanation == saved.explanation
    assert result.slots[0].reason_codes == saved.reason_codes


def test_unplaced_text_uses_actual_intensity_limit_and_date_policy() -> None:
    item = task(duration=180)
    result = build_schedule(context(item, elapsed=14, allow_date_change=False))
    saved = result.unscheduled[0]
    assert "INTENSITY_CAPACITY_EXCEEDED" in saved.reason_codes
    assert "Нужен непрерывный интервал 180 мин" in (saved.explanation or "")
    text = schedule_explanations(result).unscheduled_explanations[0].explanation
    assert "лимит интенсивной работы" in text and "Перенос даты запрещён" in text
    assert DAY.isoformat() in text
    assert "биоритм" not in text and "пик" not in text


@pytest.mark.parametrize("text", [None, "", "   "])
def test_legacy_slot_without_text_gets_a_factual_fallback_without_invented_energy(
    text: str | None,
) -> None:
    item = task()
    plan = build_schedule(context(item))
    saved = next(slot for slot in plan.slots if slot.task == item.ref)
    plan = replace(plan, slots=(replace(saved, explanation=text, reason_codes=()),))
    exposed = schedule_explanations(plan).placement_explanations[0]
    assert exposed.reason_codes == ("SAVED_PLACEMENT",)
    assert "подробная причина выбора недоступна" in exposed.explanation
    assert "Длительность: 60 мин" in exposed.explanation
    assert "%" not in exposed.explanation


def test_legacy_unplaced_reasons_are_explained_without_recomputing_a_plan() -> None:
    item = task()
    plan = build_schedule(context(item))
    plan = replace(
        plan,
        slots=(),
        unscheduled=(UnscheduledTask(item.ref, ("NO_FEASIBLE_INTERVAL", "DEADLINE_EXCEEDED")),),
    )
    exposed = schedule_explanations(plan).unscheduled_explanations[0]
    assert "позже дедлайна" in exposed.explanation
    assert "лимит интенсивной" not in exposed.explanation


def test_legacy_dst_fold_explanation_preserves_offsets_and_real_duration() -> None:
    item = task()
    plan = build_schedule(context(item))
    interval = Interval(
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    )
    plan = replace(
        plan,
        day=date(2026, 10, 25),
        timezone="Europe/Berlin",
        slots=(PlanSlot("task", interval, item.ref),),
    )
    text = schedule_explanations(plan).placement_explanations[0].explanation
    assert "02:30 +0200–02:30 +0100" in text and "60 мин" in text
