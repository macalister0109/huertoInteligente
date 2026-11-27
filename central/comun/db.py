"""Conexión a MariaDB. Todas las consultas del proyecto son parametrizadas (%s).

Convención de fechas: dentro del código se usan datetime *ingenuos en UTC*
(sin tzinfo), igual que los guarda la BD. Solo se convierten a la hora de
Chile para mostrar o para calcular qué día es.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone

import pymysql
import pymysql.cursors

from .config import Config

log = logging.getLogger(__name__)

# Errores que indican que la conexión se perdió (vale la pena reintentar)
ERRORES_CONEXION = (pymysql.err.OperationalError, pymysql.err.InterfaceError)


def ahora_utc() -> datetime:
    """Hora actual en UTC, sin tzinfo y con milisegundos."""
    t = datetime.now(timezone.utc).replace(tzinfo=None)
    return t.replace(microsecond=(t.microsecond // 1000) * 1000)


def conectar(cfg: Config) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=cfg.db_host,
        port=cfg.db_puerto,
        user=cfg.db_usuario,
        password=cfg.db_clave,
        database=cfg.db_nombre,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        init_command="SET time_zone = '+00:00'",
        connect_timeout=10,
    )


def conectar_con_reintentos(cfg: Config, intentos: int = 0, espera_max: float = 30.0):
    """Reintenta hasta lograr conectar (intentos=0: sin límite).

    En la Pi, MariaDB puede tardar en arrancar después de un corte de luz.
    """
    n, espera = 0, 1.0
    while True:
        try:
            return conectar(cfg)
        except ERRORES_CONEXION as e:
            n += 1
            if intentos and n >= intentos:
                raise
            log.warning("No se pudo conectar a la BD (%s). Reintento en %.0f s.", e, espera)
            time.sleep(espera)
            espera = min(espera * 2, espera_max)
