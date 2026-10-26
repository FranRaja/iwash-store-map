from __future__ import annotations

import argparse
import ast
import json
import hashlib
import math
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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
    "street",
    "street2",
    "zip",
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


ROAD_WORDS = {
    "CALLE", "C", "CL", "AVENIDA", "AVDA", "AV", "CARRETERA", "CTRA",
    "PLAZA", "PZA", "PASEO", "PSO", "CAMINO", "CMNO", "TRAVESIA", "TRVA",
    "RONDA", "GLORIETA", "CRUCE", "ESQUINA", "S", "N", "SN", "HI",
}
STOP_WORDS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "CENTRO", "COMERCIAL", "MODULO"}


def geocode_address(record: dict[str, Any]) -> str | None:
    street = clean_text(record.get("street"))
    city = display_city(record.get("city"))
    province = display_province(record.get("state_id"))
    parts = [street, clean_text(record.get("street2")), clean_text(record.get("zip")), city, province, "España"]
    query = ", ".join(part for part in parts if part)
    return query if street and city and len(query) >= 12 else None


def address_hash(query: str) -> str:
    return hashlib.sha256(normalize_key(query).encode("utf-8")).hexdigest()


def address_tokens(value: Any) -> set[str]:
    words = set(normalize_key(str(value or "")).split())
    return words - ROAD_WORDS - STOP_WORDS


def city_matches(expected: Any, found: Any) -> bool:
    expected_key = normalize_key(str(expected or ""))
    expected_key = {"SAN JORDI": "SANT JORDI"}.get(expected_key, expected_key)
    expected_words = set(expected_key.split())
    found_words = set(normalize_key(str(found or "")).split())
    if not expected_words or not found_words:
        return False
    return expected_words <= found_words or found_words <= expected_words


def province_key(value: Any) -> str:
    aliases = {"GIPUZCOA": "GIPUZKOA", "CASTELLO": "CASTELLON"}
    return " ".join(aliases.get(word, word) for word in normalize_key(str(value or "")).split())


def province_matches(expected: Any, found: Any) -> bool:
    expected_words = set(province_key(expected).split())
    found_words = set(province_key(found).split())
    return bool(expected_words and found_words and (expected_words <= found_words or found_words <= expected_words))


def expected_street(record: dict[str, Any]) -> tuple[set[str], str | None]:
    street = clean_text(record.get("street")) or ""
    is_no_number = bool(re.search(r"\b(?:S\s*/\s*N|SIN\s+NUMERO)\b", street, flags=re.IGNORECASE))
    # Cruces y referencias posteriores a S/N no identifican el nombre de la vía.
    street = re.split(r"\b(?:S\s*/\s*N|SIN\s+NUMERO|CRUCE|ESQUINA)\b", street, flags=re.IGNORECASE)[0]
    house_match = re.search(r"(?:^|[,\s])(?:N[ºO.]?\s*)?(\d+[A-Za-z]?(?:-\d+)?)\s*$", street, flags=re.IGNORECASE)
    house_number = house_match.group(1) if house_match else ("SN" if is_no_number else None)
    if house_match:
        street = street[:house_match.start()].strip(" ,")
    return address_tokens(street), house_number


def candidate_street_tokens(candidate: dict[str, Any]) -> set[str]:
    address = clean_text(candidate.get("address")) or ""
    road = address.split(",", 1)[0]
    words = address_tokens(road)
    number = candidate.get("portalNumber")
    if number not in (None, False, ""):
        words.discard(normalize_key(str(number)))
    return words


def cartociudad_match(
    record: dict[str, Any], candidates: list[dict[str, Any]],
) -> tuple[tuple[float, float] | None, str | None, str | None]:
    postcode = clean_text(record.get("zip"))
    expected_city = display_city(record.get("city"))
    expected_province = display_province(record.get("state_id"))
    expected_road, expected_house = expected_street(record)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if postcode and normalize_key(str(candidate.get("postalCode") or "")) != normalize_key(postcode):
            continue
        if not city_matches(expected_city, candidate.get("muni")):
            continue
        if expected_province and not province_matches(expected_province, candidate.get("province")):
            continue
        if candidate.get("countryCode") not in (None, "011", 11):
            continue

        kind = str(candidate.get("type") or "").lower()
        match_type: str | None = None
        if kind == "portal":
            if candidate_street_tokens(candidate) != expected_road:
                continue
            if expected_house == "SN":
                if candidate.get("noNumber") not in (True, "true", "True", 1):
                    continue
                match_type = "portal-sin-numero"
            elif expected_house:
                if normalize_key(str(candidate.get("portalNumber") or "")) != normalize_key(expected_house):
                    continue
                match_type = "portal-exacto"
            else:
                continue
        elif kind == "toponimo":
            # Solo se acepta un punto de interés si su nombre aparece literalmente
            # en la segunda línea de dirección de Odoo; se etiqueta como referencia.
            place = (clean_text(candidate.get("address")) or "").split(",", 1)[0]
            place_words = address_tokens(place)
            street2_words = address_tokens(record.get("street2"))
            if not place_words or not place_words <= street2_words:
                continue
            match_type = "referencia-recinto"
        else:
            continue

        pair = coordinate_pair(candidate.get("lat"), candidate.get("lng"))
        if pair:
            return pair, match_type, clean_text(candidate.get("address"))
    return None, None, None


