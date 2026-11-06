# Контракт аутентификации

Статус: завершены этапы 1–6 из 6. Доступны регистрация, подтверждение email, вход, ротация refresh, выход, список и отзыв сессий, восстановление и смена пароля. Общая зависимость `get_current_user` готова для профиля и биоритмов. Истёкшие auth-данные очищаются через Celery Beat. Подключение фронтенда и реализация профиля выполняются их владельцами.

## Ответственность двух бэкендеров

| Область | Бэкендер 1: auth | Бэкендер 2: профиль и биоритмы |
|---|---|---|
| Учётная запись | Регистрация, пароль, подтверждение email, поля безопасности существующего `User` | Использование `User.id` для доступа к своим данным |
| Профиль | Не создаёт и не изменяет профиль при регистрации | Создание и изменение `UserProfile`, `/me`, `/me/profile`, онбординг, тест хронотипа |
| Авторизация запросов | Реализация `get_current_user`, проверка access и сессии | Подключение зависимости в своих маршрутах, проверка завершённого онбординга |
| Сессии | Таблицы, ротация refresh, отзыв, список устройств | Не реализует альтернативную проверку JWT или сессий |
| Биоритмы | Не реализует | numpy, синусоиды, фазы, критические дни, соответствующие API |
| Redis | Лимиты auth с префиксом `pd:auth:` | Кэш профиля и биоритмов с отдельными префиксами |

Общие файлы конфигурации, подключения роутеров, worker, реестра моделей и зависимостей для auth меняет бэкендер 1. Бэкендер 2 добавляет свои изменения после синхронизации; пересекающиеся правки оговариваются до редактирования. Никто не очищает Redis целиком.

Текущая head миграций — `0005`, добавлены `sessions`, `refresh_tokens`, `email_tokens`. Существующие ревизии не переписываются. Последующие миграции профиля строятся поверх актуальной объединённой head. Перед объединением проверяется единственная Alembic head. Изменения ORM и их миграция входят в один PR.

## Контракт общей зависимости

Готовый публичный импорт: `from app.core.security import get_current_user`.

Сигнатура: `async def get_current_user(...) -> User`. В роутерах используется `Annotated[User, Depends(get_current_user)]`. Внутренние аргументы зависимости определяются реализацией auth; вызывающие модули их не передают. Для тестов допускается `app.dependency_overrides[get_current_user]`.

Зависимость читает только `Authorization: Bearer <access_token>`, проверяет HS256, обязательные `sub`, `sid`, `iat`, `exp`, срок JWT, пользователя и состояние сессии в PostgreSQL. Алгоритм не выбирается из непроверенного заголовка JWT. Пользователь и сессия должны соответствовать друг другу. Отозванная или истёкшая сессия немедленно делает access недействительным.

| Условие | HTTP | Код |
|---|---|---|
| Access отсутствует, некорректен или истёк | 401 | `AUTHENTICATION_REQUIRED` |
| Сессия отсутствует, истекла, отозвана или принадлежит другому пользователю | 401 | `AUTHENTICATION_REQUIRED` |
| Пользователь отсутствует, отключён или удалён | 401 | `AUTHENTICATION_REQUIRED` |
| Пользователь активен, но email не подтверждён | 403 | `EMAIL_NOT_VERIFIED` |

Ответ `401` содержит `WWW-Authenticate: Bearer`. Профиль не загружается, его наличие и завершённость онбординга не требуются. Дополнительную проверку онбординга реализует бэкендер 2: `409 ONBOARDING_REQUIRED` для функций, которым нужны данные рождения.

Второй бэкендер может подключать эту зависимость в свои роутеры. Она возвращает существующий ORM `User` без загрузки профиля, не требует Redis и завершает собственную транзакцию чтения до вызова роутера. Сервис профиля может открыть собственный `session.begin()` на той же сессии БД. Проверка онбординга остаётся у владельца профиля; auth не создаёт `/me` или эндпоинты биоритмов.

## HTTP API

Префикс `/api/v1`. Тело запроса — JSON, кроме `/auth/login`: `application/x-www-form-urlencoded`. Все даты ответов — ISO 8601 с часовым поясом UTC. Значения email валидируются, пробелы по краям удаляются; уникальность регистронезависимая благодаря существующему CITEXT. Пароли и токены не обрезаются и не нормализуются.

