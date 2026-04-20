# Comfy CLI — Запуск AI-агентов

```
╭───────────────────────────────────╮
│     Comfy CLI                     │
│     AI Development Pipeline       │
╰───────────────────────────────────╯
```

## Провайдеры и модели

### kiro
| Модель | Описание |
|--------|----------|
| glm-5:cloud | GLM-5 Cloud (рекомендуется) |
| llama3 | Llama 3 |
| llama3.1 | Llama 3.1 |
| mistral | Mistral |
| codellama | Code Llama |
| qwen2.5 | Qwen 2.5 |

### claude
| Модель | Описание |
|--------|----------|
| sonnet | Claude Sonnet 4.6 (рекомендуется) |
| opus | Claude Opus 4.6 |
| haiku | Claude Haiku 4.5 |

## Запуск

```bash
# Интерактивное меню
python cli.py

# С параметрами
python cli.py <project> -c claude -m sonnet
python cli.py <project> --provider kiro --model llama3
python cli.py <project> -t "статус" -s PM
```

### Параметры

| Параметр | Сокращение | Описание |
|----------|------------|----------|
| `--task` | `-t` | Задача |
| `--pipeline` | `-p` | Пайплайн |
| `--stage` | `-s` | Этап |
| `--provider` | `-c` | Провайдер |
| `--model` | `-m` | Модель |

## Меню

```
╭───────────────────────────────────╮
│     Comfy CLI                     │
│     AI Development Pipeline       │
╰───────────────────────────────────╯

  Выбери проект:

   1) ai-workflow ●
   2) my-project

  s) Статус сессий
  a) Подключиться к tmux
  q) Выход
  \) Команды
```

## tmux

Сессия: `comfy`

```bash
tmux attach -t comfy    # Подключиться
Ctrl+B, D               # Отключиться
Ctrl+B, [                # Прокрутка (q — выход)
```

## Цветовая схема

Comfy использует **magenta/purple** (код `\033[1;35m`):
- Заголовки и рамки — magenta
- Активные проекты — magenta `●`
- Команды — cyan
- Действия — yellow