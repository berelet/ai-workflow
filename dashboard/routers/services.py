"""Services management API routes.

GET  /api/services       - list services with status
POST /api/services/start - start services by name
POST /api/services/stop  - stop services by name

All endpoints require superadmin role.
"""
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dashboard.auth.permissions import require_superadmin
from dashboard.db.models.user import User
from dashboard.helpers import BASE

router = APIRouter(tags=["services"])

SERVICES_CONFIG = BASE / "runtime" / "projects.json"


def load_services():
    if SERVICES_CONFIG.exists():
        data = json.loads(SERVICES_CONFIG.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict) and "port" in v}
    return {}


def load_service_groups():
    if SERVICES_CONFIG.exists():
        data = json.loads(SERVICES_CONFIG.read_text(encoding="utf-8"))
        return data.get("_groups")
    return None


class ServiceAction(BaseModel):
    names: list[str]


@router.get("/api/services")
def list_services(user: User = Depends(require_superadmin)):
    cfg = load_services()
    groups = load_service_groups()
    services = {}
    for name, svc in cfg.items():
        port = svc.get("port")
        running = False
        if port:
            r = subprocess.run(["lsof", f"-ti:{port}"], capture_output=True, text=True)
            running = r.returncode == 0 and bool(r.stdout.strip())
        repo = ""
        d = svc.get("dir", "")
        if d and Path(d).is_dir():
            r = subprocess.run(["git", "-C", d, "remote", "get-url", "origin"], capture_output=True, text=True)
            if r.returncode == 0:
                repo = r.stdout.strip()
        services[name] = {"name": name, "port": port, "dir": d, "running": running, "repo": repo}

    # Build grouped response
    if groups:
        grouped = []
        used = set()
        for group_name, members in groups.items():
            items = [services[m] for m in members if m in services]
            used.update(m for m in members if m in services)
            if items:
                grouped.append({"group": group_name, "services": items})
        # Add ungrouped services
        ungrouped = [s for name, s in services.items() if name not in used]
        if ungrouped:
            grouped.append({"group": "Інші", "services": ungrouped})
        return grouped

    # Fallback: flat list (backwards compatible)
    return [{"group": "Всі сервіси", "services": list(services.values())}]


@router.post("/api/services/start")
def start_services(body: ServiceAction, user: User = Depends(require_superadmin)):
    cfg = load_services()
    results = {}
    for name in body.names:
        svc = cfg.get(name)
        if not svc:
            results[name] = {"ok": False, "error": "not found"}
            continue
        port = svc["port"]
        r = subprocess.run(["lsof", f"-ti:{port}"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            results[name] = {"ok": True, "msg": "already running"}
            continue
        d = svc["dir"]
        if not Path(d).is_dir():
            results[name] = {"ok": False, "error": f"dir not found: {d}"}
            continue
        venv = svc.get("venv")
        cmd = svc["cmd"]
        log = svc.get("log", "server.log")
        activate = f'source "{d}/{venv}/bin/activate" && ' if venv and venv != "null" else ""
        shell_cmd = f'cd "{d}" && {activate}nohup {cmd} > "{d}/{log}" 2>&1 &'
        subprocess.Popen(["bash", "-c", shell_cmd])
        results[name] = {"ok": True}
    return results


@router.post("/api/services/stop")
def stop_services(body: ServiceAction, user: User = Depends(require_superadmin)):
    cfg = load_services()
    results = {}
    for name in body.names:
        svc = cfg.get(name)
        if not svc:
            results[name] = {"ok": False, "error": "not found"}
            continue
        port = svc["port"]
        r = subprocess.run(["lsof", f"-ti:{port}"], capture_output=True, text=True)
        pids = r.stdout.strip()
        if pids:
            subprocess.run(["kill", "-9"] + pids.split("\n"), capture_output=True)
            results[name] = {"ok": True}
        else:
            results[name] = {"ok": True, "msg": "not running"}
    return results
