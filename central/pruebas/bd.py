"""BD de test desechable:  docker compose --profile test up -d --wait mariadb_test"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from comun.config import Config

CENTRAL = Path(__file__).resolve().parents[1]

CFG = Config(
    db_host=os.environ.get("TEST_DB_HOST", "127.0.0.1"),
    db_puerto=int(os.environ.get("TEST_DB_PORT", "3307")),
    db_usuario="huerto",
    db_clave="test",
    db_nombre="huerto_test",
)

TABLAS = ["eventos_alerta", "alertas", "luz_diaria", "latencias_pantalla", "cambios_estado",
          "lecturas", "camas", "cultivos", "heartbeats", "conexiones_nodo", "incidencias"]

# 26-11-2026 15:00 UTC = 12:00 en Chile (horario de verano, UTC-3)
INICIO = datetime(2026, 11, 26, 15, 0, 0)

MENSAJE_SIN_BD = ("No hay BD de test ({}). Levántala con: "
                  "docker compose --profile test up -d --wait mariadb_test")


class Reloj:
    """Reloj controlable: los tests deciden qué hora es."""

    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def avanzar(self, **delta) -> None:
        self.t += timedelta(**delta)


def vaciar_bd(conn) -> None:
    """Deja la BD vacía, solo con las semillas de cultivos."""
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for tabla in TABLAS:
            cur.execute(f"TRUNCATE TABLE {tabla}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        semillas = (CENTRAL / "db" / "semillas.sql").read_text(encoding="utf-8")
        for sentencia in semillas.split(";"):
            lineas = [l for l in sentencia.splitlines() if not l.strip().startswith("--")]
            if "".join(lineas).strip():
                cur.execute("\n".join(lineas))
    conn.commit()
