from __future__ import annotations

import argparse
import json
import os
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_STORES_URL = "https://franraja.github.io/iwash-store-map/stores.json"


def name_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in plain.upper()).split())


def read_store_list(path: Path) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    stores = payload.get("stores") if isinstance(payload, dict) else payload
    if not isinstance(stores, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in stores):
        return None
    return stores


def fetch_published_stores() -> list[dict[str, Any]] | None:
    request = urllib.request.Request(
        PUBLISHED_STORES_URL,
        headers={"User-Agent": "IWASH-Store-Map-Run-Report/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    stores = payload.get("stores") if isinstance(payload, dict) else payload
    if not isinstance(stores, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in stores):
        return None
    return stores


def store_map(stores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name_key(item["name"]): item for item in stores}


def status_label(value: Any) -> str:
    return {"open": "Abierta", "upcoming": "Próxima apertura"}.get(value, str(value or "sin estado"))


def changed_description(old: dict[str, Any], new: dict[str, Any]) -> str:
    changes: list[str] = []
    if old.get("status") != new.get("status"):
        changes.append("estado: " + status_label(old.get("status")) + " → " + status_label(new.get("status")))
    if any(old.get(field) != new.get(field) for field in ("city", "province", "address")):
        changes.append("datos de ubicación actualizados")
    if any(old.get(field) != new.get(field) for field in ("lat", "lng")):
        changes.append("coordenadas actualizadas")
    return "; ".join(changes)


def has_coordinates(store: dict[str, Any]) -> bool:
    return store.get("lat") not in (None, 0, 0.0) and store.get("lng") not in (None, 0, 0.0)


def format_location(store: dict[str, Any]) -> str:
    place = ", ".join(str(value) for value in (store.get("city"), store.get("province")) if value)
    return store["name"] + (" — " + place if place else "")


def read_sync_error(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    diagnostic = next((line for line in reversed(lines) if "No se publicó el mapa:" in line), None)
    if diagnostic is None:
        lines = [line for line in lines if not line.startswith(("Traceback", "File \""))]
        diagnostic = "\n".join(lines[-4:]) or "No se obtuvo un detalle del error."
    for variable in ("ODOO_API_KEY", "MAP_SMTP_PASSWORD"):
        secret = os.environ.get(variable)
        if secret:
            diagnostic = diagnostic.replace(secret, "[oculto]")
    return diagnostic[:1200]


def read_log_entries(path: Path, prefix: str) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line.split(prefix, 1)[1].strip() for line in lines if prefix in line]


def build_report(status: str, sync_log: Path) -> dict[str, Any]:
    current = read_store_list(ROOT / "_site" / "stores.json") if status in ("success", "snapshot") else None
    previous = fetch_published_stores()
    effective_status = status
    sync_error = read_sync_error(sync_log) if status == "failure" else None
    if status in ("success", "snapshot") and current is None:
        effective_status = "failure"
        sync_error = "La preparación terminó sin error, pero no se pudo leer el archivo de tiendas generado."

    baseline = store_map(previous or [])
    current_map = store_map(current or [])
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    comparison_available = effective_status == "success" and previous is not None
    if comparison_available:
        added = sorted((item["name"] for key, item in current_map.items() if key not in baseline), key=name_key)
        removed = sorted((item["name"] for key, item in baseline.items() if key not in current_map), key=name_key)
        for key in current_map.keys() & baseline.keys():
            detail = changed_description(baseline[key], current_map[key])
            if detail:
                changed.append(current_map[key]["name"] + " — " + detail)
        changed.sort(key=name_key)

    listing = current if current is not None else previous
    missing_coordinates = sorted(
        (format_location(item) for item in (listing or []) if not has_coordinates(item)),
        key=name_key,
    )
    counts = None
    if current is not None:
        counts = {
            "total": len(current),
            "abiertas": sum(item.get("status") == "open" for item in current),
            "proximas": sum(item.get("status") == "upcoming" for item in current),
            "marcadores": sum(has_coordinates(item) for item in current),
        }
    elif previous is not None:
        counts = {
            "total": len(previous),
            "abiertas": sum(item.get("status") == "open" for item in previous),
            "proximas": sum(item.get("status") == "upcoming" for item in previous),
            "marcadores": sum(has_coordinates(item) for item in previous),
        }

    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_status": effective_status,
        "comparison_available": comparison_available,
        "baseline_available": previous is not None,
        "baseline_error": None if previous is not None else "No se pudo consultar el JSON publicado para comparar cambios.",
        "counts": counts,
        "added": added,
        "removed": removed,
        "changed": changed,
        "missing_coordinates": missing_coordinates,
        "geocoded": read_log_entries(sync_log, "GEOCODED:"),
        "geocoding_warnings": read_log_entries(sync_log, "GEOCODING_WARNING:"),
        "sync_error": sync_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el resumen de una ejecución del mapa IWASH.")
    parser.add_argument("--status", choices=("success", "failure", "snapshot"), required=True)
    parser.add_argument("--sync-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.status, args.sync_log)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Informe de ejecución preparado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

