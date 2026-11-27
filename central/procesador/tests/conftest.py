"""Fixtures de los tests.

Los tests de reglas son puros. Los de integración (marcados `bd`) usan una
MariaDB real y desechable:

    cd central
    docker compose --profile test up -d --wait mariadb_test
    python -m pytest
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

import pytest

from procesador.publicador import PublicadorMemoria, topico_estado, topico_tarjeta
from procesador.servicio import Procesador
from pruebas.bd import CFG, INICIO, Reloj  # noqa: F401  (los tests importan CFG e INICIO de aquí)

# Las fixtures `bd`, `conexion_bd` y `reloj` están en central/conftest.py


@pytest.fixture
def pub():
    return PublicadorMemoria()


@pytest.fixture
def proc(bd, pub, reloj):
    return Procesador(bd, CFG, pub, reloj)


class Huerto:
    """Atajos para escribir los tests en el lenguaje de los criterios."""

    def __init__(self, bd, proc: Procesador, pub: PublicadorMemoria, reloj: Reloj):
        self.bd, self.proc, self.pub, self.reloj = bd, proc, pub, reloj
        self._seq: dict[str, int] = {}

    # --- Preparación ---
    def crear_cama(self, nodo_id: str, nombre: str, cultivo: Optional[str] = "tomate",
                   **rangos) -> int:
        with self.bd.cursor() as cur:
            cultivo_id = None
            if cultivo:
                cur.execute("SELECT id FROM cultivos WHERE nombre = %s", (cultivo,))
                cultivo_id = cur.fetchone()["id"]
            columnas = ["nombre", "nodo_id", "cultivo_id", *rangos.keys()]
            valores = [nombre, nodo_id, cultivo_id, *rangos.values()]
            cur.execute(f"INSERT INTO camas ({', '.join(columnas)}) "
                        f"VALUES ({', '.join(['%s'] * len(valores))})", valores)
            cama_id = cur.lastrowid
        self.bd.commit()
        return cama_id

    # --- Envío de lecturas ---
    def enviar(self, nodo_id: str, medido_en: datetime, suelo: Optional[float] = 50.0,
               temp: Optional[float] = 20.0, hum_aire: Optional[float] = 60.0,
               lux: Optional[float] = 30000.0, seq: Optional[int] = None,
               llegada: Optional[datetime] = None, sondas: Optional[list] = None):
        """Publica una lectura como lo haría el nodo. Por defecto llega 2 s
        después de medirse; `llegada` permite simular lecturas atrasadas."""
        if seq is None:
            seq = self._seq.get(nodo_id, 0) + 1
        self._seq[nodo_id] = max(seq, self._seq.get(nodo_id, 0))
        self.reloj.t = llegada or (medido_en + timedelta(seconds=2))
        datos = {
            "nodo_id": nodo_id,
            "medido_en": medido_en.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seq": seq,
            "suelo": sondas if sondas is not None else (None if suelo is None else [suelo]),
            "suelo_prom": suelo,
            "temp": temp,
            "hum_aire": hum_aire,
            "lux": lux,
        }
        return self.proc.procesar_lectura(f"huerto/cama/{nodo_id}/lectura",
                                          json.dumps(datos).encode())

    def serie(self, nodo_id: str, desde: datetime, minutos: int, cada_s: int = 60, **valores):
        """Envía lecturas cada `cada_s` segundos durante `minutos`."""
        resultados = []
        t = desde
        while t <= desde + timedelta(minutes=minutos):
            resultados.append(self.enviar(nodo_id, t, **valores))
            t += timedelta(seconds=cada_s)
        return resultados

    # --- Consultas ---
    def alertas(self, cama_id: int, tipo: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM alertas WHERE cama_id = %s"
        args: list = [cama_id]
        if tipo:
            sql += " AND tipo = %s"
            args.append(tipo)
        with self.bd.cursor() as cur:
            cur.execute(sql + " ORDER BY id", args)
            filas = list(cur.fetchall())
        self.bd.commit()
        return filas

    def contar(self, tabla: str, where: str = "1=1", args=()) -> int:
        with self.bd.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {tabla} WHERE {where}", args)
            n = cur.fetchone()["n"]
        self.bd.commit()
        return n

    def estado(self, nodo_id: str) -> Optional[dict]:
        """Último estado publicado (retenido) para el LED y el tablero."""
        return self.pub.ultimo(topico_estado(nodo_id))

    def tarjeta(self, nodo_id: str) -> Optional[dict]:
        return self.pub.ultimo(topico_tarjeta(nodo_id))


@pytest.fixture
def huerto(bd, proc, pub, reloj):
    return Huerto(bd, proc, pub, reloj)
