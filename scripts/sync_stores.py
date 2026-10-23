from __future__ import annotations

import argparse
import ast
import json
import math
import os
import shutil
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FILTER_ID = 25
FILTER_NAME = "Aperturas Iwash"
FILTER_MODEL = "res.partner"
COMMERCIAL_NAME_FIELD = "x_studio_nombre_comercial"
OPEN_TAG_ID = 12
UPCOMING_TAG_ID = 31
TARGET_COMPANY_NAME = "Smart Shops Factory"
PAGE_SIZE = 100

EXPECTED_FILTER_DOMAIN = [
    "|",
    "|",
    [COMMERCIAL_NAME_FIELD, "ilike", "IWASH"],
    ["category_id", "in", [UPCOMING_TAG_ID]],
    ["category_id", "in", [OPEN_TAG_ID]],
]

PARTNER_FIELDS = [
    COMMERCIAL_NAME_FIELD,
    "city",
    "state_id",
    "partner_latitude",
    "partner_longitude",
    "category_id",
    "active",
]


class SyncError(RuntimeError):
    pass


def clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


def normalize_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in plain.upper()).split())


def display_city(value: Any) -> str | None:
    city = clean_text(value)
    if not city:
        return None
    if city.isupper():
        return city.title()
    return city


def display_province(value: Any) -> str | None:
    if isinstance(value, list) and len(value) > 1:
        value = value[1]
    province = clean_text(value)
    if not province:
        return None
    suffix = " (ES)"
    if province.endswith(suffix):
        province = province[:-len(suffix)].strip()
    spanish_names = {
        "Gipuzkoa (Guipúzcoa)": "Guipúzcoa",
        "Castelló (Castellón)": "Castellón",
    }
    return spanish_names.get(province, province)


