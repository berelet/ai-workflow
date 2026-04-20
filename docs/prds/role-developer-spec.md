# Специфікація: Роль Developer та гранулярний контроль доступу

**Версія:** 2.0  
**Дата:** 2026-04-05  
**Автор:** BA (AI Workflow)  
**Статус:** Draft  
**Джерело:** 18 User Stories (PM Reviewed, 2026-04-05)

---

## 1. Загальний опис

Розширити систему ролей проєкту AI Workflow з трьох рівнів (viewer < editor < owner) до чотирьох: **viewer < developer < editor < owner**. Нова роль `developer` надає доступ до терміналу, read-only перегляд pipeline та черги задач, але забороняє мутуючі операції над беклогом, агентами та конфігурацією проєкту.

### Мотивація

Розробники отримують роль editor лише заради терміналу, але при цьому мають зайві права на беклог, pipeline та агентів. Це створює ризик випадкових змін у плануванні. Потрібен проміжний рівень доступу.

### Поза scope

- Кастомні ролі (довільні рівні доступу)
- Per-resource permissions (доступ до окремих задач/артефактів)
- Аудит-лог змін ролей
- Обмеження конкретних команд у терміналі (sandboxing)
- Row-level security в БД
- CLI role management (лише UI)
- Роль developer для local/private projects (лише DB projects)

### Залежності (файли системи)

| Файл | Опис |
|---|---|
| `dashboard/auth/permissions.py` | ROLE_RANK, RequireProjectRole |
| `dashboard/db/models/project.py` | ProjectMembership.role |
| `dashboard/routers/projects.py` | _check_project_access helper |
| `dashboard/routers/ui.py` | tab partials, HTMX rendering |
| `dashboard/routers/queue.py` | _get_project_with_access |
| `dashboard/routers/pipeline.py` | _get_membership checks |
| `dashboard/routers/terminal.py` | terminal WebSocket/HTTP |
| `dashboard/static/lang/en.json`, `uk.json` | i18n |
| `dashboard/templates/partials/_topbar.html` | tab navigation |
| `dashboard/templates/partials/tabs/_board.html` | Board template |
| `dashboard/templates/partials/tabs/_backlog.html` | Backlog template |
| `dashboard/templates/partials/tabs/_pipeline.html` | Pipeline template |
| `dashboard/migrations/versions/` | Alembic migrations |

---

## 2. Матриця дозволів (зведена)

| Функція | viewer | developer | editor | owner |
|---|:---:|:---:|:---:|:---:|
| **Board** -- перегляд карток | + | + | + | + |
| **Board** -- створення/редагування/видалення задач | - | - | + | + |
| **Board** -- запуск pipeline (кнопка Run) | - | - | + | + |
| **Board** -- вибір для черги (checkbox) | - | - | + | + |
| **Board** -- Archive all done | - | - | + | + |
| **Board** -- pipeline статус-бейдж на картці | + | + | + | + |
| **Backlog** -- вкладка в навігації | - | - | + | + |
| **Backlog** -- CRUD операції | - | - | + | + |
| **Archive** -- перегляд | + | + | + | + |
| **Pipeline** -- вкладка в навігації | - | + (RO) | + | + |
| **Pipeline** -- перегляд графу | - | + (RO) | + | + |
| **Pipeline** -- перегляд логів запусків | - | + | + | + |
| **Pipeline** -- редагування/збереження/run/stop | - | - | + | + |
| **Pipeline** -- viewer бачить лише статус (бейдж) | + | - | - | - |
| **Agents** -- перегляд конфігурації | + | + | + | + |
| **Agents** -- редагування/збереження | - | - | + | + |
| **Artifacts** -- перегляд | + | + | + | + |
| **Terminal** -- доступ (WebSocket, HTTP) | - | + | + | + |
| **Transcriber** -- використання | - | + | + | + |
| **Queue** -- вкладка в навігації | - | + (RO) | + | + |
| **Queue** -- перегляд/моніторинг | - | + | + | + |
| **Queue** -- створення/запуск/скасування | - | - | + | + |
| **Members** -- перегляд списку | + | + | + | + |
| **Members** -- зміна ролі | - | - | - | + |
| **Members** -- видалення учасника | - | - | - | + |
| **Join Requests** -- перегляд та управління | - | - | - | + |
| **Settings** -- вкладка | - | - | - | + |
| **Delete Project** | - | - | - | + |
| **Logs** -- перегляд | + | + | + | + |

**Легенда:** + = доступно, - = заборонено, RO = read-only (елементи управління приховані).

### Видимість вкладок у навігації

| Вкладка | viewer | developer | editor | owner |
|---|:---:|:---:|:---:|:---:|
| Board | + | + | + | + |
| Archive | + | + | + | + |
| Agents | + | + | + | + |
| Artifacts | + | + | + | + |
| Members | + | + | + | + |
| Logs | + | + | + | + |
| Pipeline | - | + | + | + |
| Terminal | - | + | + | + |
| Queue | - | + | + | + |
| Transcriber | - | + | + | + |
| Backlog | - | - | + | + |
| Join Requests | - | - | - | + |
| Settings | - | - | - | + |

---

## 3. Специфікації User Stories

---

### US-1: Додати роль developer до ієрархії ролей

**Проблема:** Розробники отримують роль editor лише заради терміналу, але при цьому мають зайві права на беклог, pipeline та агентів.

**Як** адміністратор системи,  
**я хочу** мати роль developer між viewer та editor,  
**щоб** розробники мали доступ до терміналу та перегляду pipeline без можливості змінювати беклог, агентів або конфігурацію проекту.

**Пріоритет:** high (strategic bet -- prerequisite для всіх інших stories)  
**Залежності:** немає (базова story)

#### Специфікація реалізації

1. В `dashboard/auth/permissions.py` оновити ROLE_RANK:
   ```python
   ROLE_RANK = {"viewer": 0, "developer": 1, "editor": 2, "owner": 3}
   ```

2. Додати convenience-dependency:
   ```python
   require_developer = RequireProjectRole("developer")
   ```

3. В `dashboard/db/models/project.py` оновити коментар до поля `role`:
   ```python
   role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="viewer")
   # Допустимі значення: owner, editor, developer, viewer
   ```

4. Логіка `RequireProjectRole` залишається без змін -- ранжування автоматично працює через порівняння `>=` з новим рангом.

#### Acceptance Criteria

**AC-1.1: ROLE_RANK містить 4 ролі**
- Дано: система з оновленим `permissions.py`
- Коли: звертаюсь до `ROLE_RANK`
- Тоді: повертає `{"viewer": 0, "developer": 1, "editor": 2, "owner": 3}`

**AC-1.2: Convenience-dependency require_developer існує**
- Дано: система з оновленим `permissions.py`
- Коли: імпортую `require_developer`
- Тоді: отримую екземпляр `RequireProjectRole` з `min_role="developer"`

**AC-1.3: RequireProjectRole("editor") відхиляє developer**
- Дано: користувач з роллю developer (rank 1), ендпоінт з `require_editor`
- Коли: надходить запит від developer
- Тоді: HTTP 403 з повідомленням "Requires editor role, you have developer"

**AC-1.4: RequireProjectRole("developer") пропускає developer, editor, owner**
- Дано: ендпоінт з `require_developer`
- Коли: надходить запит від developer (rank 1), editor (rank 2), owner (rank 3)
- Тоді: HTTP 200 для всіх трьох

**AC-1.5: Superadmin bypass працює для всіх 4 ролей**
- Дано: superadmin без membership у проєкті
- Коли: надходить запит до ендпоінту з будь-яким `RequireProjectRole`
- Тоді: HTTP 200 (bypass)

#### Edge Cases

- Невідома роль в БД (наприклад, "manager") отримує rank -1 через `ROLE_RANK.get(role, -1)`, що блокує будь-який доступ -- поведінка зберігається.
- Порожній рядок ролі трактується як rank -1.
- Superadmin bypass перевіряється ДО порівняння рангів -- порядок збережений.

#### Обмеження та допущення