def request_cartociudad(query: str, postcode: str | None) -> tuple[list[dict[str, Any]] | None, str | None]:
    params: dict[str, str] = {"q": query, "limit": "10", "countrycodes": "es"}
    if postcode:
        params["cod_postal_filter"] = postcode
    url = "https://www.cartociudad.es/geocoder/api/geocoder/candidates?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "IWASH-Store-Map/1.0 (monthly address matching; contacto: smart.iwashlaundry.es)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, "CartoCiudad devolvió HTTP " + str(exc.code)
    except urllib.error.URLError:
        return None, "no se pudo conectar con CartoCiudad"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "CartoCiudad devolvió una respuesta inválida"
    if not isinstance(payload, list):
        return None, "CartoCiudad devolvió un formato inesperado"
    return [item for item in payload if isinstance(item, dict)], None


def geocode_queries(record: dict[str, Any], base_query: str) -> list[str]:
    queries = [base_query]
    street = clean_text(record.get("street")) or ""
    city = display_city(record.get("city")) or ""
    province = display_province(record.get("state_id")) or ""
    postcode = clean_text(record.get("zip")) or ""
    # En Donostia el callejero oficial usa la forma vasca "HI NAVARRA".
    if "GIPUZKOA" in normalize_key(province) or "GIPUZCOA" in normalize_key(province):
        avenue = re.match(r"\s*AVENIDA\s+DE\s+(.+?)\s+(\d+[A-Za-z]?)\s*$", street, flags=re.IGNORECASE)
        if avenue:
            queries.append("HI " + avenue.group(1) + " " + avenue.group(2) + ", " + postcode + ", " + city + ", " + province)
    simpler = ", ".join(part for part in (street, postcode, city, province) if part)
    if simpler and simpler not in queries:
        queries.append(simpler)
    return queries


def save_locations(path: Path, locations: dict[str, dict[str, Any]]) -> None:
    payload = sorted(locations.values(), key=lambda item: normalize_key(item["name"]))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def geocode_missing_locations(
    partner_records: list[dict[str, Any]],
    locations: dict[str, dict[str, Any]],
    locations_path: Path,
) -> list[str]:
    candidates: list[tuple[dict[str, Any], str, str]] = []
    for record in partner_records:
        name = clean_text(record.get(COMMERCIAL_NAME_FIELD))
        if not name:
            continue
        key = normalize_key(name)
        if key in locations and coordinate_pair(locations[key].get("lat"), locations[key].get("lng")):
            continue
        if coordinate_pair(record.get("partner_latitude"), record.get("partner_longitude")):
            continue
        query = geocode_address(record)
        if query:
            candidates.append((record, key, query))

    if not candidates:
        return []

    warnings: list[str] = []
    updated = False
    attempted = 0
    for record, key, query in candidates:
        name = clean_text(record.get(COMMERCIAL_NAME_FIELD)) or "Tienda sin nombre"
        digest = address_hash("\n".join(geocode_queries(record, query)))
        cached = locations.get(key, {})
        if cached.get("geocode_status") == "unresolved" and cached.get("geocode_query_hash") == digest:
            try:
                checked_at = datetime.fromisoformat(str(cached.get("geocoded_at", "")).replace("Z", "+00:00"))
            except ValueError:
                checked_at = datetime.min.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - checked_at < timedelta(days=90):
                warning = name + ": " + str(cached.get("geocode_reason") or "coordenadas pendientes de coincidencia fiable")
                warnings.append(warning)
                print("GEOCODING_WARNING: " + warning)
                continue

        pair: tuple[float, float] | None = None
        match_type: str | None = None
        matched_address: str | None = None
        request_error: str | None = None
        for variant in geocode_queries(record, query):
            if attempted:
                time.sleep(1.05)
            attempted += 1
            results, request_error = request_cartociudad(variant, clean_text(record.get("zip")))
            if request_error:
                break
            pair, match_type, matched_address = cartociudad_match(record, results or [])
            if pair:
                break
        if request_error:
            warning = name + ": " + request_error
            warnings.append(warning)
            print("GEOCODING_WARNING: " + warning)
            continue
        if not pair:
            reason = "CartoCiudad no encontró un portal exacto con el código postal y la localidad indicados"
            locations[key] = {
                "name": name,
                "city": display_city(record.get("city")),
                "province": display_province(record.get("state_id")),
                "geocode_status": "unresolved",
                "geocode_query_hash": digest,
                "geocode_reason": reason,
                "geocoded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            updated = True
            warning = name + ": " + reason
            warnings.append(warning)
            print("GEOCODING_WARNING: " + warning)
            continue

        lat, lng = pair
        locations[key] = {
            "name": name,
            "city": display_city(record.get("city")),
            "province": display_province(record.get("state_id")),
            "lat": lat,
            "lng": lng,
            "coordinate_source": "CartoCiudad (IGN-CNIG)",
            "match_type": match_type,
            "matched_address": matched_address,
            "geocode_query_hash": digest,
            "geocoded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        updated = True
        print("GEOCODED: " + name + " (coincidencia " + str(match_type) + "; " + str(matched_address) + ")")
        if match_type == "referencia-recinto":
            warning = name + ": pin situado en la referencia del recinto; puede requerir ajuste al módulo/local"
            warnings.append(warning)
            print("GEOCODING_WARNING: " + warning)

    if updated:
        save_locations(locations_path, locations)
    return warnings


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
        unresolved = item.get("geocode_status") == "unresolved" and isinstance(item.get("geocode_query_hash"), str)
        if not pair and not unresolved:
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
        override_pair = coordinate_pair(location.get("lat"), location.get("lng")) if location else None
        odoo_pair = coordinate_pair(record.get("partner_latitude"), record.get("partner_longitude"))
        pair = override_pair or odoo_pair
        lat, lng = pair if pair else (None, None)
        city = clean_text(location.get("city")) if location else None
        province = clean_text(location.get("province")) if location else None
        city = city or display_city(record.get("city"))
        province = province or display_province(record.get("state_id"))
        address = clean_text(location.get("address")) if location else None

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

    if not args.snapshot:
        geocode_missing_locations(partner_records, locations, args.locations)
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

