"""Fixtures del tablero web: Flask de prueba + MariaDB de test + difusor sin broker."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Optional

import pytest

from comun.clima import ClimaReferencia, ErrorClima, ProveedorClima
from comun.db import conectar
from pruebas.bd import CFG
from web import crear_app, rutas_config
from web.config import ConfigWeb
from web.difusor import DifusorMemoria

PIN = "2468"


@pytest.fixture
def difusor():
    return DifusorMemoria()


class ProveedorClimaFalso(ProveedorClima):
    """Clima de prueba: los tests web nunca llaman a internet."""
    nombre = "open-meteo"
    nombre_corto = "Open-Meteo"

    def __init__(self, reloj):
        self.reloj = reloj
        self.falla = False
        self.demora_s = 0.0
        self.temp = 25.0
        self.llamadas = 0

    def obtener(self, lat, lon, timeout=5):
        self.llamadas += 1
        if self.demora_s:
            time.sleep(min(self.demora_s, timeout))
            raise ErrorClima("sin conexión (timed out)")
        if self.falla:
            raise ErrorClima("sin conexión")
        t = self.reloj().replace(second=0, microsecond=0)
        return ClimaReferencia(self.temp, 40, 0, 800, 30, 16.8, 0.5, t - timedelta(minutes=12),
                               "open-meteo", lat, lon, 4.2)


@pytest.fixture
def clima_falso(reloj):
    return ProveedorClimaFalso(reloj)


@pytest.fixture
def app(bd, difusor, reloj, clima_falso):
    rutas_config._intentos.clear()
    cfg = ConfigWeb(bd=CFG, pin_docente=PIN, clave_sesion="clave-de-prueba")
    app = crear_app(cfg, difusor=difusor, conectar_bd=lambda: conectar(CFG), reloj=reloj,
                    crear_proveedor_clima=lambda nombre: clima_falso)
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