- ROLE_RANK є єдиним джерелом правди для ієрархії ролей.
- Ранги -- цілі числа без пропусків (0, 1, 2, 3) для коректного порівняння `>=`.
- Зміна рангів існуючих ролей (editor: 1->2, owner: 2->3) потребує grep по коду на hard-coded числові порівняння.
- Строкове зберігання ролей у БД означає, що зміна рангів не потребує міграції даних.

---

### US-2: Безпечна міграція існуючих даних при додаванні ролі

**Проблема:** Після додавання нової ролі developer існуючі записи membership мають зберегти коректні права. Без чіткої стратегії міграції можливі як втрата доступу, так і несанкціоноване розширення прав.

**Як** owner проекту,  
**я хочу** щоб після оновлення системи всі існуючі учасники зберегли свої ролі та права,  
**щоб** оновлення системи не порушило роботу команди.

**Пріоритет:** high (quick win -- мінімальний effort, критичний для безпеки)  
**Залежності:** US-1

#### Специфікація реалізації

1. Alembic-міграція (наприклад, `009_add_developer_role.py`):
   - Без змін до структури таблиці (role вже `String(20)`, "developer" вміщується).
   - Існуючі значення viewer/editor/owner залишаються без змін.
   - Опціонально: додати CHECK constraint `role IN ('viewer', 'developer', 'editor', 'owner')`.

2. Маппінг міграції (без зміни даних у БД):
   - viewer -> viewer (rank 0 -> 0)
   - editor -> editor (rank 1 -> 2, лише в ROLE_RANK коді)
   - owner -> owner (rank 2 -> 3, лише в ROLE_RANK коді)
   - developer не призначається автоматично -- лише вручну owner

3. Downgrade стратегія:
   - Якщо є записи з role="developer" -- замінити на "viewer" (безпечне пониження).
   - Якщо CHECK constraint додано -- видалити при downgrade.

#### Acceptance Criteria

**AC-2.1: Міграція виконується без ALTER TABLE**
- Дано: БД з існуючими membership записами
- Коли: запускаю `alembic upgrade head`
- Тоді: міграція проходить без помилок, жоден стовпець не змінюється

**AC-2.2: 0 користувачів з невалідною роллю після міграції**
- Дано: БД після міграції
- Коли: виконую `SELECT COUNT(*) FROM project_membership WHERE role NOT IN ('viewer','developer','editor','owner')`
- Тоді: результат = 0

**AC-2.3: Rollback-міграція присутня та не видаляє дані**
- Дано: виконана міграція 009
- Коли: виконую `alembic downgrade -1`
- Тоді: developer (якщо є) стають viewer, структура таблиці не змінюється

**AC-2.4: Всі існуючі editor залишаються editor**
- Дано: БД з 5 editor учасниками
- Коли: запускаю міграцію
- Тоді: всі 5 мають role="editor" (не понижені до developer)

**AC-2.5: Система працює без downtime під час міграції**
- Дано: працюючий сервер
- Коли: міграція виконується
- Тоді: запити продовжують оброблятись (без перезапуску)

#### Edge Cases

- Паралельне використання старого і нового коду під час deploy: "developer" як рядок матиме rank -1 в старому коді, що дасть 403 -- безпечна деградація.
- Міграція на великій БД (10 000+ записів): без ALTER TABLE -- миттєве виконання.
- Якщо CHECK constraint порушується (manual INSERT) -- БД відхилить запис.

#### Обмеження та допущення

- Міграція не потребує downtime.
- Rollback-сценарій: developer -> viewer (безпечне пониження, не editor).
- Немає автоматичної конвертації editor -> developer. Owner вирішує вручну.
- Автоматичне визначення "хто з editor має стати developer" -- поза scope (ручне рішення owner).

---

### US-3: Viewer -- лише перегляд Board, Archive, Agents, Artifacts

**Проблема:** Без серверної перевірки ролі viewer може через API виконати мутуючі операції, навіть якщо UI приховає кнопки.

**Як** viewer проекту,  
**я хочу** переглядати Board (картки задач), Archive, Agents та Artifacts у режимі read-only,  
**щоб** слідкувати за прогресом проекту без ризику випадково змінити дані.

**Пріоритет:** high (quick win -- базова безпека read-only)  
**Залежності:** US-1

#### Специфікація реалізації

1. Viewer має доступ лише до GET-ендпоінтів:
   - `GET /ui/partials/tabs/board` -- перегляд (без кнопок New Task, Run, Delete, Archive Done, checkbox)
   - `GET /ui/partials/tabs/archive` -- перегляд
   - `GET /ui/partials/tabs/agents` -- перегляд (без кнопок Save, Reset)
   - `GET /artifacts/{project}/{task_id}` -- перегляд артефактів
   - `GET /ui/partials/tabs/logs` -- перегляд

2. POST/PUT/PATCH/DELETE ендпоінти для Board, Agents, Backlog повертають 403.

3. Шаблон `_board.html` перевіряє `user_role` через Jinja2:
   ```jinja2
   {% if user_role in ['editor', 'owner'] %}
     <button class="add-task-btn">+ {{ t('board.add_task', lang) }}</button>
   {% endif %}
   ```

4. Viewer бачить Members tab з read-only списком учасників та їх ролями.

#### Acceptance Criteria

**AC-3.1: Viewer отримує 200 на GET Board, Archive, Agents, Artifacts**
- Дано: користувач з роллю viewer у проєкті "my-app"
- Коли: GET /ui/partials/tabs/board, /archive, /agents, GET /artifacts/my-app/1
- Тоді: HTTP 200 для всіх

**AC-3.2: Viewer отримує 403 на мутуючі операції**
- Дано: viewer
- Коли: POST /api/projects/my-app/backlog (створення задачі)
- Тоді: HTTP 403

**AC-3.3: UI НЕ рендерить кнопки Create/Edit/Delete для viewer**
- Дано: viewer відкриває Board
- Коли: сервер рендерить _board.html з user_role="viewer"
- Тоді: в DOM відсутні: "+ New Task", Run (play), Delete (x), Archive Done, checkbox

**AC-3.4: Viewer бачить список учасників з ролями**
- Дано: viewer
- Коли: відкриваю вкладку Members
- Тоді: бачу імена учасників з бейджами ролей, без елементів управління

#### Edge Cases

- Viewer намагається відкрити модал редагування задачі через клік на картку Board -- модал відкривається в режимі read-only (без кнопки Save, поля disabled).
- Viewer з прямим API-запитом через curl -- 403 на будь-який мутуючий ендпоінт.
- Viewer бачить кількість артефактів на картці Board і може їх переглядати (клік на "N art." працює).
- HTMX запит з невалідною роллю -- повертаємо HTML з повідомленням помилки, а не JSON (щоб не ламати DOM).

#### Обмеження та допущення

- Board для viewer є read-only: картки клікабельні для перегляду деталей, але модал без кнопки Save.
- Viewer не бачить Pipeline логи, лише статус (done/running/failed) на картці Board.
- GET-запит до Board дозволений для всіх ролей (viewer+).

---

### US-4: Viewer -- обмежений перегляд Pipeline (лише статус на Board)

**Проблема:** Viewer потребує розуміння стану задачі (чи запущений pipeline), але не потребує доступу до детальних логів та графу.

**Як** viewer проекту,  
**я хочу** бачити індикатор статусу pipeline run (running/done/failed) на картках Board,  
**щоб** розуміти чи виконується задача, без доступу до вкладки Pipeline.

**Пріоритет:** medium (quick win -- мінімальний effort, покращує UX viewer)  
**Залежності:** US-1, US-3

#### Специфікація реалізації

1. На картці Board додати бейдж статусу pipeline:
   - running: spinner або текст "Running" (жовтий/оранжевий)
   - done: checkmark або "Done" (зелений)
   - failed: X або "Failed" (червоний)
   - немає запусків: нічого не показувати

2. Вкладка Pipeline НЕ відображається в навігації для viewer (Jinja2 `{% if %}`).

3. API для viewer:
   - `GET /pipeline/status` -- повертає лише поточний статус (200 для viewer)
   - `GET /pipeline/runs/{id}/logs` -- 403 для viewer

4. Статус pipeline на картці Board рендериться серверно в `_board.html` як частина даних задачі.

#### Acceptance Criteria

