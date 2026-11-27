"""Fixtures del tablero web: Flask de prueba + MariaDB de test + difusor sin broker."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

import pytest

from comun.db import conectar
from pruebas.bd import CFG
from web import crear_app, rutas_config
from web.config import ConfigWeb
from web.difusor import DifusorMemoria

PIN = "2468"


@pytest.fixture
def difusor():
    return DifusorMemoria()


@pytest.fixture
def app(bd, difusor, reloj):
    rutas_config._intentos.clear()
    cfg = ConfigWeb(bd=CFG, pin_docente=PIN, clave_sesion="clave-de-prueba")
    app = crear_app(cfg, difusor=difusor, conectar_bd=lambda: conectar(CFG), reloj=reloj)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def cliente(app):
    return app.test_client()


def ingresar(cliente) -> str:
    """Entra con el PIN y devuelve el token CSRF de la sesión."""
    r = cliente.post("/configuracion/ingresar", data={"pin": PIN})
    assert r.status_code == 302
    with cliente.session_transaction() as sesion:
        return sesion["csrf"]


class Datos:
    """Inserta datos de ejemplo directo en la BD."""

    def __init__(self, bd):
        self.bd = bd

    def _ejecutar(self, sql: str, args=()) -> int:
        with self.bd.cursor() as cur:
            cur.execute(sql, args)
            ultimo = cur.lastrowid
        self.bd.commit()
        return ultimo

    def cultivo_id(self, nombre: str) -> int:
        with self.bd.cursor() as cur:
            cur.execute("SELECT id FROM cultivos WHERE nombre = %s", (nombre,))
            fila = cur.fetchone()
        self.bd.commit()
        return fila["id"]

    def cama(self, nodo_id: str, nombre: str, cultivo: Optional[str] = "tomate", activa: int = 1) -> int:
        return self._ejecutar(
            "INSERT INTO camas (nombre, nodo_id, cultivo_id, activa) VALUES (%s, %s, %s, %s)",
            (nombre, nodo_id, self.cultivo_id(cultivo) if cultivo else None, activa))

    def lectura(self, cama_id: int, medido_en: datetime, seq: int, suelo=50.0, temp=20.0, lux=30000.0) -> int:
        return self._ejecutar(
            """INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom, suelo_detalle, temp, hum_aire, lux)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 60, %s)""",
            (cama_id, seq, medido_en, medido_en, suelo, json.dumps([suelo]), temp, lux))

    def estado(self, cama_id: int, color: str, mensaje: str, cuando: datetime) -> None:
        self._ejecutar(
            """INSERT INTO cambios_estado (cama_id, estado_nuevo, mensaje, ocurrido_en)
               VALUES (%s, %s, %s, %s)""", (cama_id, color, mensaje, cuando))

    def alerta(self, cama_id: int, tipo: str, mensaje: str, iniciada: datetime,
               resuelta: Optional[datetime] = None, variable: str = "suelo") -> int:
        return self._ejecutar(
            """INSERT INTO alertas (cama_id, tipo, variable, estado, mensaje, valor_inicial, valor_actual,
                                    iniciada_en, actualizada_en, resuelta_en)
               VALUES (%s, %s, %s, %s, %s, 22, 22, %s, %s, %s)""",
            (cama_id, tipo, variable, "resuelta" if resuelta else "abierta", mensaje,
             iniciada, resuelta or iniciada, resuelta))

    def evento_apertura(self, alerta_id: int, medido: datetime) -> None:
        self._ejecutar(
            """INSERT INTO eventos_alerta (alerta_id, evento, lectura_medida_en, procesado_en)
               VALUES (%s, 'apertura', %s, %s)""", (alerta_id, medido, medido + timedelta(seconds=1)))

    def consulta(self, sql: str, args=()) -> list[dict]:
        with self.bd.cursor() as cur:
            cur.execute(sql, args)
            filas = list(cur.fetchall())
        self.bd.commit()
        return filas


@pytest.fixture
def datos(bd):
    return Datos(bd)