Пароль: 8–128 символов, минимум одна буква и одна цифра. Хэширование — Argon2 через `pwdlib`. JWT — PyJWT, HS256. Секрет берётся из окружения. Решение и схема хранения описаны в [ADR 0005](adr/0005-auth-boundaries.md).

| Метод и путь | Вход и авторизация | Успешный ответ |
|---|---|---|
| `POST /auth/register` | `{email, password}` | `202 MessageResponse`, письмо; сессия не выдаётся |
| `POST /auth/resend-verification` | `{email}` | `202 MessageResponse` |
| `POST /auth/verify-email` | `{token}` | `200 TokenResponse` и refresh-cookie |
| `POST /auth/login` | Form: `username=email`, `password`; необязательный `grant_type=password` | `200 TokenResponse` и refresh-cookie |
| `POST /auth/refresh` | Refresh-cookie, без тела и без обязательного access | `200 TokenResponse` и заменённая refresh-cookie |
| `POST /auth/logout` | Refresh-cookie; access не требуется | `204`, отзыв текущей сессии и очистка cookie |
| `POST /auth/logout-all` | Bearer access | `204`, отзыв всех сессий и очистка cookie |
| `GET /auth/sessions` | Bearer access | `200 SessionsResponse` |
| `DELETE /auth/sessions/{id}` | Bearer access, UUID сессии | `204`, отзыв своей сессии; для текущей также очистка cookie |
| `POST /auth/password/forgot` | `{email}` | `202 MessageResponse` |
| `POST /auth/password/reset` | `{token, new_password}` | `204`, смена пароля, отзыв всех сессий, очистка cookie |
| `POST /auth/password/change` | Bearer access, `{old_password, new_password}` | `204`, смена пароля, отзыв всех сессий, очистка cookie |

Все обязательные поля таблицы передаются строками. `204` не содержит тела. Нативная мобильная выдача refresh в JSON и социальный вход не входят в спринт.

Доступны все строки таблицы. Маршруты описаны в OpenAPI, защищённые маршруты используют OAuth2 Bearer. Новые миграции для этапов 3–6 не требуются; текущая head остаётся `0005`.

### Ответы

Схемы Python находятся в `app/modules/auth/schemas.py`.