**AC-4.1: Бейдж статусу pipeline на картці Board для viewer**
- Дано: viewer, задача #5 має pipeline run зі статусом "running"
- Коли: переглядаю Board
- Тоді: на картці #5 відображається бейдж "Running" (жовтий)

**AC-4.2: Вкладка Pipeline НЕ в навігації для viewer**
- Дано: viewer
- Коли: дивлюсь на topbar tabs
- Тоді: вкладка "Pipeline" відсутня

**AC-4.3: Viewer отримує 403 на логи pipeline**
- Дано: viewer
- Коли: GET /api/projects/my-app/pipeline/runs/1/logs
- Тоді: HTTP 403 "Requires developer role"

**AC-4.4: Viewer отримує 200 на статус pipeline**
- Дано: viewer
- Коли: GET /api/projects/my-app/pipeline/status
- Тоді: HTTP 200 з JSON `{"status": "running"}` (без детальних логів)

#### Edge Cases

- Задача без pipeline runs: бейдж не показується (немає статусу).
- Pipeline run давно завершений (>24h): бейдж все одно показує "Done" (не зникає).
- Viewer натискає на бейдж статусу: нічого не відбувається (не є посиланням).

#### Обмеження та допущення

- Viewer НЕ має доступу до Pipeline tab в повному вигляді -- лише індикатор статусу на Board-картці.
- Статус береться з останнього pipeline run для задачі.
- Статус оновлюється при перезавантаженні Board (не real-time polling для viewer).

---

### US-5: Developer -- доступ до терміналу

**Проблема:** Щоб працювати з CLI-агентами, розробник зараз потребує роль editor, що дає зайві права на беклог та pipeline management.

**Як** developer проекту,  
**я хочу** мати доступ до терміналу (WebSocket /ws/terminal та HTTP ендпоінти),  
**щоб** виконувати задачі через CLI у контексті проекту без повних прав на планування.

**Пріоритет:** high (strategic bet -- ключова цінність ролі developer)  
**Залежності:** US-1

#### Специфікація реалізації

1. Terminal ендпоінти вимагають `min_role="developer"`:
   - `WS /ws/terminal` -- WebSocket підключення
   - `POST /api/terminal/start` -- створення сесії
   - `POST /api/terminal/command` -- виконання команди
   - `POST /api/terminal/upload` -- file upload
   - `POST /api/terminal/stop` -- зупинка сесії

2. В `dashboard/routers/terminal.py` замінити `require_editor` (або поточну перевірку) на `require_developer`.

3. Tmux-сесія створюється з ім'ям `user_{id}_project_{id}` (існуюча поведінка).

4. Вкладка Terminal видима для developer+ в навігації.

#### Acceptance Criteria

**AC-5.1: Developer може підключитися до WebSocket терміналу**
- Дано: developer у проєкті "my-app"
- Коли: підключаюсь до WS /ws/terminal з project=my-app
- Тоді: HTTP 101 (Switching Protocols), з'єднання встановлено

**AC-5.2: Developer може виконати POST /terminal/command**
- Дано: developer з активною terminal сесією
- Коли: POST /api/terminal/command з body `{"command": "ls"}`
- Тоді: HTTP 200, отримую результат команди

**AC-5.3: Developer може використовувати file upload**
- Дано: developer
- Коли: POST /api/terminal/upload з файлом
- Тоді: HTTP 200, файл завантажено

**AC-5.4: Viewer отримує 403 на всі terminal ендпоінти**
- Дано: viewer
- Коли: POST /api/terminal/start
- Тоді: HTTP 403 "Requires developer role"

**AC-5.5: Tmux-сесія створюється в контексті проекту**
- Дано: developer (user_id=42) у проєкті "my-app" (project_id=7)
- Коли: POST /api/terminal/start
- Тоді: tmux сесія з ім'ям `user_42_project_7` створена

#### Edge Cases

- Developer відключається від WebSocket -- сесія очищується коректно (tmux detach, не kill).
- Developer намагається підключитись до терміналу іншого проєкту, де він viewer -- 403.
- Два developer-и в одному проєкті створюють окремі tmux-сесії (різні user_id).

#### Обмеження та допущення

- Developer має доступ до terminal, що дає змогу виконувати довільні команди. Це свідомий вибір -- developer потребує CLI для роботи.
- Sandboxing (обмеження конкретних команд) -- окремий epic, поза scope.
- Terminal доступний для developer+ (developer, editor, owner).

---

### US-6: Developer -- перегляд Pipeline та логів (read-only)

**Проблема:** Developer виконує задачі в терміналі, але без доступу до pipeline логів не може зрозуміти стан обробки задачі та діагностувати проблеми.

**Як** developer проекту,  
**я хочу** бачити вкладку Pipeline з графом та детальними логами кожного stage,  
**щоб** розуміти що відбувається на кожному етапі обробки задачі.

**Пріоритет:** high (quick win -- read-only доступ, мінімальний effort)  
**Залежності:** US-1, US-4

#### Специфікація реалізації

1. Pipeline tab видимий для developer+ в навігації.

2. API ендпоінти для developer (GET-only):
   - `GET /api/projects/{name}/pipeline` -- перегляд конфігурації (200)
   - `GET /api/projects/{name}/pipeline/runs` -- список запусків (200)
   - `GET /api/projects/{name}/pipeline/runs/{id}/logs` -- логи stage (200)

3. API ендпоінти заборонені для developer (editor+):
   - `POST /api/projects/{name}/pipeline` -- збереження (403)
   - `POST /api/projects/{name}/pipeline/run` -- запуск (403)
   - `POST /api/projects/{name}/pipeline/stop` -- зупинка (403)
   - `PUT /api/projects/{name}/pipeline/config` -- зміна конфігурації (403)

4. UI для developer:
   - Drawflow-граф рендериться в readOnly mode (вузли не drag-and-droppable)
   - Кнопки "Save Pipeline", "Clear", "Run", "Stop" -- приховані (Jinja2)
   - Pipeline runs list з логами -- повний доступ

5. Різниця з viewer:
   - Viewer: лише бейдж статусу на Board (без вкладки Pipeline)
   - Developer: повна вкладка Pipeline з графом та логами (read-only)

#### Acceptance Criteria

**AC-6.1: Developer отримує 200 на GET pipeline runs та logs**
- Дано: developer, є 3 завершених pipeline runs
- Коли: GET /api/projects/my-app/pipeline/runs
- Тоді: HTTP 200, JSON з 3 записами

**AC-6.2: Developer отримує 403 на POST pipeline run/stop/save**
- Дано: developer
- Коли: POST /api/projects/my-app/pipeline/run
- Тоді: HTTP 403 "Requires editor role"

**AC-6.3: Вкладка Pipeline відображається для developer**
- Дано: developer
- Коли: рендериться topbar
- Тоді: вкладка "Pipeline" присутня в DOM

**AC-6.4: Кнопки Run/Stop/Save НЕ рендеряться для developer**
- Дано: developer відкриває Pipeline tab
- Коли: сервер рендерить _pipeline.html з user_role="developer"
- Тоді: кнопки "Save Pipeline", "Clear", "Run", "Stop" відсутні в DOM

#### Edge Cases

- Pipeline в процесі редагування editor-ом: developer бачить збережену версію, не live-draft.
- Developer натискає на вузол drawflow: відкривається read-only панель деталей (поля disabled).
- Якщо pipeline не створений: developer бачить повідомлення "No pipelines configured".
- Pipeline run, що виконується в реальному часі: developer бачить оновлення через polling (5 секунд).

#### Обмеження та допущення

- Drawflow-editor рендериться однаково, але для developer з readOnly mode.
- Polling interval для developer: 5 секунд (для live run).
- PipelineStageLog вже існує в БД.

---

### US-7: Developer -- моніторинг черги задач (read-only)

**Проблема:** Developer потребує бачити прогрес виконання задач у черзі, щоб координувати свою роботу з pipeline-обробкою.

**Як** developer проекту,  
**я хочу** бачити список задач у черзі з їх статусами та прогресом,  
**щоб** відслідковувати хід виконання без можливості створювати, запускати чи скасовувати черги.

**Пріоритет:** medium (quick win -- read-only, аналогічний US-6)  
**Залежності:** US-1

#### Специфікація реалізації

