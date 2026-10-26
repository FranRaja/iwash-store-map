from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "data_status": "failure",
            "comparison_available": False,
            "baseline_available": False,
            "counts": None,
            "added": [],
            "removed": [],
            "changed": [],
            "missing_coordinates": [],
            "sync_error": "No se pudo generar o recuperar el informe detallado de la ejecución.",
        }
    return value if isinstance(value, dict) else {"data_status": "failure"}


def section(title: str, values: list[str], empty: str) -> list[str]:
    if not values:
        return [title + ":", "- " + empty]
    return [title + ":", *["- " + value for value in values]]


def make_message(report: dict[str, Any], publish_result: str, run_url: str) -> EmailMessage:
    data_status = report.get("data_status", "failure")
    job_succeeded = publish_result == "success"
    if not job_succeeded or data_status == "failure":
        title = "Incidencia en la actualización"
        result_text = "No se completó la ejecución correctamente. Si falló la lectura de Odoo, se conserva el mapa anterior. Consulta el registro de GitHub Actions para identificar el paso fallido."
    elif data_status == "snapshot":
        title = "Publicación manual completada"
        result_text = "Se publicó la captura revisada sin consultar Odoo. No se calcularon cambios frente a los datos actuales de Odoo."
    else:
        title = "Actualización completada"
        result_text = "La sincronización con Odoo y la publicación del mapa terminaron correctamente."

    lines = [
        "Mapa público de tiendas IWASH",
        "",
        "Resultado: " + result_text,
        "",
        "Resumen de datos:",
    ]
    counts = report.get("counts")
    if isinstance(counts, dict):
        lines.extend([
            "- Tiendas: {total} ({abiertas} abiertas, {proximas} próximas aperturas).".format(**counts),
            "- Marcadores: {marcadores}.".format(**counts),
        ])
    else:
        lines.append("- No se pudo preparar el recuento de tiendas de esta ejecución.")

    if report.get("comparison_available"):
        lines.extend([""])
        lines.extend(section("Tiendas añadidas", report.get("added", []), "Ninguna."))
        lines.extend(section("Tiendas retiradas del conjunto activo", report.get("removed", []), "Ninguna."))
        lines.extend(section("Tiendas con cambios", report.get("changed", []), "Ninguna."))
    elif data_status == "success":
        lines.extend(["", "Cambios: no se pudieron comparar con la publicación anterior."])
    elif data_status == "failure":
        lines.extend(["", "Cambios: no se pudieron calcular porque la lectura o preparación de Odoo falló."])

    lines.extend([""])
    if report.get("missing_coordinates"):
        lines.extend(section("Fichas sin coordenadas", report["missing_coordinates"], "Ninguna."))
        if data_status == "failure":
            lines.append("La lista corresponde a la última versión pública disponible.")
    elif report.get("baseline_available") or data_status in ("success", "snapshot"):
        lines.extend(["Fichas sin coordenadas:", "- Ninguna."])
    else:
        lines.extend(["Fichas sin coordenadas:", "- No se pudieron consultar los datos disponibles."])

    error = report.get("sync_error")
    if error:
        lines.extend(["", "Detalle del error:", str(error)])
    baseline_error = report.get("baseline_error")
    if baseline_error and data_status == "success":
        lines.extend(["", str(baseline_error)])

    created_at = report.get("created_at")
    if created_at:
        try:
            date_text = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M %Z")
            lines.extend(["", "Fecha del informe: " + date_text])
        except ValueError:
            pass
    lines.extend(["", "Ejecución de GitHub Actions:", run_url])
    subject_status = "Incidencia" if title.startswith("Incidencia") else "Correcta"

    recipient = os.environ.get("MAP_NOTIFICATION_TO", "").strip()
    sender = os.environ.get("MAP_SMTP_USER", "").strip()
    if not recipient or not sender or not os.environ.get("MAP_SMTP_PASSWORD", "").strip():
        raise ValueError("Faltan uno o más secretos MAP_NOTIFICATION_TO, MAP_SMTP_USER o MAP_SMTP_PASSWORD.")
    if parseaddr(recipient)[1] != recipient or "\n" in recipient or "\r" in recipient:
        raise ValueError("El secreto MAP_NOTIFICATION_TO no contiene una dirección de correo válida.")
    if parseaddr(sender)[1] != sender or "\n" in sender or "\r" in sender:
        raise ValueError("El secreto MAP_SMTP_USER no contiene una dirección de correo válida.")

    message = EmailMessage()
    message["Subject"] = "[Mapa IWASH] " + subject_status + " — " + title
    message["From"] = sender
    message["To"] = recipient
    message.set_content("\n".join(lines))
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description="Envía el resumen de ejecución del mapa IWASH.")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run_url = "https://github.com/{}/actions/runs/{}".format(
        os.environ.get("GITHUB_REPOSITORY", "FranRaja/iwash-store-map"),
        os.environ.get("GITHUB_RUN_ID", ""),
    )
    try:
        message = make_message(
            load_report(args.report),
            os.environ.get("PUBLISH_RESULT", "failure"),
            run_url,
        )
        password = os.environ["MAP_SMTP_PASSWORD"].strip().replace(" ", "")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30, context=context) as server:
            server.login(os.environ["MAP_SMTP_USER"].strip(), password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError, KeyError) as exc:
        print("No se pudo enviar el aviso por correo: " + str(exc), file=sys.stderr)
        return 1
    print("Resumen de ejecución enviado por correo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

