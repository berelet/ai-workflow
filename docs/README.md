# AI Workflow — Повна документація

AI Workflow — мультиагентна система автоматизації повного циклу розробки програмного забезпечення. Система координує роботу спеціалізованих AI-агентів, кожен з яких відповідає за свій етап: від збору вимог до коміту коду.

Цей документ — вичерпний довідник для розробників системи.

## Зміст

- [Архітектура](#архітектура)
- [Структура файлів](#структура-файлів)
- [Оркестратор](#оркестратор)
- [Агенти](#агенти)
  - [PM — Проджект-менеджер](#pm--проджект-менеджер)
  - [BA — Бізнес-аналітик](#ba--бізнес-аналітик)
  - [Designer — Дизайнер](#designer--дизайнер)
  - [DEV — Розробник](#dev--розробник)
  - [QA — Тестувальник](#qa--тестувальник)
  - [PERF — Performance Reviewer](#perf--performance-reviewer)
- [Пайплайн розробки](#пайплайн-розробки)
  - [Етапи детально](#етапи-детально)
  - [Подвійний прохід (Double Pass)](#подвійний-прохід-double-pass)
  - [Повернення на доопрацювання](#повернення-на-доопрацювання)
  - [Формат pipeline.md](#формат-pipelinemd)
  - [Етап COMMIT](#етап-commit)
- [Discovery-пайплайн](#discovery-пайплайн)
- [Skills та Review](#skills-та-review)
  - [Механізм injection](#механізм-injection)
  - [Маппінг skills на етапи](#маппінг-skills-на-етапи)
  - [Формат звіту ревью](#формат-звіту-ревью)
- [Шаблони артефактів](#шаблони-артефактів)
- [Конфігурація проєктів](#конфігурація-проєктів)
  - [pipeline-config.json — повна схема](#pipeline-configjson--повна-схема)
  - [backlog.json — схема](#backlogjson--схема)
  - [Pipeline graph — формат JSON](#pipeline-graph--формат-json)
  - [Кастомні агенти](#кастомні-агенти)
  - [Кастомні skills](#кастомні-skills)
  - [Git-правила](#git-правила)
- [CLI](#cli)
  - [Аргументи командного рядка](#аргументи-командного-рядка)
  - [Інтерактивний режим](#інтерактивний-режим)
  - [Провайдери та моделі](#провайдери-та-моделі)
  - [Збірка промпту](#збірка-промпту)
- [Дашборд](#дашборд)
  - [API-ендпоінти](#api-ендпоінти)
  - [WebSocket](#websocket)
  - [Вкладки](#вкладки)
  - [Голосовий ввід/вивід](#голосовий-ввідвивід)
  - [Збереження сесій](#збереження-сесій)
- [Deployment](#deployment)
- [Менеджер сервісів (run.sh)](#менеджер-сервісів-runsh)
- [Транскрайбер (Whisper)](#транскрайбер-whisper)
- [Телеметрія та логування](#телеметрія-та-логування)
- [Figma MCP](#figma-mcp)
- [Допоміжні утиліти](#допоміжні-утиліти)
- [Конфігурація середовища](#конфігурація-середовища)
- [Усунення проблем](#усунення-проблем)

---

## Архітектура

```
┌─────────────────────────────────────────────────────────┐
│                      CLI / Дашборд                       │
│              (cli.py / dashboard/server.py)               │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                     Оркестратор                          │
│              (orchestrator/instructions.md)               │
│                                                          │
│  Маршрутизація задач між агентами за графом пайплайну    │
└────┬──────┬──────┬──────┬──────┬──────┬──────┬──────────┘
     │      │      │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼      ▼      ▼
   PM → PM_R → BA → BA_R → DES → DEV → DEV_R → QA → QA_R → PERF → COMMIT
     │                                    │
     │         Якщо QA = FAIL             │
     │◄───────────────────────────────────┘
     │         (баг-репорт → DEV)

┌─────────────────────────────────────────────────────────┐
│               Зберігання артефактів                      │
│         <project_dir>/.ai-workflow/artifacts/             │
└─────────────────────────────────────────────────────────┘
```

Ключові принципи:

- **Оркестратор** працює з однієї сесії та викликає субагентів для кожного етапу
- **Артефакт-центричність** — кожен етап читає вхідні артефакти і створює вихідні
- **Подвійний прохід** — базовий агент + ревью-агент зі skills
- **Файлова система як стейт** — весь стан зберігається у файлах `.ai-workflow/`

---

## Структура файлів

### Кореневий каталог системи

```
ai-workflow/
├── orchestrator/               # Оркестратор — інструкції маршрутизації
│   └── instructions.md
├── project-manager/            # PM-агент
│   └── instructions.md
├── business-analyst/           # BA-агент
│   └── instructions.md
├── designer/                   # Дизайнер
│   ├── instructions.md
│   ├── render.js               # HTML → PNG рендерер (Puppeteer)
│   └── html-to-figma.js        # Конвертер HTML → Figma
├── developer/                  # DEV-агент
│   └── instructions.md
├── tester/                     # QA-агент
│   ├── instructions.md
│   └── test_ac.py              # Утиліта тестування acceptance criteria
├── performance-reviewer/       # PERF-агент
│   └── instructions.md
├── discovery-interview/        # Discovery: інтерв'ю
│   └── instructions.md
├── discovery-analysis/         # Discovery: аналіз
│   └── instructions.md
├── discovery-decomposition/    # Discovery: декомпозиція
│   └── instructions.md
├── discovery-confirmation/     # Discovery: підтвердження
│   └── instructions.md
├── dashboard/                  # Веб-дашборд
│   ├── server.py               # FastAPI бекенд
│   ├── structured_logger.py    # Структуроване JSON-логування
│   ├── index.html              # SPA фронтенд
│   ├── static/                 # Статичні файли (Drawflow, CSS)
│   │   ├── lib/drawflow.min.js
│   │   ├── lib/drawflow.min.css
│   │   └── css/drawflow_fixes.css
│   └── requirements.txt        # Python залежності
├── config/                     # Конфігурація
│   ├── .env.example            # Шаблон змінних оточення
│   ├── projects.example.json   # Шаблон реєстру сервісів
│   ├── tessl.json              # Залежності skills
│   └── package.json            # Node.js залежності
├── docs/                       # Документація
│   ├── README.md               # Цей файл
│   ├── CLAUDE.md               # Інструкції для Claude Code
│   ├── AGENTS.md               # Маппінг агентів на skills
│   ├── CLI.md                  # Документація CLI
│   ├── cli-quick.md            # Швидкий довідник CLI
│   ├── spec.md                 # Приклад специфікації
│   ├── user-stories.md         # Приклад user stories
│   ├── user-stories-reviewed.md # Приклад reviewed user stories
│   ├── ai-workflow-full-description.txt # Опис для презентацій
│   └── prds/                   # Product Requirement Documents
├── shared/templates/           # Шаблони артефактів
│   ├── user-story.md
│   ├── spec.md
│   ├── bug-report.md
│   └── test-result.md
├── runtime/                    # Рантайм (gitignored)
│   ├── projects.json           # Реєстр сервісів
│   ├── logs/                   # Логи
│   └── uploads/                # Завантаження
├── projects/                   # Реєстр проєктів
│   └── <проєкт>/
│       ├── pipeline-config.json
│       └── pipelines/          # Кастомні пайплайни
│           └── *.json
├── .tessl/                     # Skills-бібліотека
│   ├── RULES.md                # Загальні правила агентів
│   └── tiles/                  # Skills (SKILL.md файли)
├── figma-mcp/                  # MCP-міст Cursor AI ↔ Figma
├── transcriber/                # Whisper транскрайбер
├── cli.py                      # CLI для запуску проєктів
├── run.sh                      # Менеджер сервісів
├── .env                        # Локальна конфігурація (gitignored)
└── .gitignore
```

### Робочі файли проєкту

Кожен підключений проєкт зберігає свої дані в `<project_dir>/.ai-workflow/`:

```
<project_dir>/.ai-workflow/
├── project.md                  # Опис, стек, архітектура, шлях, git workflow
├── backlog.json                # Беклог задач [{id, task, description, priority, status}]
├── backlog.md                  # Беклог у markdown (автогенерація)
├── pipeline.md                 # Статус пайплайну (таблиця етапів)
├── git-rules.md                # Правила git workflow для COMMIT-агента
├── agents/                     # Кастомні інструкції агентів (опціонально)
│   ├── pm.md
│   ├── ba.md
│   ├── dev.md
│   └── ...
└── artifacts/                  # Артефакти задач
    ├── discovery/              # Результати discovery-фази
    │   ├── interview.md
    │   └── confirmation.md
    └── task-N/                 # Артефакти задачі N
        ├── user-stories.md     # PM: user stories (оригінал)
        ├── user-stories-reviewed.md  # PM Review: покращена версія
        ├── pm-review.md        # PM Review: звіт
        ├── spec.md             # BA: специфікація (оригінал)
        ├── spec-reviewed.md    # BA Review: покращена версія
        ├── ba-review.md        # BA Review: звіт
        ├── wireframe.html      # BA: wireframe
        ├── *.html              # Designer: HTML/Tailwind макети
        ├── *.png               # Designer: рендери
        ├── design-notes.md     # Designer: дизайн-рішення
        ├── changes.md          # DEV: опис змін
        ├── code-changes/       # DEV: структуровані зміни
        │   └── changes.json
        ├── dev-review.md       # DEV Review: звіт
        ├── test-result.md      # QA: результат (PASS)
        ├── bug-report.md       # QA: баг-репорт (FAIL)
        ├── qa-review.md        # QA Review: звіт
        └── perf-review.md      # PERF: звіт продуктивності
```

---

## Оркестратор

Файл: `orchestrator/instructions.md`

Оркестратор — центральний мозок системи. Він керує потоком задач між агентами, працюючи з однієї сесії та викликаючи субагентів для кожного етапу.

### Обов'язки

1. **Маршрутизація задач** — визначає поточний етап і викликає відповідного агента
2. **Управління контекстом** — передає артефакти між етапами
3. **Skills injection** — підвантажує skills для review-агентів (читає SKILL.md і передає в промпт)
4. **Стан пайплайну** — оновлює `pipeline.md` після кожного етапу
5. **Обробка помилок** — повертає задачу на DEV при баг-репорті від QA або критичних зауваженнях PERF

### Команди користувача

Це команди для AI-оркестратора **всередині чату** (не аргументи CLI):

| Команда | Дія |
|---------|-----|
| `проєкт <назва>` | Переключитися на проєкт, прочитати `project.md` |
| `статус` | Показати `pipeline.md` |
| `беклог` | Показати `backlog.md` |
| `візьми задачу [N]` | Взяти задачу з беклогу, запустити пайплайн |
| `далі` | Наступний етап пайплайну |
| `покажи результат` | Показати артефакт поточного етапу |
| `контекст` | Показати project.md |
| `стек` | Показати технологічний стек |
| `етап` | Показати поточний етап |
| `коміт` | Виконати коміт (якщо QA = PASS) |
| `редизайн` | Запустити discovery повторно |
| `discovery` | Запустити discovery-пайплайн |

### Як оркестратор знаходить файли проєкту

1. Читає `projects/<проєкт>/pipeline-config.json`
2. Бере поле `project_dir` — абсолютний шлях до папки проєкту
3. Всі робочі файли знаходяться в `<project_dir>/.ai-workflow/`
4. Для кастомних агентів перевіряє `<project_dir>/.ai-workflow/agents/<agent>.md` — якщо є, використовує замість глобальних

### Після кожного етапу

1. Показує користувачу короткий результат
2. Якщо був Skills Review — показує підсумок: скільки зауважень, що виправлено, які skills застосовано
3. Оновлює `pipeline.md`
4. Якщо QA = PASS — оновлює статус задачі в `backlog.json` на `done`
5. Питає: "Продовжити? Скажи 'далі' або дай коментар"

---

## Агенти

### PM — Проджект-менеджер

Файл: `project-manager/instructions.md`

**Роль:** Декомпозиція задач на user stories.

**Вхід:**
- Задача з беклогу
- `project.md` — контекст проєкту

**Вихід:**
- `user-stories.md` — user stories за шаблоном `shared/templates/user-story.md`

**Правила:**
- Кожна user story — атомарна (одна функція, один результат)
- Формат: "Як [роль], я хочу [дія], щоб [цінність]"
- Пріоритет: high / medium / low
- Залежності між stories якщо є
- Не писати код, не писати технічні деталі реалізації

### BA — Бізнес-аналітик

Файл: `business-analyst/instructions.md`

**Роль:** Специфікації, acceptance criteria, wireframes.

**Вхід:**
- `user-stories-reviewed.md` — покращені user stories від PM Review
- Контекст проєкту

**Вихід:**
- `spec.md` — специфікація за шаблоном `shared/templates/spec.md`
- `wireframe.html` — HTML wireframe

**Правила специфікації:**
- Кожен AC — перевірюваний: формат "Дано / Коли / Тоді"
- Описувати edge cases
- Вказувати обмеження та допущення

**Правила wireframe:**
- HTML зі вбудованими стилями
- Сірі блоки (#e0e0e0, #f5f5f5) для контейнерів
- Placeholder-текст для контенту
- Структура: header, main, sidebar, footer
- Кожен екран — окрема секція з заголовком
- Анотації — підписи до елементів (що це, як працює)
- Адаптивний layout (flexbox/grid), max-width 1200px
- Семантичні HTML теги

### Designer — Дизайнер

Файл: `designer/instructions.md`

**Роль:** HTML/Tailwind дизайн на основі wireframe.

**Вхід:**
- `wireframe.html` — wireframe від BA
- `spec-reviewed.md` — покращена специфікація
- `project.md` — стек, стиль, бренд

**Вихід:**
- HTML файли з Tailwind CSS (по одному на екран) — файли самодостатні, всі стилі inline
- PNG рендери кожного екрана
- `design-notes.md` — дизайн-рішення по кожному екрану

**Правила:**
- Слідувати wireframe — не додавати екрани/елементи яких немає
- Tailwind CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- Мінімум 16px для body тексту
- Контрастність тексту: WCAG AA (4.5:1)
- Відступи кратні 4px (Tailwind: p-1, p-2, p-4, p-6, p-8, p-12)
- Семантичні HTML теги
- Іконки: Heroicons/Lucide через SVG inline, без зовнішніх зображень
- Адаптивний дизайн (mobile-first)

**Рендеринг у PNG:**
```bash
node designer/render.js output/screen-name.html output/screen-name.png
```

### DEV — Розробник

Файл: `developer/instructions.md`

**Роль:** Реалізація коду за специфікацією.

**Вхід:**
- `spec-reviewed.md` — специфікація з AC
- `wireframe.html` — wireframe
- `design-notes.md` — дизайн-рішення (якщо є)
- `project.md` — стек, архітектура
- `bug-report.md` — баг-репорт (при поверненні від QA)

**Вихід:**
- Код у цільовому проєкті
- `changes.md` — опис змін (які файли, що додано/змінено)
- `code-changes/changes.json` — структурований лог змін (JSON)

**Правила:**
- Слідувати архітектурі та стеку проєкту
- Мінімальний код — тільки те, що потрібно за спекою (YAGNI)
- Не змінювати існуючі тести
- У нових класах/модулях додавати коментар: `# See: docs/needs/NEED-XXX-назва/`

### QA — Тестувальник

Файл: `tester/instructions.md`

**Роль:** Перевірка коду на відповідність специфікації.

**Вхід:**
- `spec-reviewed.md` — специфікація з AC
- `changes.md` — що зробив розробник
- `dev-review.md` — результати code review
- Код у цільовому проєкті

**Вихід (один з двох):**
- `test-result.md` зі статусом PASS — всі AC пройдені
- `bug-report.md` зі статусом FAIL — знайдені баги (за шаблоном `shared/templates/bug-report.md`)

**Правила:**
- Перевіряти кожен AC окремо
- Баг-репорт: кроки відтворення, очікуваний результат, фактичний результат, серйозність (critical/major/minor)
- Перевіряти edge cases зі специфікації

**Утиліта:** `tester/test_ac.py` — скрипт для автоматичної перевірки acceptance criteria.

### PERF — Performance Reviewer

Файл: `performance-reviewer/instructions.md`

**Роль:** Аудит продуктивності перед комітом.

**Вхід:**
- `changes.md` — опис змін
- `dev-review.md` — результати code review
- Змінені файли коду

**Вихід:**
- `perf-review.md` — звіт продуктивності з розділами: критичні проблеми та рекомендації

**Що перевіряє:**

Backend:
- N+1 запити до бази даних
- Неоптимальні SQL-запити
- Відсутність кешування
- Connection pooling
- Блокуючі операції в async коді
- Витоки пам'яті
- Важкі операції в hot path

Frontend:
- Core Web Vitals (LCP, CLS, INP)
- Bundle size
- Lazy loading
- Рендеринг і перемальовування

**Рішення:**
- Критичні проблеми → повернути на DEV (статус FAIL)
- Тільки рекомендації → продовжити до COMMIT (статус PASS)

---

## Пайплайн розробки

### Етапи детально

Кожна задача проходить через ланцюжок етапів:

```
PM → PM Review → BA → BA Review → Design → DEV → DEV Review → QA → QA Review → PERF → COMMIT
```

| # | Етап | Агент | Вхід | Вихід |
|---|------|-------|------|-------|
| 1 | PM | project-manager | задача з беклогу | `user-stories.md` |
| 2 | PM Review | PM + skills | `user-stories.md` | `user-stories-reviewed.md`, `pm-review.md` |
| 3 | BA | business-analyst | `user-stories-reviewed.md` | `spec.md`, `wireframe.html` |
| 4 | BA Review | BA + skills | `spec.md` | `spec-reviewed.md`, `ba-review.md` |
| 5 | Design | designer | `spec-reviewed.md`, `wireframe.html` | HTML, PNG, `design-notes.md` |
| 6 | DEV | developer | `spec-reviewed.md`, wireframe, design-notes | код + `changes.md` + `code-changes/changes.json` |
| 7 | DEV Review | DEV + skills | `changes.md`, код | виправлений код, `dev-review.md` |
| 8 | QA | tester | `spec-reviewed.md`, `changes.md` | `test-result.md` або `bug-report.md` |
| 9 | QA Review | QA + skills | `test-result.md` | `qa-review.md` |
| 10 | PERF | performance-reviewer | `changes.md`, `dev-review.md` | `perf-review.md` |
| 11 | COMMIT | git | `git-rules.md` | коміт у develop |

### Подвійний прохід (Double Pass)

Кожен етап з ревью складається з двох кроків:

1. **Базовий агент** — працює за своїми інструкціями, без зовнішніх skills. Створює артефакт-оригінал (наприклад, `user-stories.md`).
2. **Skills Review** — ревью-агент отримує артефакт-оригінал + контент SKILL.md файлів із `.tessl/tiles/`. Перевіряє артефакт за правилами skills і створює покращену версію (наприклад, `user-stories-reviewed.md`) та звіт (`pm-review.md`).

Це дозволяє бачити різницю: що зробив агент сам vs що покращили skills.

### Формат звіту ревью

```markdown
📋 Skills Review (PM): N зауважень знайдено, N виправлено
Застосовані skills: [список із конкретними правилами]

### Зауваження

1. **[Що не так]**
   - Правило: [назва skill] → [конкретне правило]
   - Виправлення: [що саме змінено або рекомендація]
```

### Повернення на доопрацювання

Якщо QA знаходить баг:
1. QA створює `bug-report.md`
2. Оркестратор оновлює `pipeline.md` — статус "повернення на доопрацювання"
3. При команді "далі" — оркестратор запускає DEV знову з баг-репортом у контексті
4. DEV читає `bug-report.md` і виправляє код
5. Повторний прохід: DEV → DEV Review → QA → ...

Якщо PERF знаходить критичні проблеми — аналогічне повернення на DEV.

### Формат pipeline.md

```markdown
| Задача | Етап | Статус | Артефакт |
|--------|------|--------|----------|
| #1 Опис | PM | done | .ai-workflow/artifacts/task-1/user-stories.md |
| #1 Опис | PM Review | done (3 зауваження) | .ai-workflow/artifacts/task-1/pm-review.md |
| #1 Опис | BA | done | .ai-workflow/artifacts/task-1/spec.md |
| #1 Опис | DEV | done | .ai-workflow/artifacts/task-1/changes.md |
| #1 Опис | QA | PASS | .ai-workflow/artifacts/task-1/test-result.md |
| #1 Опис | PERF | done (0 критичних) | .ai-workflow/artifacts/task-1/perf-review.md |
```

### Етап COMMIT

Виконується ТІЛЬКИ якщо QA = PASS і PERF не має критичних проблем.

1. Перевірити гілку: `git branch --show-current` — має бути `develop`
2. Перевірити чеклист з `git-rules.md`
3. Сформувати коміт за шаблоном з `git-rules.md`
4. Показати користувачу повідомлення коміту і запитати підтвердження
5. Після підтвердження: `git push origin develop`

---

## Discovery-пайплайн

Discovery — 4-етапний процес для нових проєктів, який генерує `project.md` і `backlog.json`.

Етапи discovery визначаються в `pipeline-config.json` → поле `discovery_stages`.

Для кожного етапу оркестратор перевіряє наявність кастомних інструкцій у `<project_dir>/.ai-workflow/agents/<agent>.md`. Якщо є — використовує їх, якщо ні — глобальні з відповідної папки.

### Етап 1: Інтерв'ю

Агент: `discovery-interview`

Продуктовий аналітик проводить структуроване інтерв'ю з користувачем для збору контексту.

**Принципи:**
- Питання порціями по 3-5 штук
- Від широких до деталей
- Розпливчасті відповіді — перепитувати
- Фіксувати суперечності та уточнювати
- Не пропонувати рішення — тільки збирати інформацію

**Блоки питань:**

1. **Суть і ціль** — що робить продукт, яку проблему вирішує, для кого, аналоги, scope
2. **Цільова аудиторія** — ролі, масштаб, B2B/B2C
3. **Ключові фічі** — головні дії, критичні user flows, MVP scope, real-time вимоги
4. **Технічні обмеження** — стек, хостинг, інтеграції, безпека, мобільний/веб
5. **Контекст** — бюджет, строки, команда, існуючий дизайн/код

**Артефакт:** `<project_dir>/.ai-workflow/artifacts/discovery/interview.md`

### Етап 2: Аналіз

Агент: `discovery-analysis`

Технічний аналітик формує повний опис проєкту на основі інтерв'ю.

**Секції project.md:**

1. **Опис** — 2-3 речення: продукт, проблема, аудиторія
2. **Цільова аудиторія** — основні та вторинні користувачі, контекст
3. **Стек технологій** — з обґрунтуванням кожного вибору (1 рядок на технологію)
4. **Архітектура** — тип (моноліт/мікросервіси), компоненти, структура директорій, порти, взаємодія
5. **Шлях до проєкту** — абсолютний шлях
6. **Git Workflow** — гілка розробки, стратегія комітів, merge/deploy правила
7. **Деплой** — хостинг, метод, CI/CD
8. **Документація** — посилання на існуючі документи/макети

**Принципи вибору стеку:**
- Якщо користувач вказав — слідувати
- Якщо ні — зрілість, екосистема, швидкість розробки
- Для MVP — простіше краще (моноліт > мікросервіси, SQLite > PostgreSQL для прототипу)

**Артефакт:** `<project_dir>/.ai-workflow/project.md`

### Етап 3: Декомпозиція

Агент: `discovery-decomposition`

Проджект-менеджер розбиває проєкт на задачі для беклогу.

**Порядок задач:**
1. Інфраструктура — ініціалізація, Docker, БД
2. Ядро — базові моделі, сутності
3. Авторизація — реєстрація, логін, ролі
4. MVP-фічі — ключові user flows
5. Вторинні фічі — покращення, оптимізації
6. Деплой — хостинг, CI/CD
7. Полірування — UI/UX, документація, тести

**Правила:**
- Кожна задача атомарна — один результат, що можна перевірити
- Не більше 1-2 днів роботи
- Опис достатній для розробника
- Не дублювати задачі
- Не додавати задачі типу "дослідження" чи "планування"
- Залежності документувати ("після задачі #N")

**Пріоритети:**
- `high` — без цього проєкт не працює (MVP-critical)
- `medium` — важливо, але можна відкласти
- `low` — nice to have

**Кількість задач:**
- Малий проєкт (лендинг): 5-10
- Середній (веб-додаток): 10-20
- Великий (платформа): 20-40

**Артефакт:** `<project_dir>/.ai-workflow/backlog.json`

### Етап 4: Підтвердження

Агент: `discovery-confirmation`

Фінальний ревʼюер показує підсумки і отримує підтвердження.

**Що робить:**

1. Показує зведення: назва, стек, архітектура, кількість задач
2. Перевіряє чеклист повноти:
   - [ ] project.md має опис, стек, архітектуру, шлях
   - [ ] Стек обґрунтований і відповідає обмеженням
   - [ ] Архітектура описана з компонентами та структурою
   - [ ] Шлях до проєкту вказано
   - [ ] Git workflow визначено
   - [ ] Беклог містить задачі з пріоритетами
   - [ ] Задачі впорядковані за залежностями
   - [ ] Описи задач достатньо детальні
   - [ ] Немає дублікатів
   - [ ] Всі фічі з інтерв'ю покриті задачами
3. Виявляє прогалини
4. Питає підтвердження: "ок" / "правки" / "додай задачу"

**Артефакт:** `<project_dir>/.ai-workflow/artifacts/discovery/confirmation.md`

---

## Skills та Review

Skills — це набори правил і best practices з `.tessl/tiles/`, які ревью-агенти застосовують для перевірки артефактів.

### Встановлення skills

Skills керуються через `config/tessl.json` і встановлюються командою:
```bash
tessl install
```

Файли підтягуються в `.tessl/tiles/<провайдер>/<репозиторій>/.../<назва>/SKILL.md`.

### Механізм injection

Як оркестратор використовує skills:

1. Читає `projects/<проєкт>/pipeline-config.json`
2. Бере масив `skills` для поточного етапу + масив `global`
3. Для кожного skill **читає вміст файлу** `.tessl/tiles/<шлях>` (файл SKILL.md)
4. **Вставляє повний вміст SKILL.md у промпт** ревью-агента як контекст
5. Ревью-агент перевіряє артефакт за правилами з кожного skill
6. Якщо `skills` не вказано в конфігу — використовує дефолтні з `docs/AGENTS.md`

### Маппінг skills на етапи

| Skill | Шлях у `.tessl/tiles/` | Де застосовується |
|-------|----------------------|-------------------|
| **Software Security** | `cisco/software-security/SKILL.md` | Глобальний — весь код |
| **Systematic Debugging** | `secondsky/.../systematic-debugging/SKILL.md` | Глобальний — при багах |
| **PM Toolkit** | `alirezarezvani/.../product-manager-toolkit/SKILL.md` | PM Review |
| **Requirements Clarity** | `softaworks/.../requirements-clarity/SKILL.md` | BA Review |
| **FastAPI Python** | `mindrally/skills/fastapi-python/SKILL.md` | DEV Review (backend) |
| **React TypeScript** | `softaworks/.../react-dev/SKILL.md` | DEV Review (frontend) |
| **API Testing** | `secondsky/.../api-testing/SKILL.md` | DEV Review (API) |
| **Webapp Testing** | `anthropics/.../webapp-testing/SKILL.md` | QA Review |
| **Web Performance Audit** | `secondsky/.../web-performance-audit/SKILL.md` | PERF |
| **Performance Optimization** | `sickn33/.../application-performance.../SKILL.md` | PERF |
| **Performance Profiling** | `sickn33/.../performance-profiling/SKILL.md` | PERF |

### Формат звіту ревью

Кожен ревью-агент генерує звіт у форматі:

```markdown
📋 Skills Review (<Етап>): N зауважень знайдено, N виправлено
Застосовані skills: [назва skill 1], [назва skill 2]

### Зауваження

1. **[Опис проблеми]**
   - Правило: [назва skill] → [конкретне правило, яке порушено]
   - Виправлення: [що виправлено або рекомендація]

2. ...

### Підсумок
- Зауважень: N
- Виправлено: N
- Рекомендацій: N
```

### Кастомні skills для проєкту

В `pipeline-config.json` можна перевизначити набір skills:

```json
{
  "skills": {
    "global": ["cisco/software-security/SKILL.md"],
    "PM_REVIEW": ["alirezarezvani/.../product-manager-toolkit/SKILL.md"],
    "BA_REVIEW": ["softaworks/.../requirements-clarity/SKILL.md"],
    "DEV_REVIEW": ["mindrally/skills/fastapi-python/SKILL.md"],
    "QA_REVIEW": ["anthropics/.../webapp-testing/SKILL.md"],
    "PERF": ["secondsky/.../web-performance-audit/SKILL.md"]
  }
}
```

---

## Шаблони артефактів

Шаблони знаходяться в `shared/templates/`. Агенти використовують їх для створення стандартизованих артефактів.

### user-story.md

```markdown
# User Story: [Назва]

**Пріоритет:** high | medium | low
**Залежності:** немає | US-XX

## Опис

Як [роль], я хочу [дія], щоб [цінність].

## Замітки

- ...
```

### spec.md

```markdown
# Специфікація: [Назва]

**User Story:** US-XX
**Статус:** draft | review | approved

## Опис

...

## Acceptance Criteria

### AC-1: [Назва]
- **Дано:** ...
- **Коли:** ...
- **Тоді:** ...

## Edge Cases

- ...

## Обмеження та допущення

- ...
```

### bug-report.md

```markdown
# Баг-репорт: [Назва]

**AC:** AC-XX
**Серйозність:** critical | major | minor

## Кроки відтворення

1. ...

## Очікуваний результат

...

## Фактичний результат

...
```

### test-result.md

```markdown
# Результат тестування

**Дата:** ...
**Специфікація:** ...
**Статус:** PASS | FAIL

## Результати по AC

| AC | Статус | Коментар |
|----|--------|----------|
| AC-1 | PASS/FAIL | ... |
```

---

## Конфігурація проєктів

### pipeline-config.json — повна схема

Файл `projects/<проєкт>/pipeline-config.json`:

```json
{
  "stages": [
    "PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"
  ],
  "project_dir": "/абсолютний/шлях/до/проєкту",
  "discovery_stages": [
    {"name": "interview", "agent": "discovery-interview", "description": "Інтерв'ю"},
    {"name": "analysis", "agent": "discovery-analysis", "description": "Аналіз"},
    {"name": "decomposition", "agent": "discovery-decomposition", "description": "Декомпозиція"},
    {"name": "confirmation", "agent": "discovery-confirmation", "description": "Підтвердження"}
  ],
  "skills": {
    "global": ["cisco/software-security/SKILL.md"],
    "PM_REVIEW": ["alirezarezvani/.../product-manager-toolkit/SKILL.md"],
    "BA_REVIEW": ["softaworks/.../requirements-clarity/SKILL.md"],
    "DEV_REVIEW": ["mindrally/skills/fastapi-python/SKILL.md"],
    "QA_REVIEW": ["anthropics/.../webapp-testing/SKILL.md"],
    "PERF": [
      "secondsky/.../web-performance-audit/SKILL.md",
      "sickn33/.../application-performance.../SKILL.md",
      "sickn33/.../performance-profiling/SKILL.md"
    ]
  }
}
```

| Поле | Тип | Обов'язкове | Опис |
|------|-----|:-----------:|------|
| `stages` | string[] | так | Етапи пайплайну (можна прибрати непотрібні) |
| `project_dir` | string | так | Абсолютний шлях до кореня проєкту |
| `discovery_stages` | object[] | ні | Етапи для нового проєкту |
| `skills` | object | ні | Кастомні skills для review-етапів. Ключі: `global`, `PM_REVIEW`, `BA_REVIEW`, `DEV_REVIEW`, `QA_REVIEW`, `PERF` |

### backlog.json — схема

Файл `<project_dir>/.ai-workflow/backlog.json`:

```json
[
  {
    "id": 1,
    "task": "Ініціалізація проєкту",
    "description": "Створити структуру: Django project + app 'core'. Settings, Docker, requirements.txt.",
    "priority": "high",
    "status": "todo",
    "images": []
  }
]
```

| Поле | Тип | Значення | Опис |
|------|-----|----------|------|
| `id` | number | 1, 2, 3... | Унікальний ідентифікатор задачі |
| `task` | string | | Коротка назва задачі |
| `description` | string | | Детальний опис для розробника |
| `priority` | string | `high` / `medium` / `low` | Пріоритет |
| `status` | string | `todo` / `in-progress` / `done` | Статус |
| `images` | string[] | | Масив імен файлів зображень (опціонально) |

### Pipeline graph — формат JSON

Кастомні пайплайни зберігаються в `projects/<проєкт>/pipelines/*.json`. Формат — Drawflow JSON:

```json
{
  "drawflow": {
    "Home": {
      "data": {
        "1": {
          "id": 1,
          "name": "PM",
          "data": {
            "agent": "project-manager",
            "prompt": "",
            "skills": []
          },
          "class": "agent-node",
          "inputs": {},
          "outputs": {
            "output_1": {
              "connections": [{"node": "2", "output": "input_1"}]
            }
          },
          "pos_x": 100,
          "pos_y": 200
        },
        "2": {
          "id": 2,
          "name": "PM_REVIEW",
          "data": {
            "agent": "project-manager",
            "prompt": "",
            "skills": ["alirezarezvani/.../product-manager-toolkit/SKILL.md"]
          },
          "class": "reviewer-node",
          "inputs": {
            "input_1": {
              "connections": [{"node": "1", "input": "output_1"}]
            }
          },
          "outputs": {
            "output_1": {
              "connections": [{"node": "3", "output": "input_1"}]
            }
          },
          "pos_x": 300,
          "pos_y": 200
        }
      }
    }
  }
}
```

| Поле вузла | Опис |
|------------|------|
| `name` | Назва етапу (PM, BA, DEV, тощо) |
| `data.agent` | Ідентифікатор агента (project-manager, business-analyst, тощо) |
| `data.prompt` | Кастомний промпт для вузла (опціонально) |
| `data.skills` | Масив шляхів до skills (для reviewer-вузлів) |
| `class` | `agent-node` або `reviewer-node` |
| `inputs` / `outputs` | Зв'язки між вузлами |

### Кастомні агенти

Створіть файл `<project_dir>/.ai-workflow/agents/<stage>.md` — він замінить глобальні інструкції для цього агента.

Підтримувані файли: `pm.md`, `ba.md`, `dev.md`, `qa.md`, `perf.md`, `discovery-interview.md`, `discovery-analysis.md`, `discovery-decomposition.md`, `discovery-confirmation.md`.

### Кастомні skills

В `pipeline-config.json` → поле `skills`. Шляхи відносно `.tessl/tiles/`.

### Git-правила

Файл `<project_dir>/.ai-workflow/git-rules.md` визначає:
- Гілку розробки
- Формат повідомлень комітів
- Правила merge/deploy
- Чеклист перед комітом

Агент COMMIT читає цей файл і дотримується правил.

---

## CLI

Файл: `cli.py`

Інтерактивний термінал для запуску проєктів у tmux-сесіях.

### Аргументи командного рядка

```bash
python3 cli.py [проєкт] [опції]

Опції:
  --task, -t "текст"        Задача для агента
  --pipeline, -p ID         ID пайплайну (з pipelines/*.json)
  --stage, -s ЕТАП          Початковий етап (PM, BA, DEV, QA, PERF, COMMIT)
  --provider, -c ПРОВАЙДЕР  AI-провайдер (kiro, claude)
  --model, -m МОДЕЛЬ        Модель AI
```

**Приклади:**
```bash
python3 cli.py my-project
python3 cli.py my-project --task "Додати авторизацію"
python3 cli.py my-project --provider claude --model sonnet
python3 cli.py my-project --stage DEV --task "Виправити баг"
python3 cli.py my-project --pipeline custom-pipeline
```

### Інтерактивний режим

Якщо запустити без аргументів — відкриється меню:
1. Вибір проєкту (за номером, активні позначені ●)
2. Введення задачі (Enter = інтерактив)
3. Вибір пайплайну
4. Вибір провайдера
5. Вибір етапу
6. Вибір моделі

Кожен проєкт запускається в окремому tmux-вікні.

### Провайдери та моделі

| Провайдер | Команда | Моделі | За замовчуванням |
|-----------|---------|--------|------------------|
| `kiro` | `kiro-cli chat --trust-all-tools` | Auto, Claude Sonnet 4.6, Claude 3.7 Sonnet, Claude 3.5 Sonnet v2 | Auto |
| `claude` | `claude` | Sonnet 4.6, Opus 4.6, Haiku 4.5 | Sonnet 4.6 |

### Збірка промпту

CLI збирає промпт для AI-агента з контексту проєкту (`build_prompt()`):

1. **Інструкції оркестратора** — `orchestrator/instructions.md`
2. **Контекст проєкту** — `project.md`, `backlog.json`, `pipeline.md`
3. **Git-правила** — `git-rules.md`
4. **Поточний етап** — автовизначення з `pipeline.md`
5. **Граф пайплайну** — інформація про початковий вузол та наступний етап
6. **Інструкції агента** — для поточного етапу (проєктні або глобальні)
7. **Skills** — вміст SKILL.md файлів для review-етапів та PERF
8. **Задача користувача** — текст задачі або промпт за замовчуванням

Промпт зберігається в `.cli-prompts/<проєкт>.txt` і передається обраному AI-провайдеру.

**Автовизначення етапу:** CLI парсить `pipeline.md` і знаходить останній завершений етап, щоб визначити наступний. Також витягує ID задачі з тексту команди.

---

## Дашборд

Файл: `dashboard/server.py` (бекенд), `dashboard/index.html` (фронтенд)

Веб-дашборд на FastAPI для моніторингу та керування проєктами.

**Стек:**
- Бекенд: FastAPI, WebSocket, pexpect, python-dotenv
- Фронтенд: Vanilla HTML/JS, Drawflow.js (візуальний конструктор пайплайнів)
- Стиль: кастомна темна тема, шрифт Roboto Mono

**Запуск:**
```bash
./run.sh start ai-workflow-dashboard
# або
uvicorn dashboard.server:app --host 0.0.0.0 --port 9000
```

URL: http://localhost:9000/

### API-ендпоінти

#### Файловий браузер

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/browse` | Перегляд файлів та директорій (параметр `path`) |

#### Проєкти

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/projects` | Список всіх проєктів |
| POST | `/api/projects` | Створити новий проєкт |
| GET | `/api/projects/{name}` | Деталі проєкту (project.md, backlog, pipeline, git-rules) |
| DELETE | `/api/projects/{name}` | Видалити проєкт |
| GET | `/api/projects/{name}/pipeline-config` | Конфігурація пайплайну |
| PUT | `/api/projects/{name}/pipeline-config` | Оновити конфігурацію пайплайну |

#### Беклог

| Метод | Шлях | Опис |
|-------|------|------|
| POST | `/api/projects/{name}/backlog` | Додати задачу в беклог |
| PUT | `/api/projects/{name}/backlog/{item_id}` | Оновити задачу (статус, опис, пріоритет) |
| DELETE | `/api/projects/{name}/backlog/{item_id}` | Видалити задачу |
| POST | `/api/projects/{name}/backlog/{item_id}/images` | Завантажити зображення до задачі |
| DELETE | `/api/projects/{name}/backlog/{item_id}/images/{filename}` | Видалити зображення задачі |
| GET | `/uploads/{name}/{filename}` | Отримати завантажений файл |

#### Пайплайни

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/projects/{name}/pipelines` | Список пайплайнів проєкту |
| POST | `/api/projects/{name}/pipelines` | Створити новий пайплайн |
| GET | `/api/projects/{name}/pipelines/{pl_id}` | Отримати пайплайн (Drawflow JSON) |
| PUT | `/api/projects/{name}/pipelines/{pl_id}` | Оновити пайплайн |
| DELETE | `/api/projects/{name}/pipelines/{pl_id}` | Видалити пайплайн |
| PUT | `/api/projects/{name}/pipeline` | Оновити pipeline.md |

#### Агенти

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/agents` | Список глобальних агентів |
| GET | `/api/agents/{agent}/instructions` | Інструкції глобального агента |
| PUT | `/api/agents/{agent}/instructions` | Оновити інструкції глобального агента |
| GET | `/api/agents/{agent}/artifacts` | Артефакти агента (input/output) |
| GET | `/api/projects/{name}/agents` | Проєктні інструкції агентів |
| PUT | `/api/projects/{name}/agents/{agent}` | Оновити проєктні інструкції агента |
| DELETE | `/api/projects/{name}/agents/{agent}` | Скинути до глобальних інструкцій |

#### Skills

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/skills` | Список всіх доступних skills (назва, опис, агент, джерело) |

#### Артефакти

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/projects/{name}/artifacts` | Список артефактів усіх задач |
| GET | `/api/projects/{name}/artifacts/{task_id}/{filename}` | Конкретний файл артефакту |
| GET | `/api/projects/{name}/artifacts/{task_id}/code-changes` | Структуровані зміни коду (changes.json) |

#### Телеметрія

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/telemetry` | Логи телеметрії (параметр `lines` — кількість рядків) |
| DELETE | `/api/telemetry` | Очистити логи телеметрії |

#### Deployment

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/projects/{name}/deploy-info` | Інформація: git tags, коміти, гілка, шлях до репозиторію |
| POST | `/api/projects/{name}/deploy` | Деплой: merge develop→main, створення тегу, push |

Тіло запиту POST `/api/projects/{name}/deploy`:
```json
{
  "version_type": "minor",
  "tag_message": "Release v1.2.0"
}
```

`version_type`: `major` / `minor` / `patch`

#### Транскрайбер

| Метод | Шлях | Опис |
|-------|------|------|
| POST | `/api/transcriber/upload` | Завантажити аудіофайл (WebM, WAV, MP3, M4A, OGG) |
| GET | `/api/transcriber/recordings` | Список записів зі статусом транскрипції |
| POST | `/api/transcriber/transcribe/{filename}` | Транскрибувати аудіо через faster-whisper |
| DELETE | `/api/transcriber/recordings/{filename}` | Видалити запис та транскрипцію |

#### Сервіси

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/api/services` | Список сервісів зі статусом (running/stopped), портами, health |
| POST | `/api/services/start` | Запустити сервіси (тіло: `{"services": ["name1", "name2"]}`) |
| POST | `/api/services/stop` | Зупинити сервіси (тіло: `{"services": ["name1", "name2"]}`) |

#### UI

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/` | Головна сторінка дашборду (index.html) |

### WebSocket

**Шлях:** `/ws/terminal`

Мультисесійний термінал для запуску AI-агентів у реальному часі.

**Повідомлення від клієнта:**

```json
{"type": "start", "project": "my-project", "prompt": "візьми задачу 1", "model": "sonnet", "provider": "claude", "session_id": "uuid"}
```

```json
{"type": "input", "data": "далі"}
```

```json
{"type": "stop"}
```

**Повідомлення від сервера:**

```json
{"type": "output", "data": "текст відповіді агента"}
```

```json
{"type": "session_id", "data": "claude-session-abc123"}
```

```json
{"type": "exit", "code": 0}
```

### Вкладки

**Беклог** — Kanban-дошка з трьома колонками: Todo, In Progress, Done.
- Фільтри по статусу (all / todo / in-progress / done)
- Кольорові індикатори пріоритету (high — червоний, medium — жовтий, low — зелений)
- Drag-and-drop між колонками
- Завантаження зображень до задач
- Створення / редагування / видалення задач через модальні форми
- Синхронізація статусу з pipeline.md

**Pipeline** — Візуальний конструктор на Drawflow.
- Створення / перейменування / видалення пайплайнів
- Додавання вузлів (agent-node, reviewer-node)
- Налаштування вузлів (подвійний клік): агент, промпт, skills
- Бейджі типу вузла (Reviewer vs Agent)
- Індикатор незбережених змін
- Масштабування з відображенням рівня zoom
- Автопідбір skills з дефолтних налаштувань

**Агенти** — Список агентів з інструкціями.
- Глобальні агенти (з `orchestrator/`, `project-manager/`, тощо)
- Проєктні агенти (з `<project_dir>/.ai-workflow/agents/`)
- Редагування інструкцій через UI
- Скидання проєктних до глобальних

**Артефакти** — Перегляд артефактів задач.
- Навігація по задачах (task-1, task-2, ...)
- Перегляд файлів: специфікації, wireframes, код, тести
- Перегляд structured code changes

**Термінал** — Вбудований термінал для AI-агентів.
- Мультисесійність (окрема сесія на кожен проєкт)
- Збереження Claude session ID для продовження сесій
- Вибір провайдера та моделі
- Start / Stop / Resume
- Real-time потокове виведення через WebSocket
- Введення команд у активну сесію

**Запис** — Транскрайбер.
- Запис мікрофону браузера (getUserMedia)
- Запис системного звуку (getDisplayMedia)
- Мікшування аудіо-джерел через Web Audio API
- Таймер запису в реальному часі
- Кодування WebM/Opus
- Попередній перегляд з відтворенням
- Транскрипція через faster-whisper
- Превʼю тексту (1000 символів) та повний перегляд
- Розмір файлу та видалення

**Сервіси** — Керування локальними сервісами.
- Статус з кольоровими індикаторами (running / stopped)
- Порт та шлях до директорії
- Git-посилання на репозиторій
- Масовий запуск / зупинка
- Health check

**Логи** — Перегляд телеметрії пайплайну.
- Кольорова класифікація подій (SKILLS_REVIEW, SKILLS_APPLIED, STAGE_START, TOOL_USE, FILE_OP, QA_RESULT, ERROR тощо)
- Панель статистики з підрахунком подій за типами
- Парсинг JSON-логів
- Останні 200 рядків (налаштовується)
- Авто-прокрутка донизу

**+ Новий проєкт** — Створення проєкту.
- Форма: назва, шлях до директорії
- Запуск discovery-пайплайну
- Автовизначення нового / існуючого проєкту

### Голосовий ввід/вивід

Вкладка Термінал підтримує голосову взаємодію:

**Voice Input (Web Speech API):**
- Кнопка мікрофона для активації розпізнавання мови
- Мова розпізнавання: українська/російська
- Interim та final транскрипція
- Автоперезапуск при обриві з'єднання
- Візуальна індикація активного стану

**Text-to-Speech (TTS):**
- Кнопка увімкнення/вимкнення озвучення відповідей
- Мова: українська/російська
- Налаштовувана швидкість мовлення
- Індикатор ON/OFF

### Збереження сесій

Термінал дашборду підтримує збереження та відновлення сесій Claude:

1. При запуску нової сесії Claude генерується session ID
2. Сервер перехоплює session ID з виводу Claude та відправляє клієнту
3. Клієнт зберігає session ID для проєкту
4. При наступному запуску session ID передається через WebSocket
5. CLI використовує `--resume` з цим ID для продовження сесії

---

## Deployment

Дашборд має вбудований deployment workflow з семантичним версіонуванням.

### Отримання інформації

`GET /api/projects/{name}/deploy-info` повертає:

```json
{
  "current_tag": "v1.1.0",
  "commits_since_tag": 5,
  "branch": "develop",
  "repo_path": "/path/to/project",
  "recent_commits": [
    {"hash": "abc123", "message": "feat: add auth", "date": "2025-01-15"}
  ]
}
```

### Виконання деплою

`POST /api/projects/{name}/deploy` виконує:

1. Merge `develop` → `main`
2. Створення нового git tag (семантичне версіонування)
3. Push тегу та гілки main

**Типи версій:**
- `major` — v1.0.0 → v2.0.0 (зламні зміни)
- `minor` — v1.0.0 → v1.1.0 (нові фічі)
- `patch` — v1.0.0 → v1.0.1 (виправлення)

---

## Менеджер сервісів (run.sh)

Файл: `run.sh`

Bash-скрипт для керування локальними сервісами. Читає конфігурацію з `runtime/projects.json`.

```bash
./run.sh start [проєкт|all]    # Запустити проєкт(и) у фоні
./run.sh stop  [проєкт|all]    # Зупинити проєкт(и)
./run.sh status                # Статус всіх проєктів
./run.sh list                  # Список проєктів з портами
./run.sh logs <проєкт>         # Логи проєкту (останні 50 рядків)
```

**Конфігурація сервісу** (`runtime/projects.json`):

```json
{
  "my-project": {
    "port": 8000,
    "dir": "/шлях/до/проєкту",
    "venv": "venv",
    "cmd": "uvicorn app.main:app --host 0.0.0.0 --port 8000",
    "log": "server.log",
    "health": "http://localhost:8000/health"
  }
}
```

| Поле | Тип | Опис |
|------|-----|------|
| `port` | number | Порт сервісу |
| `dir` | string | Абсолютний шлях до директорії проєкту |
| `venv` | string / null | Шлях до venv відносно `dir` (або `null` якщо не потрібен) |
| `cmd` | string | Команда запуску |
| `log` | string | Файл логів відносно `dir` |
| `health` | string | URL для health check (до 10 секунд очікування) |

**Особливості:**
- Перевірка залежності `jq` при запуску
- Health check polling (до 10 секунд)
- Активація Python venv перед запуском
- nohup для фонового виконання
- Перевірка зайнятості порту через `lsof`

---

## Транскрайбер (Whisper)

Вбудований транскрайбер — запис аудіо через браузер та транскрипція через [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

### Встановлення

```bash
source venv/bin/activate
pip install faster-whisper

# GPU-прискорення (опціонально, CUDA 12+)
pip install faster-whisper[gpu]
```

> Системні вимоги для GPU: NVIDIA GPU + CUDA 12 + cuDNN 9. Без GPU працює на CPU.

### Налаштування

В `.env`:
```env
TRANSCRIBER_DIR=/шлях/до/transcriber
```

Структура директорії:
```
transcriber/
├── transcribe.sh    # Скрипт транскрипції
├── recordings/      # Записи (автостворення)
└── output/          # Текстові транскрипції
```

### Моделі Whisper

| Модель | Розмір | RAM (CPU) | VRAM (GPU) | Якість |
|--------|--------|-----------|------------|--------|
| `tiny` | 75 MB | ~1 GB | ~1 GB | Низька, швидка |
| `base` | 142 MB | ~1 GB | ~1 GB | Базова |
| `small` | 466 MB | ~2 GB | ~2 GB | Добра |
| `medium` | 1.5 GB | ~5 GB | ~4 GB | Висока (рекомендована) |
| `large-v3` | 3.1 GB | ~10 GB | ~6 GB | Найвища |

### Можливості запису

- **Мікрофон браузера** — getUserMedia API
- **Системний звук** — getDisplayMedia API (запис звуку з інших додатків)
- **Мікшування** — одночасний запис мікрофону та системного звуку через Web Audio API
- **Формати** — WebM, WAV, MP3, M4A, OGG

---

## Телеметрія та логування

Файл: `dashboard/structured_logger.py`

Система структурованого JSON-логування для телеметрії пайплайну.

### Формат логів

Кожен рядок — окремий JSON-об'єкт:

```json
{
  "timestamp": "2025-01-15T14:30:00.123456Z",
  "level": "INFO",
  "event": "STAGE_START",
  "session_id": "abc-123",
  "project": "my-project",
  "data": {
    "stage": "DEV",
    "task_id": 1
  }
}
```

| Поле | Опис |
|------|------|
| `timestamp` | UTC ISO-8601 (RFC3339) |
| `level` | DEBUG / INFO / WARNING / ERROR |
| `event` | Тип події |
| `session_id` | Ідентифікатор сесії |
| `project` | Назва проєкту |
| `data` | Додаткові дані (опціонально) |

### Типи подій

| Подія | Опис | Колір у дашборді |
|-------|------|-----------------|
| `STAGE_START` | Початок етапу | синій |
| `STAGE_END` | Завершення етапу | зелений |
| `SKILLS_REVIEW` | Запуск skills review | фіолетовий |
| `SKILLS_APPLIED` | Skills застосовано | бірюзовий |
| `TOOL_USE` | Використання інструменту | сірий |
| `FILE_OP` | Операція з файлом | жовтий |
| `QA_RESULT` | Результат QA (PASS/FAIL) | зелений/червоний |
| `ERROR` | Помилка | червоний |
| `SESSION_START` | Початок сесії | синій |
| `SESSION_END` | Завершення сесії | сірий |

### Безпека логів

- Санітизація вводу: видалення CR/LF та контрольних символів для запобігання log injection
- Всі рядкові дані проходять через `sanitize()` перед записом

---

## Figma MCP

Директорія: `figma-mcp/`

MCP (Model Context Protocol) інтеграція між Cursor AI та Figma.

**Можливості:**
- Читання дизайнів Figma програмно
- Масова заміна текстового контенту
- Поширення override'ів на інстанси компонентів
- Автоматизоване оновлення дизайнів через AI

**Стек:** TypeScript/Bun, WebSocket, MCP protocol.

**Запуск:**
```bash
cd figma-mcp
./start.sh
```

> Потребує SSL-сертифікати (`cert.pem`, `key.pem`) та конфігурацію каналу (`channel.json`).

---

## Допоміжні утиліти

### designer/render.js

Puppeteer-скрипт для рендерингу HTML-файлів у PNG-скріншоти.

```bash
node designer/render.js input.html output.png
```

Використовує headless Chrome для рендерингу. Потребує встановлений Chrome/Chromium:
```bash
npx puppeteer browsers install chrome
```

### designer/html-to-figma.js

Конвертер HTML-макетів у формат Figma для імпорту.

### tester/test_ac.py

Утиліта для автоматичної перевірки acceptance criteria з специфікації.

### dashboard/structured_logger.py

Модуль структурованого JSON-логування (див. [Телеметрія та логування](#телеметрія-та-логування)).

---

## Конфігурація середовища

### .env

Файл `.env` (gitignored) містить налаштування для конкретної машини:

| Змінна | Опис | За замовчуванням |
|--------|------|------------------|
| `TRANSCRIBER_DIR` | Абсолютний шлях до директорії транскрайбера | `./transcriber` |
| `DEFAULT_CLI` | CLI для запуску агентів: `kiro-cli` або `claude` | `kiro-cli` |
| `DEFAULT_MODEL` | Модель AI для агентів | `claude-opus-4.6` |

### config/tessl.json

Керує залежностями skills. При `tessl install` підтягує потрібні skills в `.tessl/tiles/`.

### config/package.json

Node.js залежності:
- `puppeteer-core` — рендер HTML → PNG
- `jsdom` — парсинг HTML

### config/projects.example.json

Шаблон для `runtime/projects.json` — реєстр локальних сервісів.

### dashboard/requirements.txt

Python залежності дашборду:
- `fastapi` — веб-фреймворк
- `uvicorn` — ASGI-сервер
- `python-dotenv` — завантаження .env
- `pexpect` — управління термінальними сесіями

---

## Усунення проблем

| Проблема | Причина | Рішення |
|----------|---------|---------|
| `tmux: command not found` | tmux не встановлено | `sudo apt install tmux` (Ubuntu) або `brew install tmux` (macOS) |
| `jq: command not found` | jq не встановлено | `sudo apt install jq` (Ubuntu) або `brew install jq` (macOS) |
| Порт зайнятий при запуску сервісу | Інший процес використовує порт | `lsof -i :<порт>` → `kill <PID>`, або змініть порт у `runtime/projects.json` |
| Puppeteer не рендерить PNG | Chrome/Chromium не встановлено | `npx puppeteer browsers install chrome` |
| faster-whisper: CUDA not found | Немає GPU або CUDA | Працюватиме на CPU автоматично. Для GPU: CUDA 12 + cuDNN 9 |
| `ModuleNotFoundError: pexpect` | Не встановлено залежності | `pip install -r dashboard/requirements.txt` |
| Skills не знайдено (порожній .tessl/tiles/) | Skills не встановлено | `tessl install` у кореневій папці |
| Дашборд не запускається | venv не активовано | `source venv/bin/activate && ./run.sh start ai-workflow-dashboard` |
| Claude session expired | Сесія закінчилась | Перезапустіть сесію в терміналі — новий session ID створюється автоматично |
| Помилка WebSocket у терміналі | Сервер перезапущено | Оновіть сторінку, з'єднання відновиться |
| tmux: session not found | Немає активної сесії | `python3 cli.py` — створить нову сесію |
| Pipeline graph порожній | Немає пайплайнів для проєкту | Створіть пайплайн через вкладку Pipeline або додайте JSON в `projects/<проєкт>/pipelines/` |
| Агент не бачить проєктних інструкцій | Файл не в тому місці | Перевірте шлях: `<project_dir>/.ai-workflow/agents/<stage>.md` |

---

## Ліцензія

Внутрішній інструмент команди.