1. Queue tab видимий для developer+ в навігації.

2. API ендпоінти для developer (GET-only):
   - `GET /api/queue/active` -- список черг (200)
   - `GET /api/queue/{id}` -- деталі черги (200)

3. API ендпоінти заборонені для developer (editor+):
   - `POST /api/queue/create` -- створення черги (403)
   - `POST /api/queue/{id}/start` -- запуск (403)
   - `POST /api/queue/{id}/cancel` -- скасування (403)
   - `DELETE /api/queue/{id}` -- видалення (403)

4. UI для developer:
   - Список задач у черзі з прогрес-баром та статусами (pending/running/completed/failed)
   - Кнопки "Create Queue", "Run", "Cancel" -- приховані (Jinja2)

#### Acceptance Criteria

**AC-7.1: Developer отримує 200 на GET /queue (список черг)**
- Дано: developer, є 2 активні черги
- Коли: GET /api/queue/active
- Тоді: HTTP 200, JSON з 2 чергами

**AC-7.2: Developer отримує 200 на GET /queue/{id} (деталі)**
- Дано: developer, черга з id=5
- Коли: GET /api/queue/5
- Тоді: HTTP 200, JSON з деталями черги та прогресом

**AC-7.3: Developer отримує 403 на POST /queue, POST /queue/{id}/run, DELETE**
- Дано: developer
- Коли: POST /api/queue/create
- Тоді: HTTP 403 "Requires editor role"

**AC-7.4: Вкладка Queue відображається для developer**
- Дано: developer
- Коли: рендериться topbar
- Тоді: вкладка "Queue" присутня

**AC-7.5: Кнопки Create/Run/Cancel НЕ рендеряться для developer**
- Дано: developer відкриває Queue tab
- Коли: сервер рендерить queue template з user_role="developer"
- Тоді: кнопки "Create Queue", "Run", "Cancel" відсутні в DOM

#### Edge Cases

- Developer відкриває Queue tab, коли немає активних черг -- бачить "Queue is empty".
- Черга запущена editor-ом, потім editor втрачає роль -- черга продовжує виконуватись, developer бачить прогрес.
- Queue monitoring оновлюється через той самий механізм polling, що для editor.

#### Обмеження та допущення

- Queue monitoring для developer використовує той самий polling/WebSocket механізм, що для editor.
- Viewer НЕ бачить Queue tab взагалі.

---

### US-8: Developer -- доступ до транскрайбера

**Проблема:** Для зручної роботи з терміналом developer потребує можливість створювати промпти голосом.

**Як** developer проекту,  
**я хочу** мати доступ до Transcriber,  
**щоб** створювати промпти через голосовий запис для зручнішої роботи.

**Пріоритет:** low (nice to have -- потребує уточнення scope)  
**Залежності:** US-1

**Примітка:** Архітектурне рішення #14 визначає "Available for all users". Якщо рішення зберігається -- viewer теж має доступ і ця story потребує уточнення з owner.

#### Специфікація реалізації

1. Вкладка/кнопка Transcriber видима для developer+.

2. API транскрайбера вимагає `min_role="developer"`:
   - `POST /api/transcribe` -- відправка аудіо (developer+)

3. Viewer НЕ бачить кнопку Transcriber в UI (Jinja2).

#### Acceptance Criteria

**AC-8.1: Developer бачить кнопку Transcriber в UI**
- Дано: developer у проєкті
- Коли: рендериться topbar
- Тоді: вкладка/кнопка "Transcriber" присутня

**AC-8.2: Viewer НЕ бачить кнопку Transcriber**
- Дано: viewer
- Коли: рендериться topbar
- Тоді: вкладка "Transcriber" відсутня

**AC-8.3: API транскрайбера повертає 403 для viewer**
- Дано: viewer
- Коли: POST /api/transcribe
- Тоді: HTTP 403

**AC-8.4: API транскрайбера повертає 200 для developer+**
- Дано: developer (або editor, owner)
- Коли: POST /api/transcribe з валідним аудіо
- Тоді: HTTP 200

#### Edge Cases

- Viewer копіює URL Transcriber і переходить напряму -- 403 або redirect.
- Developer без мікрофону -- UI показує помилку "Microphone not available" (не серверна перевірка).

#### Обмеження та допущення