`TokenResponse`:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 900
}
```

Refresh никогда не входит в JSON. Access действует 15 минут. При подтверждении email и входе создаётся отдельная сессия с абсолютным сроком 30 дней. Обновление access не продлевает сессию. Ответы с токенами получают `Cache-Control: no-store`.

`MessageResponse`:

```json
{
  "message": "Если действие доступно для указанного адреса, письмо будет отправлено"
}
```

Регистрация, resend и forgot возвращают одинаковый ответ для существующего и отсутствующего адреса. Регистрация существующего адреса не изменяет пароль и не создаёт сессию. Повторные запросы подтверждённого адреса не создают новые токены подтверждения. Forgot отправляет письмо только для активной подтверждённой учётной записи. Зависимость ответа от лимитов и технических сбоев сохраняется.

`SessionsResponse`:

```json
{
  "items": [
    {
      "id": "33fbd053-f913-413e-917a-ae31814cefa6",
      "created_at": "2026-11-04T08:00:00Z",
      "expires_at": "2026-12-04T08:00:00Z",
      "last_used_at": "2026-11-04T09:00:00Z",
      "ip": "127.0.0.1",
      "user_agent": "Mozilla/5.0",
      "is_current": true
    }
  ]
}
```

Список содержит только активные сессии пользователя, по убыванию `last_used_at`. ID устройства стабилен при ротации. IP и User-Agent могут быть `null`; они служат метаданными, а не условиями аутентификации, и обновляются при refresh. Чужая или отсутствующая сессия при адресном отзыве даёт одинаковый `404 SESSION_NOT_FOUND`. Повторный отзыв другого своего устройства допустим, пока сессия вызывающего остаётся активной. Отзыв текущего устройства делает его Bearer недействительным, поэтому повторный запрос с ним возвращает `401`.

### Ошибки auth

| Сценарий | HTTP | Код |
|---|---|---|
| Неправильный email или пароль при входе | 401 | `INVALID_CREDENTIALS` |
| Вход с правильным паролем до подтверждения email | 403 | `EMAIL_NOT_VERIFIED` |
| Повреждённый, истёкший или использованный email-токен | 400 | `INVALID_EMAIL_TOKEN` |
| Отсутствующий, истёкший, отозванный или повторный refresh | 401 | `INVALID_REFRESH_TOKEN` |
| Неверный старый пароль при смене | 400 | `INVALID_CURRENT_PASSWORD` |
| Чужая или отсутствующая сессия | 404 | `SESSION_NOT_FOUND` |
| Источник запроса не разрешён | 403 | `CSRF_ORIGIN_DENIED` |
| Ошибка входных данных | 422 | `VALIDATION_ERROR` |
| Превышение лимита | 429 | `RATE_LIMIT_EXCEEDED` |
| Недоступность обязательной инфраструктуры | 503 | `SERVICE_UNAVAILABLE` |

Сброс использует токен назначения `reset_password` со сроком один час; подтверждение — `verify_email` со сроком 24 часа. Токены одноразовые, в БД сохраняется только SHA-256. Повторная отправка аннулирует предыдущий токен того же назначения. Смена и сброс пароля отзывают все сессии; сброс также аннулирует остальные токены сброса. Повторный вход обязателен.

## Cookie, CORS и фронтенд

Имя cookie: `refresh_token`. Атрибуты: `HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`, без `Domain`. `Secure=true` на стенде и production, `false` допускается только для локального HTTP и тестов. Срок cookie равен оставшемуся абсолютному сроку сессии. Удаление использует то же имя и путь.

На этом спринте localhost используется и для фронтенда, и для API; не смешивать `localhost` и `127.0.0.1`. Будущий стенд предполагает один сайт по HTTPS, включая допустимые поддомены. CORS разрешает только точные адреса из настроек и credentials; wildcard с credentials не используется.

Для изменяющих состояние auth-запросов сервер проверяет точное совпадение Origin с настроенным списком. Если Origin отсутствует, разрешённый origin извлекается из Referer. `Origin: null`, недоверенный источник и отсутствие обоих заголовков дают `403 CSRF_ORIGIN_DENIED`. Проверка относится к register, resend, verify, login, refresh, logout и password/forgot/reset. Эндпоинты, принимающие только Bearer access, не используют cookie как замену авторизации. Ручным клиентам для указанных POST необходим доверенный Origin.

Текущий фронтенд использует демонстрационный вход. Для подключения auth фронтендеру необходимо:

1. Отправлять login как form, а остальные тела как JSON.
2. Установить `credentials: 'include'` для auth-запросов.
3. Хранить access в памяти, восстановление после перезагрузки выполнять через refresh.
4. Сериализовать refresh, включая несколько вкладок. Не повторять запросы refresh автоматически после сетевого сбоя: исходный запрос мог уже использовать токен.
5. После одного успешного refresh повторять защищённый запрос не более одного раза; неудача refresh завершает локальную сессию.
6. Для подтверждения и сброса читать токен из fragment ссылки (`#token=...`), затем передавать в тело соответствующего POST; не подтверждать email автоматически при GET ссылки.
7. Загружать профиль через `/me`, который реализует второй бэкендер; auth-ответ не содержит профиль или результат онбординга.

## Лимиты и хранение

| Действие | Лимит |
|---|---|
| Login | 5 запросов/мин на комбинацию IP + email |
| Register | 10 запросов/час на IP |
| Forgot | 3 запроса/час отдельно на IP и на email |
| Change password | 5 запросов/мин на пользователя |
| Resend | 1 запрос/60 секунд на email |
| Прочие публичные auth-маршруты | 30 запросов/мин на IP |

Лимиты применяются и к неизвестным адресам. `429` содержит `Retry-After` в секундах. Redis DB 0, префикс `pd:auth:`, TTL обязателен; адрес в ключах хэшируется. При недоступности Redis лимитируемый маршрут возвращает `503`. Другие модули не используют и не удаляют эти ключи. IP берётся из соединения; forwarded-заголовки доверяются только при настроенном доверенном reverse proxy.

