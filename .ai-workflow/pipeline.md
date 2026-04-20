# Pipeline — AI Workflow

## Задача #1 — Транскрайбер — интеграция в дашборд

| Этап | Агент | Статус |
|------|-------|--------|
| 1 | developer | ✅ done |

**Артефакт DEV:** Реализовано напрямую (server.py + index.html)

## Задача #6 — Редактирование карточек на морде

| Этап | Агент | Статус |
|------|-------|--------|
| PM | project-manager | ✅ done |
| BA | business-analyst | ✅ done |
| DEV | developer | ✅ done |
| QA | tester | ✅ done (PASS) |
| COMMIT | — | pending |

## Задача #7 — Редактирование изображений в карточке задачи

| Этап | Агент | Статус |
|------|-------|--------|
| PM | project-manager | ✅ done |
| BA | business-analyst | ✅ done |
| DEV | developer | ✅ done |
| QA | tester | ✅ done (PASS) |
| COMMIT | — | — |

## Задача #8 — Проработать изменение дизайна системы

| Этап | Агент | Статус |
|------|-------|--------|
| Анализ | orchestrator | ✅ done |

**Результат:** Выделены 12 UI-элементов, создано 12 задач на редизайн (#9–#20) в бэклоге.

## Задача #9 — Редизайн: Глобальные стили и дизайн-токены

| Этап | Агент | Статус |
|------|-------|--------|
| PM | project-manager | ✅ done |
| BA | business-analyst | ✅ done |
| DEV | developer | ✅ done |
| QA | tester | ✅ done (PASS) |
| COMMIT | — | pending |

## Задача #10 — Редизайн: Topbar

| Этап | Агент | Статус |
|------|-------|--------|
| PM | project-manager | ✅ done |
| BA | business-analyst | ✅ done |
| DEV | developer | ✅ done |
| QA | tester | ✅ done (PASS) |
| COMMIT | — | ⏭ skipped (git не инициализирован) |

## Задача #36 — Компетенции в карточке студента (ментор)

| Этап | Агент | Статус |
|------|-------|--------|
| DEV | developer | ✅ done |
| QA | tester | pending |

**Артефакты:**
- User stories: `.ai-workflow/artifacts/task-36/user-stories.md`
- Spec: `.ai-workflow/artifacts/task-36/spec.md`

**Реализация:**
- Компонент `CompetencyMatrixEditor.tsx` — редактируемая матрица компетенций
- Обновлен endpoint `/api/enrollments` — добавлен фильтр по `student_id`
- Обновлена страница студента ментора — интегрирован редактор компетенций

## Задача #31 — Пагинация на всех списках (backend + frontend)

| Этап | Агент | Статус |
|------|-------|--------|
| DEV | developer | ✅ done |
| QA | tester | pending |

**Реализация:**
- Создана схема `PaginatedResponse` в `api/schemas/pagination.py`
- Добавлена пагинация в endpoints: `/api/users`, `/api/tickets`, `/api/knowledge/materials`, `/api/enrollments`
- Создан компонент `Pagination.tsx` — адаптивная пагинация (desktop: номера страниц, mobile: компактный вид)
- Обновлены страницы: `admin/users`, `mentor/tickets` — интегрирована пагинация
- Параметры пагинации: `skip` (default: 0), `limit` (default: 20, max: 100)
- Формат ответа: `{items: [...], total: int, page: int, pages: int}`

## Задача #4 — Транскрайбер — выбор модели и прогресс

| Этап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-4/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done (11 замечаний) | .ai-workflow/artifacts/task-4/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-4/spec.md |
| BA Review | ba-skills-reviewer | ✅ done (8 замечаний, 80→93) | .ai-workflow/artifacts/task-4/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-4/design.html |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-4/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (4 замечания) | .ai-workflow/artifacts/task-4/dev-review.md |
| QA | tester | ❌ FAIL (5/25) | .ai-workflow/artifacts/task-4/test-result.md |
| DEV (fix) | developer | ✅ done (5 багов исправлено) | |
| QA (retest) | tester | ✅ PASS (25/25) | .ai-workflow/artifacts/task-4/test-result-retest.md |
| QA Review | qa-skills-reviewer | ✅ done (5 находок) | .ai-workflow/artifacts/task-4/qa-review.md |
| PERF | perf-reviewer | ✅ done (0 критичных) | .ai-workflow/artifacts/task-4/perf-review.md |
| DEV (fix2) | developer | ✅ done (8 исправлений) | |
| COMMIT | | ⏳ ready | |

## Задача #22 — Visibility при создании проекта

| Этап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-22/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done (16 замечаний) | .ai-workflow/artifacts/task-22/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-22/spec.md |
| BA Review | ba-skills-reviewer | ✅ done (9 замечаний, 70→90) | .ai-workflow/artifacts/task-22/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-22/wireframe.html |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-22/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (11 замечаний, 6 исправлено) | .ai-workflow/artifacts/task-22/dev-review.md |
| QA | tester | ✅ PASS (22/22) | .ai-workflow/artifacts/task-22/test-result.md |
| QA Review | qa-skills-reviewer | ✅ done (3 FAIL → исправлено) | .ai-workflow/artifacts/task-22/qa-review.md |
| PERF | perf-reviewer | ✅ done (0 критичных) | .ai-workflow/artifacts/task-22/perf-review.md |
| COMMIT | orchestrator | ✅ done (68938f7) | pushed to aiworkflow_2.0 |

## Задача #23 — Каталог публічних проєктів

| Етап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-23/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done (14 зауважень) | .ai-workflow/artifacts/task-23/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-23/spec.md, wireframe.html |
| BA Review | ba-skills-reviewer | ✅ done (18 зауважень, 73→92) | .ai-workflow/artifacts/task-23/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-23/catalog-design.html, join-requests-design.html, design-notes.md |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-23/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (6 зауважень, 5 виправлено) | .ai-workflow/artifacts/task-23/dev-review.md |
| QA | tester | ✅ PASS (56/66, 3 medium виправлено) | .ai-workflow/artifacts/task-23/test-result.md |
| QA Review | qa-skills-reviewer | ✅ done (37 PASS, 3 FAIL, 16 NOTE + 15/15 Playwright PASS) | .ai-workflow/artifacts/task-23/qa-review.md |
| PERF | perf-reviewer | ✅ done (2 WARNING виправлено, 0 критичних) | .ai-workflow/artifacts/task-23/perf-review.md |
| COMMIT | orchestrator | ✅ done (e29e66e) | pushed to aiworkflow_2.0 |

## Задача #24 — Система заявок на участь (сповіщення, мої заявки, відкликання, фільтри)

| Етап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-24/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done (14 зауважень) | .ai-workflow/artifacts/task-24/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-24/spec.md, wireframe.html |
| BA Review | ba-skills-reviewer | ✅ done (78→93) | .ai-workflow/artifacts/task-24/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-24/design.html, design-notes.md |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-24/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (8 зауважень, 8 виправлено) | .ai-workflow/artifacts/task-24/dev-review.md |
| QA | tester | ✅ PASS (22/23 → виправлено → 23/23) | .ai-workflow/artifacts/task-24/test-result.md |
| QA Review | qa-skills-reviewer | ✅ done (21 PASS, 8 FAIL — не критичні) | .ai-workflow/artifacts/task-24/qa-review.md |
| PERF | perf-reviewer | ✅ done (0 критичних, 4 WARNING) | .ai-workflow/artifacts/task-24/perf-review.md |
| COMMIT | orchestrator | ✅ done (75be04b) | pushed to aiworkflow_2.0 |

## Задача #26 — Enforce visibility в list/access

| Етап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-26/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done | .ai-workflow/artifacts/task-26/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-26/spec.md, wireframe.html |
| BA Review | ba-skills-reviewer | ✅ done | .ai-workflow/artifacts/task-26/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-26/design.html, design-notes.md |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-26/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (7 зауважень, 7 виправлено) | .ai-workflow/artifacts/task-26/dev-review.md |
| QA | tester | ✅ PASS (25/25) | .ai-workflow/artifacts/task-26/test-result.md |
| QA Review | qa-skills-reviewer | ✅ done (10 перевірок, 6 PASS, 4 FAIL — 2 виправлено, 2 pre-existing) | .ai-workflow/artifacts/task-26/qa-review.md |
| PERF | perf-reviewer | ✅ done (1 критичний виправлено, 2 medium виправлено) | .ai-workflow/artifacts/task-26/perf-review.md |
| COMMIT | orchestrator | ✅ done (52a24aa) | pushed to aiworkflow_2.0 |

## Задача #27 — UI управління учасниками

| Етап | Агент | Статус | Артефакт |
|------|-------|--------|----------|
| PM | project-manager | ✅ done | .ai-workflow/artifacts/task-27/user-stories.md |
| PM Review | pm-skills-reviewer | ✅ done | .ai-workflow/artifacts/task-27/pm-review.md |
| BA | business-analyst | ✅ done | .ai-workflow/artifacts/task-27/spec.md, wireframe.html |
| BA Review | ba-skills-reviewer | ✅ done | .ai-workflow/artifacts/task-27/ba-review.md |
| DESIGN | designer | ✅ done | .ai-workflow/artifacts/task-27/design-members.html, design-notes.md |
| DEV | developer | ✅ done | .ai-workflow/artifacts/task-27/changes.md |
| DEV Review | dev-skills-reviewer | ✅ done (6 зауважень, 6 виправлено) | .ai-workflow/artifacts/task-27/dev-review.md |
| QA | tester | ⏳ in progress | |
| QA Review | qa-skills-reviewer | pending | |
| PERF | perf-reviewer | pending | |
| COMMIT | orchestrator | pending | |
