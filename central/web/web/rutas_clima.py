"""Clima exterior de referencia en el tablero (se carga APARTE de las camas).

* GET /api/clima/actual            clima normalizado + fuente + edad + estado
* GET /api/clima/camas             comparación de la lectura actual de cada cama
* GET /api/camas/<id>/clima        comparación + serie horaria para el detalle

Si la API externa falla o tarda, estas rutas responden «no disponible» o el
último dato, y la carga de camas, lecturas y alertas no se entera.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from flask import Blueprint, abort, jsonify, request

from . import bd, consultas, contexto

log = logging.getLogger(__name__)

bp = Blueprint("clima", __name__)

HORAS_MAX = 30 * 24


def _sin_clima(error: Exception):
    # Un error inesperado del clima nunca debe romper el tablero
    log.exception("Error en el bloque de clima: %s", error)
    return jsonify(estado="no_disponible", texto_estado="Clima exterior no disponible", clima=None)


@bp.get("/api/clima/actual")
def clima_actual():
    try:
        return jsonify(contexto().clima.actual(bd()))
    except Exception as e:
        return _sin_clima(e)


@bp.get("/api/clima/camas")
def clima_camas():
    ctx, conn = contexto(), bd()
    resultado = []
    try:
        for cama in consultas.camas(conn):
            actual = consultas.lectura_actual(conn, cama["id"])
            resultado.append({"cama_id": cama["id"], "nodo_id": cama["nodo_id"],
                              "comparacion": ctx.clima.comparar(conn, actual)})
    except Exception as e:
        log.exception("Error al comparar con el clima exterior: %s", e)
        return jsonify(camas=[])
    return jsonify(camas=resultado)


@bp.get("/api/camas/<int:cama_id>/clima")
def clima_cama(cama_id: int):
    ctx, conn = contexto(), bd()
    cama = consultas.cama(conn, cama_id)
    if cama is None:
        abort(404)
    horas = max(1, min(request.args.get("horas", 24, type=int), HORAS_MAX))
    hasta = ctx.reloj()
    try:
        actual = consultas.lectura_actual(conn, cama_id)
        lectura = None
        if actual:
            lectura = {"temp": actual["temp"], "hum_aire": actual["hum_aire"],
                       "suelo_prom": actual["suelo_prom"]}
        return jsonify(lectura=lectura,
                       comparacion=ctx.clima.comparar(conn, actual),
                       serie=ctx.clima.serie(conn, hasta - timedelta(hours=horas), hasta))
    except Exception as e:
        log.exception("Error al comparar la cama %s con el clima exterior: %s", cama_id, e)
        return jsonify(lectura=None, comparacion=None, serie=[])
