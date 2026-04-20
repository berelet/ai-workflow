#!/usr/bin/env bash
# Универсальный менеджер локальных проектов
# Использование:
#   ./run.sh start [project|all]   — запустить проект(ы) в фоне
#   ./run.sh stop  [project|all]   — остановить проект(ы)
#   ./run.sh status                — показать статус всех проектов
#   ./run.sh list                  — список проектов и портов
#   ./run.sh logs <project>        — показать логи проекта

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/runtime/projects.json"

if ! command -v jq &>/dev/null; then
    echo "❌ jq не установлен. Установи: sudo apt install jq"
    exit 1
fi

list_projects() {
    echo "📋 Зарегистрированные проекты:"
    echo "─────────────────────────────────────────────────"
    printf "%-28s %-6s %s\n" "ПРОЕКТ" "ПОРТ" "ДИРЕКТОРИЯ"
    echo "─────────────────────────────────────────────────"
    jq -r 'to_entries[] | "\(.key)\t\(.value.port)\t\(.value.dir)"' "$CONFIG" | \
        while IFS=$'\t' read -r name port dir; do
            printf "%-28s %-6s %s\n" "$name" "$port" "$dir"
        done
}

get_field() {
    jq -r --arg p "$1" --arg f "$2" '.[$p][$f] // empty' "$CONFIG"
}

start_project() {
    local name="$1"
    local port dir venv cmd log
    port=$(get_field "$name" "port")
    dir=$(get_field "$name" "dir")
    venv=$(get_field "$name" "venv")
    cmd=$(get_field "$name" "cmd")
    log=$(get_field "$name" "log")
    health=$(get_field "$name" "health")

    if [ -z "$port" ]; then
        echo "❌ Проект '$name' не найден в $CONFIG"
        return 1
    fi

    # Проверить, не занят ли порт
    if lsof -ti:"$port" &>/dev/null; then
        echo "⚠️  Порт $port уже занят (проект: $name). Пропускаю."
        return 0
    fi

    if [ ! -d "$dir" ]; then
        echo "❌ Директория не найдена: $dir"
        return 1
    fi

    echo -n "🚀 Запуск $name (порт $port)... "

    local activate=""
    if [ -n "$venv" ] && [ "$venv" != "null" ]; then
        activate="source \"$dir/$venv/bin/activate\" && "
    fi

    local logpath="$dir/$log"
    bash -c "cd \"$dir\" && ${activate}nohup $cmd > \"$logpath\" 2>&1 &"

    # Health check (до 10 секунд)
    for i in $(seq 1 10); do
        sleep 1
        if curl -s -o /dev/null -w '' "$health" 2>/dev/null; then
            echo "✅"
            return 0
        fi
    done
    echo "⏳ запущен, но health check не прошёл (проверь логи: $logpath)"
}

stop_project() {
    local name="$1"
    local port
    port=$(get_field "$name" "port")

    if [ -z "$port" ]; then
        echo "❌ Проект '$name' не найден"
        return 1
    fi

    local pids
    pids=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        echo "🛑 $name (порт $port) — остановлен"
    else
        echo "⚪ $name (порт $port) — не запущен"
    fi
}

status_all() {
    echo "📊 Статус проектов:"
    echo "─────────────────────────────────────────────────"
    printf "%-28s %-6s %s\n" "ПРОЕКТ" "ПОРТ" "СТАТУС"
    echo "─────────────────────────────────────────────────"
    jq -r 'to_entries[] | "\(.key)\t\(.value.port)\t\(.value.health)"' "$CONFIG" | \
        while IFS=$'\t' read -r name port health; do
            if lsof -ti:"$port" &>/dev/null; then
                if curl -s -o /dev/null -m 2 "$health" 2>/dev/null; then
                    status="🟢 работает"
                else
                    status="🟡 порт занят, health fail"
                fi
            else
                status="🔴 остановлен"
            fi
            printf "%-28s %-6s %s\n" "$name" "$port" "$status"
        done
}

show_logs() {
    local name="$1"
    local dir log
    dir=$(get_field "$name" "dir")
    log=$(get_field "$name" "log")
    if [ -z "$dir" ]; then
        echo "❌ Проект '$name' не найден"
        return 1
    fi
    tail -50 "$dir/$log"
}

all_projects() {
    jq -r 'keys[]' "$CONFIG"
}

case "${1:-help}" in
    start)
        target="${2:-all}"
        if [ "$target" = "all" ]; then
            while read -r p; do start_project "$p"; done < <(all_projects)
        else
            start_project "$target"
        fi
        ;;
    stop)
        target="${2:-all}"
        if [ "$target" = "all" ]; then
            while read -r p; do stop_project "$p"; done < <(all_projects)
        else
            stop_project "$target"
        fi
        ;;
    status)
        status_all
        ;;
    list)
        list_projects
        ;;
    logs)
        if [ -z "${2:-}" ]; then
            echo "Использование: $0 logs <project>"
            exit 1
        fi
        show_logs "$2"
        ;;
    *)
        echo "Использование: $0 {start|stop|status|list|logs} [project|all]"
        echo ""
        list_projects
        ;;
esac
