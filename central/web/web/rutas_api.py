"""API para los nodos ESP32 que envían lecturas por HTTP.

    POST /api/lecturas                 (Authorization: Bearer <token del nodo>)
    GET  /api/camas/<nodo_id>/ultima   lectura actual de la cama (HU-01)

La web solo GUARDA la lectura (con la misma validación del procesador) y
avisa al procesador por MQTT. Las alertas y el color de la cama los sigue
calculando el procesador, igual que cuando la lectura llega por MQTT.

Respuestas de POST /api/lecturas:
    201 guardada (aunque algún valor venga fuera de rango: queda marcado inválido)
    200 duplicada (reenvío del buffer: mismo seq y misma hora)
    400 JSON mal formado, sin seq o sin medido_en
    401 falta el token o no es válido
    403 el token es de otro nodo
    409 seq repetido con otra hora (el contador del nodo se reinició)
    413 mensaje demasiado grande
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from comun import mensajes
from comun.fechas import iso
from procesador import ingreso

from . import bd, consultas, contexto
from .nodos import nodo_por_token

log = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")

# Una lectura pesa ~150 bytes; esto deja margen sin aceptar basura grande
TAMANO_MAX_LECTURA = 4096


def _error(codigo: int, texto: str, **extra: Any):
    respuesta = jsonify(error=texto, **extra)
    respuesta.status_code = codigo
    if codigo == 401:
        respuesta.headers["WWW-Authenticate"] = 'Bearer realm="huerto"'
    return respuesta


def _token() -> Optional[str]:
    cabecera = request.headers.get("Authorization", "")
    tipo, _, token = cabecera.partition(" ")
    if tipo.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _num(valor: Any, decimales: int = 1) -> Optional[float]:
    return None if valor is None else round(float(valor), decimales)


@bp.post("/lecturas")
def recibir_lectura():
    if (request.content_length or 0) > TAMANO_MAX_LECTURA:
        return _error(413, "mensaje demasiado grande")

    ctx = contexto()
    conn = bd()
    ahora = ctx.reloj()

    token = _token()
    nodo_id = nodo_por_token(conn, token, ahora) if token else None
    if nodo_id is None:
        conn.rollback()
        log.warning("POST /api/lecturas con token %s desde %s",
                    "inválido" if token else "ausente", request.remote_addr)
        return _error(401, "token inválido" if token else "falta el token (Authorization: Bearer ...)")

    cuerpo = request.get_data(cache=False)
    if len(cuerpo) > TAMANO_MAX_LECTURA:
        conn.rollback()
        return _error(413, "mensaje demasiado grande")
    try:
        datos = json.loads(cuerpo)
    except (ValueError, UnicodeDecodeError):
        datos = None
    if isinstance(datos, dict):
        nodo_mensaje = datos.get("nodo_id")
        if nodo_mensaje is not None and nodo_mensaje != nodo_id:
            conn.commit()   # guarda ultimo_uso_en
            return _error(403, f"el token es del nodo {nodo_id}, no de {nodo_mensaje}")

    # Si el JSON viene mal, ingreso lo registra como incidencia y responde INVALIDA
    r = ingreso.guardar_lectura(conn, nodo_id, cuerpo, ahora, ctx.cfg.bd)

    if r.estado == ingreso.INVALIDA:
        return _error(400, r.error or "mensaje inválido")
    if r.estado == ingreso.SEQ_REINICIADO:
        return _error(409, "seq repetido con otra hora: el contador del nodo se reinició",
                      seq=r.lectura.seq)
    conn.commit()
    if r.estado == ingreso.DUPLICADA:
        return jsonify(estado="duplicada", lectura_id=r.lectura_id, seq=r.lectura.seq), 200

    try:
        ctx.difusor.avisar_lectura(r.lectura_id)
    except Exception:  # la lectura ya está guardada: no se le responde error al nodo
        log.exception("No se pudo avisar al procesador de la lectura %s", r.lectura_id)

    lv = r.lectura
    if not lv.valida or lv.invalidos:
        log.info("[%s] seq=%s guardada con datos inválidos: %s", nodo_id, lv.seq, lv.motivo)
    return jsonify(estado="guardada", lectura_id=r.lectura_id, seq=lv.seq,
                   valida=lv.valida, campos_invalidos=sorted(lv.invalidos),
                   motivo_invalida=lv.motivo), 201


@bp.get("/camas/<nodo_id>/ultima")
def ultima_lectura(nodo_id: str):
    """HU-01: la lectura válida de mayor medido_en, no la última que llegó."""
    conn = bd()
    fila = consultas.cama_por_nodo(conn, nodo_id)
    if fila is None:
        return _error(404, "nodo desconocido", nodo_id=nodo_id)
    cama = consultas.cama(conn, fila["id"])
    lectura = consultas.lectura_actual(conn, fila["id"])
    if lectura is None:
        return jsonify(nodo_id=nodo_id, cama=cama["nombre"], lectura=None,
                       mensaje=mensajes.SIN_LECTURAS)
    return jsonify(
        nodo_id=nodo_id,
        cama=cama["nombre"],
        mensaje=None,
        lectura={
            "seq": lectura["seq"],
            "medido_en": iso(lectura["medido_en"]),
            "recibido_en": iso(lectura["recibido_en"]),
            "temp": _num(lectura["temp"]),
            "hum_aire": _num(lectura["hum_aire"]),
            "suelo_pct": _num(lectura["suelo_prom"]),
            "suelo_mv": lectura["suelo_mv"],
            "luz": _num(lectura["lux"], 0),
        },
    )