Refresh-токены ротируются атомарно. Повтор старого токена отзывает всю связанную сессию. Конкурирующие refresh не создают две действующие ветки. История использованных токенов сохраняется до истечения сессии. PostgreSQL — источник истины для отзыва, Redis не кэширует положительное состояние сессии.

## Общие ошибки: доступно сейчас

`AppError` и `ErrorResponse` находятся в `app/core/errors.py`. Бизнес-модули выбрасывают `AppError(status_code, code, message, details=..., headers=...)`; `code` не ограничен auth и допускает `ONBOARDING_REQUIRED`. В details передаются только безопасные JSON-значения.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Ошибка проверки данных",
    "details": {
      "fields": [
        {
          "field": "body.password",
          "code": "string_too_short",
          "message": "Слишком короткая строка"
        }
      ]
    }
  }
}
```

Обработчики покрывают бизнес-ошибки, HTTP-исключения, 404/405, валидацию и непредвиденные исключения. Валидация не возвращает исходный ввод, тело запроса, `ctx` или внутренние тексты исключений. Неизвестные типы ошибок валидации получают русское сообщение «Некорректное значение». Для контролируемого публичного сообщения используется `AppError`; произвольный `HTTPException.detail` клиенту не передаётся.

Сохраняются служебные заголовки, включая `WWW-Authenticate`, `Allow` и `Retry-After`. Существующие успешные health/readiness-ответы сохраняют формат. `/ready` при сбое возвращает свой диагностический ответ `503` с состояниями БД и Redis, поскольку это ответ проверки готовности, а не исключение. В production `DEBUG=false`; отладочный traceback не является публичным контрактом.

OpenAPI работающего приложения описывает общий `ErrorResponse` и двенадцать реализованных auth-маршрутов. Login принимает OAuth2 form, refresh — cookie; список сессий, logout-all, адресный отзыв и смена пароля требуют Bearer.

## Передача команде и приёмка: этап 6

Backend auth готов к подключению. Текущий фронтенд содержит `demo-token` в `frontend/src/pages/login/LoginPage.tsx`; `frontend/src/stores/session.ts` сохраняет access в localStorage, а `frontend/src/shared/api/http.ts` сериализует любое тело как JSON и при `401` вызывает локальный выход. При интеграции фронтендер заменяет демонстрационный вход, исключает access из persistent-хранилища, добавляет form-login, credentials и согласованный refresh перед повтором защищённого запроса. Auth не возвращает `user` или профиль: их загрузка зависит от эндпоинтов второго бэкендера. Формат ошибок читается через `error.code`, `error.message`, `error.details`.

Второй бэкендер подключает зависимость в своих роутерах:

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.modules.users.models import User

router = APIRouter()


@router.get("/protected")
async def protected(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
    return {"user_id": str(user.id)}
```

Собственные выборки ограничиваются `user.id`; проверка онбординга остаётся в профиле. Для объединения согласуйте общие файлы `app/main.py`, `app/core/config.py`, `app/db/models.py`, `app/workers/celery_app.py`, `pyproject.toml`, `uv.lock` и Compose. Новые периодические задачи добавляются к существующему расписанию, новые модели — к общей metadata, миграции — поверх объединённой head. Модуль auth не реализует профиль, биоритмы и их Redis-кэш.

Сводная приёмка из `backend`, после `uv sync --frozen`, с работающим Docker Desktop:

```powershell
$env:DEBUG = "false"
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -ra -W error -p no:cacheprovider
docker compose config --quiet
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

Для последних двух команд нужен запущенный Compose-проект. Ожидаются `0005 (head)` и отсутствие новых операций миграции. Тесты проверяют откат и повторное применение миграций на отдельной БД, всю цепочку доставки писем, сессии, смену пароля, очистку и публичный OpenAPI-контракт, включая CORS-запросы браузера с credentials.

Запуск, сохранение JWT-секрета и адреса сервисов описаны в [README](../../README.md#запуск-backend). Перед auth-запросами дождитесь успешного `/api/v1/ready`. При локальном конфликте порта `8000` проверьте `docker ps`: OpenAPI нашего сервиса содержит `/api/v1/auth/login` и остальные маршруты auth. После закрытия терминала заново задайте `$email`, пароль, `$base` и `$headers`; email берётся из письма уже зарегистрированного аккаунта. Следующие команды после неуспешного login не выполняются, пока вход не вернул `200`.

Локальный Compose использует Mailpit и HTTP. Для стенда задаются `ENV=staging`, стабильный собственный `JWT_SECRET`, `REFRESH_COOKIE_SECURE=true`, HTTPS-адрес фронтенда и точные `CORS_ORIGINS`, реальные SMTP-настройки. Стенд предполагает один сайт по HTTPS для API и фронтенда. Передача backend не включает публикацию, подключение демонстрационного фронтенда и выполнение работы второго бэкендера.

## Пароли и очистка: этап 5

Forgot принимает нормализованный email и возвращает нейтральный `202` для неизвестного, неподтверждённого, отключённого или удалённого пользователя. Для активного подтверждённого аккаунта создаётся одноразовый токен `reset_password`; прежние ссылки сброса аннулируются. Пароль и действующие сессии на этом этапе не меняются. Письмо ставится в очередь после фиксации токена в БД. При недоступной очереди — `503`; повторный запрос допускается в пределах лимитов, старая ссылка при этом заменяется.

Ссылка из письма имеет вид `${FRONTEND_URL}/reset-password#token=...`. Токен действует `PASSWORD_RESET_TTL_MIN` минут (по умолчанию 60). Фронтенд передаёт его в `POST /auth/password/reset` вместе с `new_password`. Подтверждающий email-токен не подходит для сброса, а токен сброса — для подтверждения email.

`POST /auth/password/change` принимает Bearer, `old_password` и `new_password`; доверенный Origin не требуется. Проверяется актуальный хэш текущего пароля под блокировкой пользователя. Для нового пароля действует та же политика 8–128 символов с буквой и цифрой; пробелы сохраняются.

Успешный reset или change атомарно меняет хэш пароля, аннулирует все ссылки сброса пользователя и отзывает все его сессии. Ответ — пустой `204` с удалением refresh-cookie и `Cache-Control: no-store`. Автоматический вход не выполняется. Старые access и refresh перестают работать; требуется новый login. Параллельные запросы сериализуются блокировкой пользователя; повторное использование ссылки не меняет пароль.

Celery Beat раз в час ставит задачу `auth.cleanup_expired`. Она удаляет истёкшие сессии вместе со всей историей refresh через каскад БД и истёкшие email-токены обоих назначений. Отозванные сессии и использованные refresh сохраняются до исходного срока сессии для обнаружения повторов. Неистёкшие email-токены, пользователи, профили и Redis-кэш не удаляются. Повторный запуск безопасен. Нужны запущенные `worker` и `beat`.

### Проверка этапа 5

Из `backend`, с работающим Docker Desktop:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_passwords.py tests/integration/test_auth_cleanup.py tests/integration/test_auth_mail.py tests/auth/test_delivery.py -q -W error -p no:cacheprovider
```

Для ручной проверки пересоберите сервисы и задайте email ранее подтверждённого аккаунта:

```powershell
docker compose up -d --build --wait
Invoke-RestMethod -Uri http://localhost:8000/api/v1/ready
$base = "http://localhost:8000/api/v1/auth"
$headers = @{ Origin = "http://localhost:5173" }
$email = "EMAIL_ПОДТВЕРЖДЁННОГО_АККАУНТА"
$body = @{ email = $email } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/password/forgot" -Headers $headers -ContentType "application/json" -Body $body
```

Ожидается `202`. В http://localhost:8025 откройте новое письмо сброса и скопируйте значение после `#token=`. Переход по ссылке не меняет пароль; экран фронтенда подключается отдельно.