def coordinate_pair(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if lat == 0 or lng == 0:
        return None
    if not (27 <= lat <= 45.5 and -18 <= lng <= 5):
        return None
    return lat, lng


def to_json_lists(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [to_json_lists(item) for item in value]
    return value


def parse_saved_domain(raw_domain: Any) -> list[Any]:
    if not isinstance(raw_domain, str):
        raise SyncError("El filtro guardado no tiene un dominio legible.")
    try:
        parsed = ast.literal_eval(raw_domain)
    except (ValueError, SyntaxError):
        try:
            parsed = json.loads(raw_domain)
        except json.JSONDecodeError as exc:
            raise SyncError("No se pudo leer el dominio del filtro guardado.") from exc
    parsed = to_json_lists(parsed)
    if parsed != EXPECTED_FILTER_DOMAIN:
        raise SyncError("El dominio del filtro Aperturas Iwash ha cambiado; se detuvo la publicación para revisar su alcance.")
    return parsed


def api_request(model: str, method: str, payload: dict[str, Any]) -> Any:
    base_url = os.environ.get("ODOO_URL", "https://smart.iwashlaundry.es").rstrip("/")
    api_key = os.environ.get("ODOO_API_KEY")
    if not api_key:
        raise SyncError("Falta el secreto ODOO_API_KEY en GitHub Actions.")

    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "IWASH-Store-Map/1.0",
    }
    database = os.environ.get("ODOO_DATABASE")
    if database:
        headers["X-Odoo-Database"] = database

    url = base_url + "/json/2/" + urllib.parse.quote(model, safe=".") + "/" + urllib.parse.quote(method, safe=".")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            message = "Odoo rechazó la clave o los permisos de lectura de la API."
        else:
            message = "Odoo devolvió HTTP " + str(exc.code) + " en " + model + "." + method + "."
        raise SyncError(message) from None
    except urllib.error.URLError:
        raise SyncError("No se pudo conectar con la API de Odoo.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SyncError("Odoo devolvió una respuesta que no es JSON válido.") from None


def search_read(model: str, domain: list[Any], fields: list[str], limit: int = 2) -> list[dict[str, Any]]:
    result = api_request(
        model,
        "search_read",
        {
            "domain": domain,
            "fields": fields,
            "limit": limit,
            "order": "id",
        },
    )
    if not isinstance(result, list):
        raise SyncError("Odoo devolvió un formato inesperado en " + model + ".")
    return result


def read_filter_domain() -> list[Any]:
    records = search_read(
        "ir.filters",
        [["id", "=", FILTER_ID]],
        ["id", "name", "model_id", "domain"],
        limit=2,
    )
    if len(records) != 1:
        raise SyncError("No se encontró una única búsqueda guardada Aperturas Iwash.")
    saved = records[0]
    if saved.get("name") != FILTER_NAME or saved.get("model_id") != FILTER_MODEL:
        raise SyncError("La búsqueda guardada Aperturas Iwash ya no coincide con el filtro esperado.")
    return parse_saved_domain(saved.get("domain"))


def read_company_id() -> int:
    companies = search_read(
        "res.company",
        [["name", "ilike", TARGET_COMPANY_NAME]],
        ["id", "name"],
        limit=20,
    )
    prefix = normalize_key(TARGET_COMPANY_NAME)
    matches = [
        record for record in companies
        if isinstance(record.get("id"), int)
        and normalize_key(str(record.get("name", ""))).startswith(prefix)
    ]
    if len(matches) != 1:
        raise SyncError("No se pudo identificar de forma única Smart Shops Factory en Odoo.")
    return matches[0]["id"]


def read_partners(saved_domain: list[Any], company_id: int) -> list[dict[str, Any]]:
    domain = [
        "&",
        ["active", "=", True],
        "&",
        ["company_id", "in", [False, company_id]],
        *saved_domain,
    ]
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = api_request(
            "res.partner",
            "search_read",
            {
                "domain": domain,
                "fields": PARTNER_FIELDS,
                "limit": PAGE_SIZE,
                "offset": offset,
                "order": "id",
            },
        )
        if not isinstance(page, list):
            raise SyncError("Odoo devolvió un formato inesperado al leer las tiendas.")
        records.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
        if offset > 10000:
            raise SyncError("La consulta superó el límite de seguridad de registros.")
    return records


def read_locations(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SyncError("No se pudo leer el archivo de ubicaciones verificadas.") from None
    if not isinstance(payload, list):
        raise SyncError("El archivo de ubicaciones verificadas debe contener una lista.")
    locations: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise SyncError("Hay una ubicación verificada con formato incorrecto.")
        key = normalize_key(item["name"])
        if not key or key in locations:
            raise SyncError("Hay nombres duplicados en las ubicaciones verificadas.")
        pair = coordinate_pair(item.get("lat"), item.get("lng"))
        if not pair:
            raise SyncError("Una ubicación verificada no contiene coordenadas válidas.")
        locations[key] = item
    return locations


def build_public_stores(
    partner_records: list[dict[str, Any]],
    locations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not partner_records:
        raise SyncError("Odoo no devolvió tiendas; se conserva la publicación anterior.")

    stores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in partner_records:
        name = clean_text(record.get(COMMERCIAL_NAME_FIELD))
        if not name:
            raise SyncError("Hay una tienda sin nombre comercial; no se publicará el nombre del contacto.")
        key = normalize_key(name)
        if key in seen:
            raise SyncError("Hay nombres comerciales duplicados; se detuvo la publicación.")
        seen.add(key)

        categories = record.get("category_id") or []
        if not isinstance(categories, list):
            raise SyncError("Una tienda tiene etiquetas con un formato inesperado.")
        is_open = OPEN_TAG_ID in categories
        is_upcoming = UPCOMING_TAG_ID in categories
        if is_open == is_upcoming:
            raise SyncError("El estado de una tienda no es único; se detuvo la publicación.")
        status = "open" if is_open else "upcoming"

        location = locations.get(key)
        if location:
            lat, lng = coordinate_pair(location.get("lat"), location.get("lng")) or (None, None)
            city = clean_text(location.get("city"))
            province = clean_text(location.get("province"))
            address = clean_text(location.get("address"))
        else:
            pair = coordinate_pair(record.get("partner_latitude"), record.get("partner_longitude"))
            lat, lng = pair if pair else (None, None)
            city = display_city(record.get("city"))
            province = display_province(record.get("state_id"))
            address = None

        if not city and not province:
            raise SyncError("Una tienda no tiene ciudad ni provincia; se detuvo la publicación.")

        store: dict[str, Any] = {
            "name": name,
            "city": city,
            "province": province,
            "status": status,
        }
        if address:
            store["address"] = address
        if lat is not None and lng is not None:
            store["lat"] = lat
            store["lng"] = lng
        stores.append(store)

    stores.sort(key=lambda item: normalize_key(item["name"]))
    return stores


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SyncError("No se pudo leer el fichero de datos de revisión.") from None
    if not isinstance(payload, list):
        raise SyncError("El fichero de datos de revisión debe ser una lista.")
    return payload


def generate_site(
    stores: list[dict[str, Any]],
    output_path: Path,
    site_dir: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "stores": stores,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for filename in ("index.html", "styles.css", "app.js"):
        shutil.copy2(site_dir / filename, output_path.parent / filename)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sincroniza el mapa público de tiendas IWASH.")
    parser.add_argument("--output", type=Path, default=ROOT / "_site" / "stores.json")
    parser.add_argument("--locations", type=Path, default=ROOT / "data" / "locations-overrides.json")
    parser.add_argument("--snapshot", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    locations = read_locations(args.locations)
    if args.snapshot:
        partner_records = load_snapshot(args.snapshot)
    else:
        saved_domain = read_filter_domain()
        company_id = read_company_id()
        partner_records = read_partners(saved_domain, company_id)

    stores = build_public_stores(partner_records, locations)
    generate_site(stores, args.output, ROOT / "site")
    open_count = sum(1 for item in stores if item["status"] == "open")
    upcoming_count = sum(1 for item in stores if item["status"] == "upcoming")
    marker_count = sum(1 for item in stores if "lat" in item and "lng" in item)
    print(
        "Mapa preparado: "
        + str(len(stores))
        + " tiendas, "
        + str(open_count)
        + " abiertas, "
        + str(upcoming_count)
        + " próximas, "
        + str(marker_count)
        + " marcadores."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as exc:
        print("No se publicó el mapa: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
