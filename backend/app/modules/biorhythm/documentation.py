from app.modules.biorhythm.config import ALGORITHM_VERSION

CALCULATION_DESCRIPTION = f"""
Расчёт трёх циклов на переданный `at` или текущий момент сервера.
Требует Bearer-токена подтверждённого пользователя и завершённого онбординга;
иначе `401 AUTHENTICATION_REQUIRED`, `403 EMAIL_NOT_VERIFIED` или `409 ONBOARDING_REQUIRED`.

Версия алгоритма: `{ALGORITHM_VERSION}`. Формула: `value = sin(2*pi*t/P)`,
где `t` — фактически прошедшие UTC-секунды с вычислительного рождения / 86400,
а `P` — 23 (physical), 28 (emotional), 33 (intellectual) суток.
Дата и время рождения трактуются в фиксированной шкале UTC; неизвестное время — 12:00 UTC.
Текущий IANA-пояс пользователя влияет на локальный день, но не на вычислительный момент рождения.

`at` — ISO 8601 с UTC-смещением. Числовой Unix timestamp не принимается.
В query знак `+` в смещении кодируется как `%2B`.
Ответные моменты — UTC с `Z`, `date` — локальная дата пользователя.
Запрос момента до рождения возвращает `422 VALIDATION_ERROR`.

`value` лежит в [-1, 1]. Границы -1, -0.5, 0, 0.5, 1 нормализуются с допуском 1e-12.
Фаза определяется до округления: peak [0.5, 1], rising [0, 0.5),
declining (-0.5, 0), minimum [-1, -0.5].
`percent = roundTiesToEven(value*1000)/10`, один знак после запятой, без отрицательного нуля.
`trend` определяется знаком производной; точно на максимуме — down, на минимуме — up
(допуск для косинуса 1e-12). Фаза и направление независимы.

Критический день содержит аналитические пересечения нуля `birth_utc + k*P/2 суток`
в полуинтервале [начало локального дня, начало следующего дня).
`level` — число разных циклов с пересечением, `kind` — none/single/double/triple;
пересечения отсортированы по UTC-моменту, затем physical/emotional/intellectual.
Событие на следующей полуночи относится только к следующему дню.

Персональные HTTP-ответы: `Cache-Control: no-store`. Внутренний Redis-кэш — 86400 секунд;
при его недоступности расчёт выполняется локально.
Эталонные данные: `contracts/fixtures/biorhythm_vectors.json`;
примеры шести маршрутов: `contracts/fixtures/biorhythm_api_examples.json`.
""".strip()

ZERO_SNAPSHOT_EXAMPLE = {
    "algorithm_version": ALGORITHM_VERSION,
    "timezone": "UTC",
    "at": "2000-01-01T00:00:00Z",
    "date": "2000-01-01",
    "cycles": {
        cycle: {"value": 0.0, "percent": 0.0, "phase": "rising", "trend": "up"}
        for cycle in ("physical", "emotional", "intellectual")
    },
    "critical": {
        "level": 3,
        "kind": "triple",
        "crossings": [
            {"cycle": cycle, "at": "2000-01-01T00:00:00Z"}
            for cycle in ("physical", "emotional", "intellectual")
        ],
    },
}