```powershell
$token = "ТОКЕН_ИЗ_ПИСЬМА_СБРОСА"
$newPassword = "Changed456"
$body = @{ token = $token; new_password = $newPassword } | ConvertTo-Json
(Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/password/reset" -Headers $headers -ContentType "application/json" -Body $body).StatusCode
$form = @{ username = $email; password = $newPassword }
$login = Invoke-RestMethod -Method Post -Uri "$base/login" -Headers $headers -ContentType "application/x-www-form-urlencoded" -Body $form -SessionVariable device
$authHeaders = @{ Authorization = "Bearer " + $login.access_token }
```

Reset возвращает `204`, новый вход — `200`. Старый пароль даёт `401 INVALID_CREDENTIALS`, повтор reset с той же ссылкой — `400 INVALID_EMAIL_TOKEN`. Ранее сохранённые access/refresh всех устройств перестают работать.

Смена уже известного пароля:

```powershell
$body = @{ old_password = $newPassword; new_password = "Another789" } | ConvertTo-Json
(Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/password/change" -Headers $authHeaders -ContentType "application/json" -Body $body -WebSession $device).StatusCode
Invoke-RestMethod -Uri "$base/sessions" -Headers $authHeaders
```

Ожидаются `204`, затем `401 AUTHENTICATION_REQUIRED`; вход теперь выполняется с `Another789`. Неверный текущий пароль даёт `400 INVALID_CURRENT_PASSWORD`. Forgot ограничен тремя запросами в час отдельно на IP и email, change — пятью в минуту на пользователя, reset — тридцатью в минуту на IP; превышение даёт `429` и `Retry-After`.

Очистку можно запустить вручную, не дожидаясь Beat:

```powershell
docker compose exec worker celery -A app.workers.celery_app call auth.cleanup_expired
```

Команда возвращает ID поставленной задачи. Сохранение действующей сессии, удаление просроченных записей и каскад истории refresh проверяются интеграционным тестом на отдельной БД.

## Вход и сессии: этап 4

Для login поле `username` содержит email, поле `password` — исходный пароль без обрезки пробелов. Вход с правильным паролем до подтверждения email возвращает `403 EMAIL_NOT_VERIFIED`. Неверный пароль, неизвестный email, отключённый или удалённый пользователь получают одинаковый `401 INVALID_CREDENTIALS`. Для неизвестного адреса тоже выполняется Argon2-проверка по служебному хэшу. Лимит — 5 запросов/мин на IP + нормализованный email.

Каждый вход создаёт отдельную сессию. Refresh принимается исключительно из cookie `refresh_token`, не требует действующего access и сохраняет исходный абсолютный срок сессии. Старый refresh помечается использованным до добавления нового, история сохраняется. Повтор старого токена отзывает всю сессию; отзыв фиксируется в БД до ответа `401`, а cookie очищается. Другая сессия пользователя продолжает работать. Из двух параллельных refresh со старым токеном один может вернуть `200`, второй — `401`, после чего вся эта сессия уже отозвана. Клиент должен сериализовать обновление, включая вкладки.

Все записи выполняются с единым порядком блокировок: пользователь → сессия → токен. Перед изменениями состояние повторно читается под блокировкой, включая уже загруженные ORM-объекты. Успешный выход или отзыв сразу блокирует access этой сессии на последующих запросах, даже если `exp` JWT ещё не наступил.

`POST /logout` идентифицирует устройство по refresh-cookie, включая ранее заменённый refresh той же сессии. Он не требует access и допускает отсутствие или неизвестное значение cookie. `POST /logout-all` и `DELETE /sessions/{session_id}` принимают только Bearer; cookie не заменяет авторизацию. Для logout-all отзываются только устройства аутентифицированного пользователя. Для адресного отзыва чужие и несуществующие ID неразличимы. Cookie очищается при отзыве текущего устройства; при отзыве другого сохраняется.

Проверка Bearer и выход со всех устройств работают через PostgreSQL и не используют Redis. Новые публичные маршруты refresh и logout ограничены 30 запросами/мин на IP и требуют доверенный Origin/Referer; при недоступном Redis они возвращают `503`. Bearer-маршруты не требуют Origin, поскольку не используют cookie для аутентификации. Ответы с токенами и списком устройств имеют `Cache-Control: no-store`.

### Проверка этапа 4

