"""Guardar una lectura que llega de un nodo: interpretar -> validar -> INSERT.

Lo usan las dos entradas de lecturas:
* el procesador, cuando llega por MQTT (huerto/cama/<id>/lectura), y
* la API del tablero, cuando llega por HTTP (POST /api/lecturas).

Así hay UNA sola regla de validación y de deduplicación. Las reglas de
alertas y estado las sigue aplicando solo el procesador.

No hace commit cuando la lectura se guarda: quien llama decide si cierra la
transacción ahí (API) o después de evaluar las alertas (procesador). Sí hace
commit al registrar incidencias (mensaje inválido o seq reiniciado).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pymysql

from comun.config import Config

from . import repositorio as repo
from .publicador import iso
from .validacion import (LecturaValidada, MensajeInvalido, interpretar, validar,
                         valores_anteriores_desde_fila)

log = logging.getLogger(__name__)

GUARDADA = "guardada"
DUPLICADA = "duplicada"              # reenvío del buffer: mismo seq y misma hora
SEQ_REINICIADO = "seq_reiniciado"    # mismo seq con otra hora: se descarta
INVALIDA = "invalida"                # JSON roto, sin seq o sin hora: no se guarda


@dataclass
class Ingreso:
    estado: str
    cama: Optional[dict] = None
    lectura: Optional[LecturaValidada] = None
    lectura_id: Optional[int] = None
    error: Optional[str] = None


def guardar_lectura(conn, nodo_id: str, payload, ahora: datetime, cfg: Config) -> Ingreso:
    try:
        datos = interpretar(nodo_id, payload)
    except MensajeInvalido as e:
        muestra = payload[:200] if isinstance(payload, (bytes, str)) else payload
        repo.registrar_incidencia(conn, nodo_id, "mensaje_invalido",
                                  f"{e}. Mensaje: {muestra!r}", ahora)
        conn.commit()
        log.warning("[%s] mensaje descartado: %s", nodo_id, e)
        return Ingreso(INVALIDA, error=str(e))
    if datos.nodo_id_mensaje and datos.nodo_id_mensaje != nodo_id:
        log.warning("[%s] el JSON dice nodo_id=%r; se usa el del tópico o del token",
                    nodo_id, datos.nodo_id_mensaje)

    cama = repo.obtener_o_crear_cama(conn, nodo_id)
    fila_anterior = repo.lectura_anterior(conn, cama["id"], datos.medido_en)
    anterior = valores_anteriores_desde_fila(fila_anterior) if fila_anterior else None
    lectura = validar(datos, anterior, ahora, cfg)

    try:
        lectura_id = repo.insertar_lectura(conn, cama["id"], lectura, ahora)
    except pymysql.err.IntegrityError:
        return _seq_repetido(conn, cama, lectura, ahora)
    return Ingreso(GUARDADA, cama, lectura, lectura_id)


def _seq_repetido(conn, cama: dict, lectura: LecturaValidada, ahora: datetime) -> Ingreso:
    conn.rollback()
    existente = repo.lectura_por_seq(conn, cama["id"], lectura.seq)
    if existente and existente["medido_en"] == lectura.medido_en:
        # Reenvío normal desde el buffer (se perdió la confirmación): se ignora.
        return Ingreso(DUPLICADA, cama, lectura, existente["id"])
    detalle = (f"Llegó seq={lectura.seq} medida el {iso(lectura.medido_en)}, pero ese seq ya "
               f"existe con hora {iso(existente['medido_en']) if existente else '?'}. "
               "Probablemente se borró la memoria del nodo y su contador volvió a cero: "
               "esas lecturas se están descartando.")
    if repo.registrar_incidencia(conn, cama["nodo_id"], "seq_reiniciado", detalle, ahora):
        log.error("[%s] %s", cama["nodo_id"], detalle)
    conn.commit()
    return Ingreso(SEQ_REINICIADO, cama, lectura, error=detalle)