- Якщо буде прийнято рішення зберегти "Available for all users" (рішення #14), ця story скасовується і Transcriber залишається доступним для всіх.
- Потребує фінального підтвердження scope від owner.

---

### US-9: Захист беклогу від viewer та developer

**Проблема:** Без серверної перевірки ролі будь-який учасник може через API створити або видалити задачу в беклозі, навіть якщо UI приховає кнопки.

**Як** editor/owner проекту,  
**я хочу** щоб тільки editor та owner мали доступ до вкладки Backlog та CRUD операцій над задачами,  
**щоб** зберегти контроль над плануванням та пріоритизацією задач.

**Пріоритет:** high (quick win -- критичний для захисту планування)  
**Залежності:** US-1, US-3

#### Специфікація реалізації

1. Вкладка Backlog видима тільки для editor+ в навігації (Jinja2 `{% if %}`).

2. Всі ендпоінти беклогу вимагають `min_role="editor"`:
   - `GET /ui/partials/tabs/backlog` -- перегляд вкладки (editor+)
   - `POST /api/projects/{name}/backlog` -- створення задачі
   - `PUT /api/projects/{name}/backlog/{id}` -- оновлення
   - `DELETE /api/projects/{name}/backlog/{id}` -- видалення
   - `POST /ui/actions/move-to-todo` -- переміщення в todo

3. При прямому переході за URL /backlog -- сервер повертає 403 HTML-сторінку (не JSON).

#### Acceptance Criteria

**AC-9.1: require_editor застосований до всіх Backlog ендпоінтів**
- Дано: developer або viewer
- Коли: POST /api/projects/my-app/backlog
- Тоді: HTTP 403 "Requires editor role"

**AC-9.2: Viewer отримує 403 з локалізованим повідомленням**
- Дано: viewer з мовою uk
- Коли: POST /api/projects/my-app/backlog
- Тоді: HTTP 403 з повідомленням "Потрiбна роль Редактор" (або англійською залежно від мови)

**AC-9.3: Developer отримує 403**
- Дано: developer
- Коли: DELETE /api/projects/my-app/backlog/15
- Тоді: HTTP 403

**AC-9.4: Вкладка Backlog НЕ рендериться для viewer та developer**
- Дано: viewer або developer
- Коли: рендериться topbar
- Тоді: вкладка "Backlog" відсутня в DOM

**AC-9.5: Прямий перехід за URL Backlog -- 403**
- Дано: developer
- Коли: вводжу URL /ui/partials/tabs/backlog напряму
- Тоді: сервер повертає HTML з повідомленням "Insufficient permissions" (403)

#### Edge Cases

- Editor створює задачу в Backlog -- вона з'являється на Board для всіх ролей (включаючи viewer/developer).
- HTMX запит з невалідною роллю не повинен ламати DOM -- повертаємо HTML з повідомленням помилки.
- Viewer натискає на URL #backlog (client-side hash) -- HTMX запит до серверного partial повертає 403.

#### Обмеження та допущення

- Board та Backlog -- різні вкладки, але Board показує ті ж задачі. Board read-only для viewer/developer означає лише приховання кнопок дій.
- GET-запит до Board дозволений для всіх ролей (viewer+).
- Backlog GET-запит (перегляд вкладки) вимагає editor+, на відміну від Board.

---

### US-10: Захист Board від мутуючих дій для viewer та developer

**Проблема:** Board показує кнопки створення задач, запуску pipeline, видалення та інші мутуючі дії. Без захисту viewer/developer можуть змінити стан проекту.

**Як** editor/owner проекту,  
**я хочу** щоб кнопки створення задач, запуску pipeline, видалення, вибору для черги та "Archive all done" на Board були доступні лише editor+,  
**щоб** viewer та developer бачили Board у режимі read-only.

**Пріоритет:** high (quick win -- захист основного робочого простору)  
**Залежності:** US-1, US-3

#### Специфікація реалізації

1. В `_board.html` обгорнути елементи в Jinja2 `{% if user_role in ['editor', 'owner'] %}`:
   - Кнопка "+ New Task" (add-task-btn)
   - Кнопки Run (play) та Delete (x) на кожній картці (card-actions)
   - Checkbox для вибору в чергу (queue-checkbox)
   - Кнопка "Run all" для черги (btn-queue-selected)
   - Кнопка "Archive all done" (btn-ghost archive)

2. API ендпоінти Board вимагають `min_role="editor"`:
   - `POST /api/projects/{name}/board/tasks` -- створення задачі (403 для viewer/developer)
   - `POST /api/projects/{name}/board/tasks/{id}/run` -- запуск pipeline (403)
   - `DELETE /api/projects/{name}/board/tasks/{id}` -- видалення (403)
   - `POST /ui/actions/archive-done` -- архівування (403)

3. Модал перегляду задачі: для viewer/developer відкривається в read-only (без кнопки Save, поля disabled).

#### Acceptance Criteria

**AC-10.1: Кнопки приховані для viewer та developer**
- Дано: viewer або developer відкриває Board
- Коли: сервер рендерить _board.html з user_role="viewer" або "developer"
- Тоді: кнопки Create Task, Run, Delete, Queue checkbox, Archive Done відсутні в DOM

**AC-10.2: POST /board/tasks повертає 403 для viewer та developer**
- Дано: developer
- Коли: POST /api/projects/my-app/board/tasks з body `{"title": "test"}`
- Тоді: HTTP 403

**AC-10.3: POST /board/tasks/{id}/run повертає 403**
- Дано: viewer
- Коли: POST /api/projects/my-app/board/tasks/1/run
- Тоді: HTTP 403

**AC-10.4: DELETE /board/tasks/{id} повертає 403**
- Дано: developer
- Коли: DELETE /api/projects/my-app/board/tasks/5
- Тоді: HTTP 403

**AC-10.5: Board повністю функціональний для editor та owner**
- Дано: editor
- Коли: відкриваю Board
- Тоді: всі кнопки (New Task, Run, Delete, Archive Done, checkbox) присутні та працюють

#### Edge Cases

- Viewer натискає на картку Board: модал відкривається в read-only (поля disabled, без Save).
- Developer натискає на картку Board: аналогічно viewer -- read-only модал.
- Board для viewer/developer: фільтри (todo/in-progress/done) працюють нормально.
- Прогрес-бар (running pipeline на Board) видимий для всіх ролей.

#### Обмеження та допущення

- Board елементи приховуються повністю (не disabled), щоб не плутати користувача.
- Alpine.js x-show НЕ використовується для безпеки -- лише Jinja2 `{% if %}` (серверний рендеринг).
- API перевірка -- основний бар'єр, UI приховання -- додатковий UX-шар.

---

### US-11: Захист редагування Pipeline -- тільки editor+

**Проблема:** Pipeline config визначає послідовність AI-агентів. Зміна конфігурації може зламати обробку всіх задач проекту.

**Як** editor проекту,  
**я хочу** мати ексклюзивний доступ до збереження та редагування конфігурації pipeline,  
**щоб** developer міг переглядати pipeline, але не змінювати його структуру.

**Пріоритет:** high (quick win -- захист pipeline config)  
**Залежності:** US-1, US-6

#### Специфікація реалізації

1. API ендпоінти з `min_role="editor"`:
   - `PUT /api/projects/{name}/pipeline/config` -- збереження конфігурації
   - `POST /api/projects/{name}/pipeline/run` -- запуск pipeline
   - `POST /api/projects/{name}/pipeline/stop` -- зупинка pipeline
   - `DELETE /api/projects/{name}/pipeline/{id}` -- видалення

2. UI для developer:
   - Drawflow-граф в readOnly mode
   - Кнопки Save Config, Run, Stop, Clear -- приховані (Jinja2)
   - Pipeline runs list та логи -- доступні (read-only)

3. UI для editor+:
   - Drawflow-граф в edit mode
   - Всі кнопки видимі та функціональні

#### Acceptance Criteria

**AC-11.1: PUT /pipeline/config повертає 403 для developer та viewer**
- Дано: developer
- Коли: PUT /api/projects/my-app/pipeline/config з новим JSON
- Тоді: HTTP 403

**AC-11.2: POST /pipeline/run повертає 403 для developer та viewer**
- Дано: developer
- Коли: POST /api/projects/my-app/pipeline/run
- Тоді: HTTP 403

**AC-11.3: POST /pipeline/stop повертає 403 для developer та viewer**
- Дано: viewer
- Коли: POST /api/projects/my-app/pipeline/stop
- Тоді: HTTP 403

**AC-11.4: Кнопки Save/Run/Stop/Clear НЕ рендеряться для developer**
- Дано: developer відкриває Pipeline tab
- Коли: сервер рендерить _pipeline.html з user_role="developer"
- Тоді: кнопки "Save Pipeline", "Clear", "Run", "Stop" відсутні в DOM

**AC-11.5: Developer бачить pipeline граф та логи (read-only)**
- Дано: developer, є збережений pipeline з 3 stages
- Коли: відкриваю Pipeline tab
- Тоді: бачу drawflow-граф з 3 вузлами (non-interactive) та список pipeline runs з логами

#### Edge Cases

- Developer натискає на вузол drawflow: відкривається read-only панель деталей (назва агента, prompt, output) без можливості змінити.
- Editor зберігає pipeline під час перегляду developer-ом: developer побачить оновлення при наступному завантаженні tab.
- Pipeline не створений: developer бачить повідомлення "No pipelines configured", editor бачить порожній editor.

#### Обмеження та допущення

- Drawflow має вбудований readOnly API, але потребує тестування.
- Developer не може drag-and-drop вузли або з'єднання в readOnly mode.

---

### US-12: Захист управління чергою -- тільки editor+

**Проблема:** Task queue дозволяє пакетно запускати задачі через pipeline. Без контролю developer може ненавмисно запустити масову обробку.

**Як** editor проекту,  
**я хочу** мати ексклюзивний доступ до створення, запуску та скасування черг задач,  
**щоб** developer бачив прогрес, але не міг впливати на виконання.

**Пріоритет:** medium (quick win -- аналогічний патерн до US-11)  
**Залежності:** US-1, US-7

#### Специфікація реалізації

1. API ендпоінти з `min_role="editor"`:
   - `POST /api/queue/create` -- створення черги
   - `POST /api/queue/{id}/start` -- запуск
   - `POST /api/queue/{id}/cancel` -- скасування
   - `DELETE /api/queue/{id}` -- видалення

2. API ендпоінти для developer+ (GET):
   - `GET /api/queue/active` -- список (200)
   - `GET /api/queue/{id}` -- деталі (200)

3. UI для developer:
   - Список черг з прогрес-баром та статусами -- доступний
   - Кнопки "Create Queue", "Run", "Cancel" -- приховані

4. На Board: checkbox та "Run all" кнопка -- тільки для editor+ (вже покрито US-10).

#### Acceptance Criteria

**AC-12.1: POST /queue повертає 403 для developer та viewer**
- Дано: developer
- Коли: POST /api/queue/create з body `{"task_ids": [1,2,3]}`
- Тоді: HTTP 403

**AC-12.2: POST /queue/{id}/run повертає 403**
- Дано: developer
- Коли: POST /api/queue/5/start
- Тоді: HTTP 403

**AC-12.3: DELETE /queue/{id} повертає 403**
- Дано: viewer
- Коли: DELETE /api/queue/5
- Тоді: HTTP 403

**AC-12.4: Кнопки Create/Run/Cancel НЕ рендеряться для developer**
- Дано: developer відкриває Queue tab
- Коли: сервер рендерить queue template
- Тоді: кнопки управління відсутні, лише прогрес-бар та статуси

**AC-12.5: GET /queue та GET /queue/{id} доступні для developer (200)**
- Дано: developer
- Коли: GET /api/queue/active
- Тоді: HTTP 200

#### Edge Cases

- Черга запущена editor-ом, editor втрачає роль (стає viewer) -- черга продовжує виконуватись, developer бачить прогрес.
- Два editor-и одночасно створюють черги -- кожна черга незалежна.
- Developer відкриває Queue tab без активних черг -- "Queue is empty".

#### Обмеження та допущення

- Queue monitoring для developer оновлюється через той самий механізм, що для editor.
- "Run all" на Board з'являється тільки коли вибрано задачі (існуюча поведінка).

---

### US-13: Захист редагування агентів -- тільки editor+

**Проблема:** Конфігурація агентів визначає промпти та інструкції AI. Зміна агентів може порушити якість обробки задач.

**Як** editor проекту,  
**я хочу** щоб тільки editor+ міг зберігати та змінювати конфігурацію агентів,  
**щоб** viewer та developer бачили налаштування, але не могли їх змінити.

**Пріоритет:** medium (quick win -- аналогічний патерн)  
**Залежності:** US-1

#### Специфікація реалізації

1. API ендпоінти з `min_role="editor"`:
   - `POST /api/agents` -- створення агента
   - `PUT /api/agents/{id}` -- оновлення
   - `DELETE /api/agents/{id}` -- видалення

2. API ендпоінти для всіх ролей (viewer+):
   - `GET /api/agents` -- список агентів (200)
   - `GET /api/agents/{id}` -- деталі агента (200)

3. UI:
   - Вкладка Agents видима для всіх ролей
   - Кнопки "Save", "Reset", "New Agent", "Delete" -- тільки editor+ (Jinja2)
   - Для viewer/developer: поля конфігурації disabled або відображаються як текст

#### Acceptance Criteria

**AC-13.1: PUT /agents/{id} повертає 403 для viewer та developer**
- Дано: developer
- Коли: PUT /api/agents/3 з оновленим промптом
- Тоді: HTTP 403

**AC-13.2: POST /agents повертає 403 для viewer та developer**
- Дано: viewer
- Коли: POST /api/agents з body `{"name": "new-agent"}`
- Тоді: HTTP 403

**AC-13.3: DELETE /agents/{id} повертає 403**
- Дано: developer
- Коли: DELETE /api/agents/2
- Тоді: HTTP 403

**AC-13.4: Кнопка Save НЕ рендериться для viewer та developer**
- Дано: developer відкриває Agents tab
- Коли: сервер рендерить agents template
- Тоді: кнопки "Save", "Reset", "New Agent", "Delete" відсутні

**AC-13.5: GET /agents доступний для всіх ролей**
- Дано: viewer
- Коли: GET /api/agents
- Тоді: HTTP 200, список агентів

#### Edge Cases

- Developer переглядає конфігурацію агента з довгим промптом -- повний текст відображається (не обрізаний).
- Viewer натискає на агента в списку: відкривається read-only деталі.
- Editor змінює агента -- developer/viewer побачать зміни при наступному завантаженні.

#### Обмеження та допущення

- Вкладка Agents доступна для всіх ролей (перегляд конфігурації корисний для всіх).
- Конфігурація агентів відображається read-only через disabled поля або plain text.

---

### US-14: Управління учасниками -- тільки owner

**Проблема:** Дії з критичним впливом (зміна складу команди, зміна ролей) мають бути обмежені, бо помилка може призвести до втрати контролю над проектом.

**Як** owner проекту,  
**я хочу** бути єдиним (разом із superadmin через bypass), хто може змінювати ролі учасників, видаляти учасників та управляти заявками на вступ,  
**щоб** зберегти повний контроль над складом та правами команди.

**Пріоритет:** high (strategic bet -- критичний для безпеки)  
**Залежності:** US-1

#### Специфікація реалізації

1. API ендпоінти з `min_role="owner"`:
   - `PATCH /api/projects/{name}/members/{user_id}` -- зміна ролі
   - `DELETE /api/projects/{name}/members/{user_id}` -- видалення учасника
   - `PATCH /api/projects/{name}/join-requests/{id}` -- approve/reject заявки

2. UI:
   - Owner бачить dropdown зміни ролі (4 варіанти: viewer, developer, editor, owner) та кнопку Remove для кожного учасника.
   - Editor/developer/viewer бачать Members list з іменами та ролями, але без dropdown та кнопки Remove.
   - Вкладка "Join Requests" видима тільки для owner.

3. Dropdown зміни ролі:
   - Порядок: Viewer, Developer, Editor, Owner
   - Поточна роль виділена (selected)
   - Зміна ролі викликає HTMX PATCH запит

4. Новий учасник через approve заявки отримує роль viewer за замовчуванням.

#### Acceptance Criteria

**AC-14.1: PUT /members/{id}/role повертає 403 для editor, developer, viewer**
- Дано: editor
- Коли: PATCH /api/projects/my-app/members/42 з body `{"role": "developer"}`
- Тоді: HTTP 403

**AC-14.2: DELETE /members/{id} повертає 403 для editor, developer, viewer**
- Дано: developer
- Коли: DELETE /api/projects/my-app/members/42
- Тоді: HTTP 403

**AC-14.3: POST /join-requests/{id}/approve повертає 403 для editor, developer, viewer**
- Дано: editor
- Коли: PATCH /api/projects/my-app/join-requests/10 з body `{"action": "approve"}`
- Тоді: HTTP 403

**AC-14.4: Superadmin може виконати всі дії (bypass)**
- Дано: superadmin без membership
- Коли: PATCH /api/projects/my-app/members/42 з body `{"role": "developer"}`
- Тоді: HTTP 200

**AC-14.5: UI приховує dropdown та кнопки для не-owner**
- Дано: editor або developer переглядає Members
- Коли: сервер рендерить members template
- Тоді: dropdown зміни ролі та кнопка Remove відсутні в DOM

#### Edge Cases

- Owner підвищує viewer до owner -- тепер обидва мають повний контроль.
- Owner видаляє учасника з активною terminal-сесією -- сесія продовжує до завершення, наступний запит отримає 403.
- Superadmin може виконувати всі операції незалежно від наявності membership.
- Owner не може призначити собі роль нижче owner, якщо він єдиний owner (покрито US-15).

#### Обмеження та допущення

- Join Request approve/reject доступний тільки owner (не editor).
- Новий учасник через approve отримує роль viewer за замовчуванням.
- Superadmin bypass перевіряється до перевірки ролі.

---

### US-15: Захист від видалення/пониження останнього owner

**Проблема:** Якщо єдиний owner понизить себе або буде видалений, проект залишиться без управління.

**Як** owner проекту,  
**я хочу** щоб система не дозволяла видалити або понизити роль єдиного owner,  
**щоб** проект завжди мав хоча б одного owner.

**Пріоритет:** high (quick win -- одна перевірка, критична для безпеки)  
**Залежності:** US-14

#### Специфікація реалізації

1. Перед зміною ролі або видаленням учасника перевірити:
   ```python
   # Кількість owner у проєкті (включаючи поточного)
   owner_count = db.query(ProjectMembership).filter(
       ProjectMembership.project_id == project_id,
       ProjectMembership.role == "owner"
   ).count()
   
   if target_membership.role == "owner" and owner_count <= 1:
       raise HTTPException(400, "Project must have at least one owner")
   ```

2. Ця перевірка застосовується до:
   - `PATCH /members/{id}` -- зміна ролі (пониження owner)
   - `DELETE /members/{id}` -- видалення owner

3. Superadmin також НЕ може видалити/понизити єдиного owner.

#### Acceptance Criteria

**AC-15.1: Пониження єдиного owner повертає 400**
- Дано: owner, він єдиний owner проєкту
- Коли: PATCH /members/self з body `{"role": "editor"}`
- Тоді: HTTP 400 "Проект повинен мати хоча б одного owner"

**AC-15.2: Видалення єдиного owner повертає 400**
- Дано: owner, він єдиний owner
- Коли: DELETE /members/self
- Тоді: HTTP 400 з тим самим повідомленням

**AC-15.3: Owner може понизити себе, якщо є інший owner**
- Дано: 2 owner-и у проєкті
- Коли: PATCH /members/self з body `{"role": "editor"}`
- Тоді: HTTP 200, роль змінена на editor

**AC-15.4: Owner НЕ може понизити себе, якщо він єдиний**
- Дано: єдиний owner
- Коли: PATCH /members/self з body `{"role": "viewer"}`
- Тоді: HTTP 400

**AC-15.5: Superadmin також не може видалити/понизити єдиного owner**
- Дано: superadmin, проєкт з єдиним owner
- Коли: PATCH /members/{owner_id} з body `{"role": "editor"}`
- Тоді: HTTP 400 (не bypass)

#### Edge Cases

- Два owner-и: один понижує іншого до editor. Потім намагається понизити себе -- HTTP 400 (він тепер єдиний owner).
- Owner видаляє іншого owner, потім намагається видалити себе -- HTTP 400.
- Перевірка count має бути транзакційною: race condition, коли два owner-и одночасно понижують один одного -- один має отримати 400.

#### Обмеження та допущення

- Повідомлення помилки локалізоване (en/uk).
- Перевірка виконується ДО зміни в БД (оптимістичний підхід).
- Race condition мітигується через serializable transaction або SELECT FOR UPDATE.

---

### US-16: Відображення ролі developer у UI (бейджі, dropdown, каталог)

**Проблема:** Якщо UI не знає про нову роль, owner не зможе її призначити, а інтерфейс покаже некоректні дані.

**Як** користувач дашборду,  
**я хочу** бачити роль developer у списку учасників з відповідним бейджем, у dropdown зміни ролі та у каталозі проектів,  
**щоб** чітко розуміти рівень доступу кожного учасника.

**Пріоритет:** medium (quick win -- UI-зміни, мінімальний effort)  
**Залежності:** US-1, US-14

#### Специфікація реалізації

1. Members list:
   - Бейдж ролі "developer" з відповідним кольором (синій #3b82f6)
   - CSS-клас: `badge-developer`

2. Dropdown зміни ролі (owner only):
   - 4 варіанти в порядку: Viewer, Developer, Editor, Owner
   - Поточна роль selected

3. Catalog badge:
   - При перегляді каталогу проєктів показувати бейдж "Developer" для відповідних учасників

4. Стилі бейджів:
   ```css
   .badge-viewer { background: #6b7280; color: #fff; }
   .badge-developer { background: #3b82f6; color: #fff; }
   .badge-editor { background: #10b981; color: #fff; }
   .badge-owner { background: #f59e0b; color: #fff; }
   ```

#### Acceptance Criteria

**AC-16.1: Бейдж "developer" в Members list**
- Дано: учасник з роллю developer
- Коли: переглядаю Members tab
- Тоді: навпроти імені -- бейдж "Developer" синього кольору (#3b82f6)

**AC-16.2: Dropdown містить 4 варіанти**
- Дано: owner відкриває dropdown зміни ролі
- Коли: натискаю на dropdown
- Тоді: варіанти зверху вниз: Viewer, Developer, Editor, Owner

**AC-16.3: Catalog badge для developer**
- Дано: developer у проєкті "my-app"
- Коли: відкриваю каталог проєктів
- Тоді: навпроти "my-app" -- бейдж "Developer"

**AC-16.4: Dropdown відображається тільки для owner**
- Дано: editor переглядає Members
- Коли: дивлюсь на рядок учасника
- Тоді: dropdown відсутній, лише текстовий бейдж ролі

#### Edge Cases

- Owner змінює роль developer на viewer: бейдж миттєво оновлюється (HTMX swap).
- Довга таблиця учасників (20+): dropdown не обрізається viewport-ом (z-index, position).
- Mobile: dropdown адаптується під ширину екрану.
- Бейдж ролі owner самого себе: показується без dropdown (owner не може змінити свою роль через dropdown, якщо він єдиний).

#### Обмеження та допущення

- Бейджі ролей використовують CSS-класи (badge-viewer, badge-developer, badge-editor, badge-owner).
- Каталог показує конкретну роль тільки для поточного користувача, не для всіх учасників.
- Локалізація бейджів через i18n (покрито US-18).

---

### US-17: Приховання вкладок у навігації за роллю

**Проблема:** Якщо навігація показує вкладки, до яких у користувача немає прав, це створює плутанину та зайві 403 помилки.

**Як** користувач з обмеженою роллю,  
**я хочу** бачити лише доступні мені вкладки в навігації,  
**щоб** інтерфейс не показував функції, до яких у мене немає прав.

**Пріоритет:** high (strategic bet -- UX всієї системи ролей)  
**Залежності:** US-1, US-3, US-5, US-9

#### Специфікація реалізації

1. В `_topbar.html` перевіряти `user_role` для кожної вкладки:
   ```jinja2
   {% set role_rank = {"viewer": 0, "developer": 1, "editor": 2, "owner": 3} %}
   {% set rank = role_rank.get(user_role, 0) %}
   
   {% set tab_visibility = {
       'board': 0, 'archive': 0, 'agents': 0, 'artifacts': 0, 
       'members': 0, 'logs': 0,
       'pipeline': 1, 'terminal': 1, 'queue': 1, 'transcriber': 1,
       'backlog': 2,
       'join-requests': 3, 'settings': 3
   } %}
   
   {% for tab_id, tab_key in tabs %}
     {% if rank >= tab_visibility.get(tab_id, 0) %}
       <button class="tab" data-tab="{{ tab_id }}">{{ t(tab_key, lang) }}</button>
     {% endif %}
   {% endfor %}
   ```

2. Правила видимості:
   - viewer (rank 0): Board, Archive, Agents, Artifacts, Members, Logs -- 6 вкладок
   - developer (rank 1): + Pipeline (RO), Terminal, Queue (RO), Transcriber -- 10 вкладок
   - editor (rank 2): + Backlog -- 11 вкладок
   - owner (rank 3): + Join Requests, Settings -- 13 вкладок

3. Пряме введення URL прихованої вкладки -- серверна перевірка ролі, 403 HTML.

4. Mobile burger menu: приховані вкладки не з'являються в мобільному меню.

#### Acceptance Criteria

**AC-17.1: Viewer бачить 6 вкладок**
- Дано: viewer
- Коли: рендериться topbar
- Тоді: в DOM присутні: Board, Archive, Agents, Artifacts, Members, Logs

**AC-17.2: Developer бачить 10 вкладок**
- Дано: developer
- Коли: рендериться topbar
- Тоді: в DOM: Board, Archive, Agents, Artifacts, Members, Logs + Pipeline, Terminal, Queue, Transcriber

**AC-17.3: Editor бачить 11 вкладок**
- Дано: editor
- Коли: рендериться topbar
- Тоді: все що developer + Backlog

**AC-17.4: Owner бачить 13 вкладок**
- Дано: owner
- Коли: рендериться topbar
- Тоді: все що editor + Join Requests, Settings

**AC-17.5: Приховання через серверний рендеринг (не client-side JS)**
- Дано: viewer
- Коли: переглядаю HTML source коду сторінки
- Тоді: приховані вкладки відсутні в DOM (не display:none, а не рендеряться взагалі)

**AC-17.6: Пряме введення URL показує 403**
- Дано: viewer, вводить URL /ui/partials/tabs/pipeline
- Коли: сервер обробляє запит
- Тоді: HTTP 403 HTML сторінка "Insufficient permissions"

#### Edge Cases

- Роль змінилась під час сесії (owner змінив роль): зміни застосовуються при наступному HTMX запиті (tab load).
- Mobile burger menu: приховані вкладки не з'являються.
- URL з hash (#pipeline) для viewer: HTMX запит до partial повертає 403.

#### Обмеження та допущення

- Шаблони використовують `user_role` з контексту Jinja2.
- HTMX tab partials перевіряють роль на сервері при кожному запиті -- подвійний захист (UI + API).
- Елементи приховуються повністю (не рендеряться в DOM), а не disabled.

---

### US-18: Локалізація назв ролей (uk/en)

**Проблема:** Якщо нова роль developer не додана до i18n-файлів, користувачі побачать технічний ключ замість зрозумілої назви.

**Як** користувач дашборду,  
**я хочу** бачити назви ролей своєю мовою,  
**щоб** інтерфейс був зрозумілим незалежно від мови.

**Пріоритет:** medium (quick win -- мінімальний effort, 4 рядки в 2 файлах)  
**Залежності:** US-1, US-16

#### Специфікація реалізації

1. Додати ключі до `en.json`:
   ```json
   "role.viewer": "Viewer",
   "role.developer": "Developer",
   "role.editor": "Editor",
   "role.owner": "Owner",
   "error.insufficient_permissions": "Insufficient permissions",
   "error.requires_role": "Requires {role} role"
   ```

2. Додати ключі до `uk.json`:
   ```json
   "role.viewer": "Глядач",
   "role.developer": "Розробник",
   "role.editor": "Редактор",
   "role.owner": "Власник",
   "error.insufficient_permissions": "Недостатньо прав",
   "error.requires_role": "Потрібна роль {role}"
   ```

3. Бейджі ролей в шаблонах використовують `t('role.' + user_role, lang)`.

4. Dropdown зміни ролі також використовує i18n ключі.

#### Acceptance Criteria

**AC-18.1: en.json містить ключі ролей**
- Дано: файл en.json
- Коли: перевіряю наявність ключів
- Тоді: `role.viewer`, `role.developer`, `role.editor`, `role.owner` присутні

**AC-18.2: uk.json містить ключі з українськими перекладами**
- Дано: файл uk.json
- Коли: перевіряю значення `role.developer`
- Тоді: "Розробник"

**AC-18.3: 403 повідомлення локалізоване**
- Дано: developer, мова uk, спроба доступу до editor+ ендпоінту
- Коли: отримую HTTP 403
- Тоді: повідомлення "Недостатньо прав" або "Потрібна роль Редактор"

**AC-18.4: Жоден ключ ролі не залишається непереведеним**
- Дано: система запущена
- Коли: всі 4 ролі відображаються в UI
- Тоді: жодна роль не показує технічний ключ (role.developer) замість перекладу

#### Edge Cases

- Перемикання мови під час перегляду Members list: ролі перекладаються при наступному HTMX запиті.
- API error messages: detail повертається англійською для сумісності, UI може показувати локалізовану версію.
- Fallback: якщо ключ відсутній -- показувати англійську назву ролі (не пустий рядок).

#### Обмеження та допущення

- Назви ролей в БД зберігаються англійською (viewer, developer, editor, owner).
- Локалізація відбувається тільки в UI-шарі (шаблони).
- API detail повертається англійською для зворотної сумісності.

---

## 4. Технічна реалізація (високий рівень)

### 4.1 Backend

| Файл | Зміни | US |
|---|---|---|
| `dashboard/auth/permissions.py` | ROLE_RANK + require_developer | US-1 |
| `dashboard/db/models/project.py` | Коментар до role field | US-1 |
| `dashboard/migrations/versions/009_*.py` | Міграція (CHECK constraint) | US-2 |
| `dashboard/routers/projects.py` | _check_project_access, members CRUD, last owner check | US-3, US-14, US-15 |
| `dashboard/routers/ui.py` | Передавати user_role в шаблони, перевірка ролі в tab_partial | US-17 |
| `dashboard/routers/terminal.py` | require_developer замість require_editor | US-5 |
| `dashboard/routers/pipeline.py` | Розмежування developer (GET) та editor (POST) | US-6, US-11 |
| `dashboard/routers/queue.py` | Розмежування developer (GET) та editor (POST) | US-7, US-12 |

### 4.2 Frontend

| Файл | Зміни | US |
|---|---|---|
| `dashboard/templates/partials/_topbar.html` | Фільтрація tab-ів за роллю | US-17 |
| `dashboard/templates/partials/tabs/_board.html` | Приховання кнопок за роллю | US-3, US-10 |
| `dashboard/templates/partials/tabs/_backlog.html` | Перевірка editor+ | US-9 |
| `dashboard/templates/partials/tabs/_pipeline.html` | Read-only для developer | US-6, US-11 |
| `dashboard/templates/partials/tabs/_terminal.html` | Перевірка developer+ | US-5 |
| `dashboard/static/lang/en.json` | Рядки ролей + помилок | US-18 |
| `dashboard/static/lang/uk.json` | Рядки ролей + помилок | US-18 |
| `dashboard/static/css/dashboard.css` | Стилі бейджів developer | US-16 |

### 4.3 Рекомендований порядок впровадження

```
Sprint 1 -- Foundation (3-4 дні):
  US-1   ROLE_RANK + require_developer         -- 0.5 дня
  US-2   Міграція Alembic                      -- 0.5 дня
  US-17  Приховання вкладок (Jinja2)           -- 1 день
  US-18  Локалізація (en.json + uk.json)       -- 0.25 дня
  Buffer                                       -- 0.5 дня

Sprint 2 -- Access Control (3-4 дні):
  US-3, US-10 Viewer read-only Board           -- 1 день
  US-9   Захист backlog (editor+)              -- 0.5 дня
  US-5   Developer terminal access             -- 0.5 дня
  US-6, US-4 Pipeline permissions              -- 1 день
  Buffer                                       -- 0.5 дня

Sprint 3 -- Polish & Edge Cases (2-3 дні):
  US-11  Pipeline edit protection              -- 0.5 дня
  US-13  Agents edit protection                -- 0.25 дня
  US-7, US-12 Queue permissions                -- 0.5 дня
  US-14, US-15 Owner members + last protection -- 0.5 дня
  US-16  Developer UI бейджі                   -- 0.5 дня
  US-8   Транскрайбер (якщо scope уточнено)    -- 0.25 дня
  Buffer                                       -- 0.5 дня
```

**Загальна оцінка:** 8-10 людино-днів + 20% buffer = 10-12 людино-днів (2-3 спринти)

---

## 5. Ризики

| Ризик | Ймовірність | Вплив | Мітигація |
|---|:---:|:---:|---|
| Hard-coded rank numbers в коді | Середня | Високий | Grep по ROLE_RANK та числовим порівнянням перед релізом |
| Superadmin bypass ламається | Низька | Високий | Superadmin bypass перевіряється ДО ROLE_RANK порівняння |
| UI елементи видимі через DevTools | - | Низький | API перевірка -- основний бар'єр, UI -- UX |
| Pipeline readOnly mode drawflow | Середня | Середній | Drawflow має readOnly API, потребує тестування |
| Race condition при пониженні owner | Низька | Високий | SELECT FOR UPDATE або serializable transaction |
| Rollback developer->viewer втрата даних | Низька | Середній | Повідомити owner перед rollback, developer->viewer безпечно |

---

## 6. Definition of Done

- [ ] ROLE_RANK = {"viewer": 0, "developer": 1, "editor": 2, "owner": 3}
- [ ] require_developer dependency доступний
- [ ] Всі API ендпоінти перевіряють мінімальну роль згідно з матрицею (розділ 2)
- [ ] Шаблони приховують UI елементи через Jinja2 `{% if %}` (не client-side)
- [ ] Локалізація ролей en/uk (8 ключів)
- [ ] Alembic міграція з downgrade стратегією
- [ ] Last owner protection (400 при пониженні/видаленні єдиного owner)
- [ ] Бейджі ролей з відповідними кольорами (viewer: сірий, developer: синій, editor: зелений, owner: золотий)
- [ ] Dropdown зміни ролі містить 4 варіанти (owner only)
- [ ] Manual testing: створити по одному користувачу кожної ролі, перевірити кожну вкладку та API
- [ ] Superadmin bypass працює коректно
- [ ] Mobile burger menu: приховані вкладки не з'являються

---

## 7. Граф залежностей

```
US-1 (базова роль developer)
 |
 +-- US-2  (міграція БД)
 |
 +-- US-3  (viewer read-only)
 |    +-- US-4  (viewer: pipeline статус на Board)
 |    |    +-- US-6  (developer: pipeline + логи read-only)
 |    |         +-- US-11 (editor: pipeline edit protection)
 |    +-- US-9  (захист backlog)
 |    +-- US-10 (захист board actions)
 |
 +-- US-5  (developer: термінал)
 |
 +-- US-7  (developer: queue read-only)
 |    +-- US-12 (editor: queue management)
 |
 +-- US-8  (developer: транскрайбер -- потребує уточнення)
 |
 +-- US-13 (editor: agents edit)
 |
 +-- US-14 (owner: members management)
 |    +-- US-15 (last owner protection)
 |    +-- US-16 (developer у UI)
 |         +-- US-18 (локалізація)
 |
 +-- US-17 (tab navigation)
      (залежить від US-3, US-5, US-9)
```
