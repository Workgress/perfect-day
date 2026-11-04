# Проверка этапа 2: хранение и функции безопасности

## Что готово

- Миграция `0005` поверх `0004`: `sessions`, `refresh_tokens`, `email_tokens` и enum назначения email-токена.
- Модели `AuthSession`, `RefreshToken`, `EmailToken` в `app/modules/auth/models.py`, зарегистрированные в metadata Alembic.
- Постоянный UUID сессии, история refresh, только SHA-256 токенов в БД, уникальность хэшей, один неиспользованный refresh на сессию, ограничения времени и каскадное удаление.
- `validate_password`, async `hash_password` и `verify_password` в `app/core/security.py`: Argon2, 8–128 символов, буква и цифра, без изменения исходного пароля. Дорогие операции выполняются в thread pool.
- `generate_token` создаёт непрозрачный случайный токен из 32 случайных байтов. `hash_token` возвращает SHA-256.
- `create_access_token` и `decode_access_token`: HS256, обязательные UUID `sub` и `sid`, целочисленные `iat` и `exp`. По умолчанию access действует 15 минут.
- Настройки секретного ключа и сроков действия; зависимости PyJWT и `pwdlib[argon2]` зафиксированы в `uv.lock`.

JWT-проверка на этом этапе подтверждает подпись и claims, но ещё не проверяет наличие пользователя и активность сессии в БД. Эту проверку добавит `get_current_user` на этапе 4. Регистрация, отправка писем и работающая ротация refresh пока не реализованы. В `/docs` ещё нет маршрутов auth.

Профиль, расчёты биоритмов и их Redis-кэш не изменялись. Второму бэкендеру нужно учитывать новую head `0005` и пользоваться существующим `User`; отдельные модели пользователя или собственную JWT-проверку создавать не нужно.

## Настройки

После обновления исходников установите зависимости из `backend`: `uv sync --frozen`. Команды ниже рассчитаны на PowerShell и существующее локальное `.venv`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `JWT_SECRET` | отсутствует | Секрет HS256, минимум 32 символа |
| `ACCESS_TTL_MIN` | 15 | Срок access в минутах |
| `REFRESH_TTL_DAYS` | 30 | Абсолютный срок сессии в днях |
| `EMAIL_VERIFICATION_TTL_HOURS` | 24 | Срок подтверждения email в часах |
| `PASSWORD_RESET_TTL_MIN` | 60 | Срок сброса пароля в минутах |

Все TTL должны быть положительными. `JWT_SECRET` обязателен при `ENV=staging` или `ENV=production`. Локально health и тесты можно запускать без секрета, но функции создания и проверки JWT без него завершатся ошибкой конфигурации. Встроенного рабочего секрета нет. Секрет скрыт в строковом представлении настроек и не выводится в текстах ошибок их валидации.

Для локальной ручной проверки создайте секрет в окружении текущего терминала:

```powershell
cd "D:\Project Workgress\perfect-day\backend"
$env:DEBUG = "false"
$env:JWT_SECRET = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Для сохранения между запусками используйте собственный секрет в локальном `.env`. Не добавляйте `.env` в Git. Не меняйте секрет между запросами одной сессии: изменение ключа делает ранее выданные JWT недействительными.

## Проверка без Docker

```powershell
cd "D:\Project Workgress\perfect-day\backend"
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest tests/auth -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m alembic heads
```

Ожидается успешный прогон тестов и единственная head `0005`. Тесты используют собственный тестовый секрет, а не рабочие ключи.

Проверяются пароли и разные соли, неверный пароль, повреждённые хэши, выполнение вне event loop, генерация и хэширование непрозрачных токенов, корректный JWT и TTL, просроченные и будущие токены, неверная подпись, изменение payload, запрещённый алгоритм, отсутствие claims и некорректные UUID.

Простой ручной JWT round trip после задания `JWT_SECRET`:

```powershell
.\.venv\Scripts\python.exe -c "from uuid import uuid4; from app.core.security import create_access_token, decode_access_token; user_id, session_id = uuid4(), uuid4(); claims = decode_access_token(create_access_token(user_id, session_id)); assert claims.sub == user_id and claims.sid == session_id; print('JWT OK')"
```

## Проверка на одноразовой PostgreSQL

Запустите Docker Desktop. Тесты сами создают отдельные контейнеры PostgreSQL и Redis; рабочая БД проекта не используется.

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest tests/db/test_auth.py tests/db/test_migrations.py -q -p no:cacheprovider
```

Проверяются ограничения новых таблиц, одна действующая запись refresh на сессию, сохранение истории и ID устройства при записи ротации, уникальность хэшей и каскады. Проверка ротации здесь относится к хранению данных; HTTP-сценарий и обнаружение повтора будут реализованы на этапе 4.

Миграционные тесты проверяют полную цепочку upgrade/downgrade/upgrade, соответствие схемы ORM и откат `0005 → 0004 → 0005` с сохранением существующей учётной записи. Откаты выполняются исключительно в одноразовом контейнере тестов.

Полный прогон:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check app tests
.\.venv\Scripts\python.exe -m mypy app
```

## Применение к локальной БД разработки

Следующие команды применяют новую миграцию к БД из вашего `DATABASE_URL`. Из `backend`, после установки зависимостей и с корректным локальным `.env`:

```powershell
$env:DEBUG = "false"
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Ожидаются ревизия `0005 (head)` и отсутствие новых операций в `alembic check`. Откат на рабочей БД для проверки не нужен; обратимость уже проверяется тестами в отдельном контейнере.