Из `backend` после `uv sync --frozen`, с запущенным Docker Desktop:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_sessions.py -q -W error -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -ra -W error -p no:cacheprovider
```

Проверяются login, OAuth2 form и лимиты, обязательное подтверждение email, ротация и история, неизменный срок сессии, повтор и параллельный refresh, очистка cookie, немедленный отзыв access, изоляция пользователей, гонки с logout/logout-all/DELETE и использование `get_current_user` без профиля. Тестовые защищённые маршруты существуют только в тестах.

Для ручной проверки сначала подтвердите новый аккаунт по инструкции этапа 3 ниже либо используйте свой уже подтверждённый email. Запущенные сервисы после обновления пересобираются командой `docker compose up -d --build`; секрет JWT должен сохраняться между запусками в локальном `.env`.

```powershell
$headers = @{ Origin = "http://localhost:5173" }
$form = @{ username = $email; password = "Testpass123" }
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/login -Headers $headers -ContentType "application/x-www-form-urlencoded" -Body $form -SessionVariable browserSession
$authHeaders = @{ Authorization = "Bearer " + $login.access_token }
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/sessions -Headers $authHeaders
$rotated = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/refresh -Headers $headers -WebSession $browserSession
$authHeaders.Authorization = "Bearer " + $rotated.access_token
Invoke-WebRequest -Method Post -Uri http://localhost:8000/api/v1/auth/logout -Headers $headers -WebSession $browserSession
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/sessions -Headers $authHeaders
```

Ожидания: login и refresh — `200`; список показывает свои активные устройства и `is_current`; logout — `204`; последний запрос списка — `401`, потому что access уже отозван. Для проверки logout-all выполните новый вход и отправьте Bearer в `POST /auth/logout-all`. Другие устройства этого пользователя тоже потеряют доступ.

## Отправка подтверждения: этап 3

Пароль и email проверяются до создания пользователя. Регистрация существующего адреса возвращает нейтральный `202`, не меняет пароль и не отправляет новое письмо; для получения новой ссылки используется resend. При регистрации профиль не создаётся.

Данные пользователя и SHA-256 одноразового токена сначала фиксируются в PostgreSQL, затем задача отправляется в Celery. Если публикация не удалась, API возвращает `503`: неподтверждённая учётная запись сохраняется, а повторную отправку можно запросить сразу. При сетевой неопределённости задача могла попасть в очередь; последующий resend всё равно аннулирует предыдущий токен.

Для SMTP предусмотрены до трёх повторов с задержкой. Результат задачи не сохраняется; email и токен скрываются в представлении аргументов как исходной, так и повторных задач. SMTP-ошибки заменяются безопасным сообщением. Само сообщение брокера содержит данные, необходимые для отправки; Redis используется только внутри доверенной инфраструктуры.

Подтверждение блокирует пользователя перед проверкой и использованием токена. Подтверждение и создание сессии фиксируются одной транзакцией. Из двух параллельных подтверждений только одно успешно. Токены сброса пароля не принимаются как подтверждение email.

### Настройки почты и cookie

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `FRONTEND_URL` | `http://localhost:5173` | Базовый адрес ссылок подтверждения и сброса |
| `SMTP_HOST` | `localhost`, в Compose — `mailpit` | Сервер SMTP |
| `SMTP_PORT` | 1025 | Порт SMTP |
| `SMTP_FROM` | `noreply@example.com` | Отправитель |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | пустые | Учётные данные, если SMTP требует вход |
| `SMTP_STARTTLS`, `SMTP_SSL_TLS` | false | Режимы TLS; нельзя включать оба |
| `REFRESH_COOKIE_SECURE` | автоматически по `ENV` | Для staging/production включён и не может быть выключен |

`JWT_SECRET` нужен для подтверждения и выдачи access, минимум 32 символа. `ACCESS_TTL_MIN=15`, `REFRESH_TTL_DAYS=30`, `EMAIL_VERIFICATION_TTL_HOURS=24`, `PASSWORD_RESET_TTL_MIN=60`; все значения положительные. На staging и production `FRONTEND_URL` должен быть HTTPS, без query, fragment и учётных данных.

## Как проверить этап 3

Из `backend` после установки зависимостей `uv sync --frozen`:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest tests/auth -q -W error -p no:cacheprovider
```

Для полного набора нужен работающий Docker Desktop:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra -W error -p no:cacheprovider
```

Тесты используют отдельные PostgreSQL, Redis и Mailpit. Проверяются обычная регистрация, дубликаты адресов, истёкшие и использованные токены, повторная отправка, параллельные подтверждения и регистрации, лимиты, CSRF, сбои Redis и очереди. Отдельный тест `tests/integration/test_auth_mail.py` запускает настоящий Celery worker и проверяет цепочку API → Redis → Celery → SMTP → Mailpit → подтверждение токена из письма. Рабочая БД проекта в этих тестах не используется.

### Ручная проверка через Mailpit

В PowerShell из `backend` подготовьте `.env` с постоянным JWT-секретом по [README](../../README.md#запуск-backend) и поднимите сервисы:

```powershell
docker compose up -d --build --wait
Invoke-RestMethod -Uri http://localhost:8000/api/v1/ready
```

Дождитесь `db: ok`, `redis: ok`. Compose передаёт секрет API и worker; `.env` не коммитится. Сохраняйте прежний секрет между запусками. Если запускаете API/worker непосредственно на Windows, используйте `SMTP_HOST=localhost`; в контейнерах SMTP доступен как `mailpit`. На Windows Celery запускается с `--pool=solo`, в Compose используется обычная команда worker.

Регистрация с новым адресом:

```powershell
$headers = @{ Origin = "http://localhost:5173" }
$email = [guid]::NewGuid().ToString("N") + "@example.com"
$body = @{ email = $email; password = "Testpass123" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/register -Headers $headers -ContentType "application/json" -Body $body
```

Ожидается `202` и нейтральное сообщение. Откройте http://localhost:8025: в Mailpit появится русскоязычное письмо. Скопируйте токен после `#token=` из ссылки. Фронтенд-экран подтверждения ещё не подключён, поэтому для этого этапа токен передаётся через API:

```powershell
$token = "ТОКЕН_ИЗ_ПИСЬМА"
$body = @{ token = $token } | ConvertTo-Json
$result = Invoke-WebRequest -UseBasicParsing -Method Post -Uri http://localhost:8000/api/v1/auth/verify-email -Headers $headers -ContentType "application/json" -Body $body -SessionVariable authSession
$result.StatusCode
$result.Content
$result.Headers["Set-Cookie"]
```

Ожидаются `200`, access в JSON и refresh-cookie с `HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`. Для локального HTTP `Secure` выключен. Тот же запрос подтверждения второй раз возвращает `400 INVALID_EMAIL_TOKEN`.

Для проверки resend зарегистрируйте другой новый адрес и до подтверждения запросите:

```powershell
$body = @{ email = $email } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/resend-verification -Headers $headers -ContentType "application/json" -Body $body
```

В течение 60 секунд после регистрации ожидается `429` с `Retry-After`. После интервала — `202` и новое письмо; старая ссылка больше не подтверждает email. Без доверенного Origin/Referer auth POST возвращает `403 CSRF_ORIGIN_DENIED`. Для выполнения запросов через Swagger добавьте точный origin страницы API, например `http://localhost:8000`, в локальный `CORS_ORIGINS` и перезапустите API.

## Как проверить этап 1

Из `backend` в PowerShell:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest -m "not docker" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check app tests
.\.venv\Scripts\python.exe -m mypy app
```

Эти проверки не требуют работающих PostgreSQL, Redis или Docker. Тестовые маршруты существуют только в тестовом приложении.

Для ручной проверки:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

В другом терминале:

```powershell
curl.exe -i http://localhost:8000/api/v1/missing
curl.exe -i -X POST http://localhost:8000/api/v1/health
curl.exe -i http://localhost:8000/api/v1/health
```

Ожидания: `404 NOT_FOUND`, `405 METHOD_NOT_ALLOWED` с `Allow: GET`, затем `200 {"status":"ok"}`. В http://localhost:8000/docs у ответов ошибок используется `ErrorResponse`.

Полный набор с миграциями и реальными PostgreSQL/Redis требует запущенного Docker Desktop:

```powershell
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m pytest -ra -p no:cacheprovider
```
