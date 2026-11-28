"""Tendencias de una cama (RF-15, HU-02 «además consultar cálculo de tendencia»).

* GET /api/camas/<id>/tendencia            pendientes del suelo (6 h y 24 h) con
                                            etiqueta, medias móviles de 24 h,
                                            amplitud térmica vs. el exterior y la
                                            predicción del tiempo hasta el mínimo
  ?horas=N  agrega la serie horaria de medias móviles de las últimas N horas.

Se carga aparte de la tarjeta: si falla, el tablero sigue igual.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from flask import Blueprint, abort, jsonify, request

from comun import ajustes
from comun.analitica import descriptiva
from comun.analitica import repositorio as repo_analitica
from comun.analitica.prediccion import ESTIMACION
from comun.analitica.servicio_tendencia import parametros, predecir_cama, prediccion_json

from . import bd, consultas, contexto

log = logging.getLogger(__name__)

bp = Blueprint("tendencia", __name__)

HORAS_MAX = 30 * 24


@bp.get("/api/tendencias")
def tendencias_tablero():
    """Etiqueta de tendencia y estimación de cada cama activa (para las tarjetas)."""
    ctx, conn = contexto(), bd()
    ahora = ctx.reloj()
    resultado = []
    try:
        vigentes = ajustes.leer(conn, ctx.cfg.bd)
        p = parametros(ctx.cfg.bd, vigentes)
        for cama in repo_analitica.camas(conn):
            if not cama["activa"]:
                continue
            pendiente = descriptiva.pendientes_suelo(conn, ctx.cfg.bd, cama["id"], ahora)[6]
            pred, _ = predecir_cama(conn, cama, ahora, p)
            resultado.append({
                "cama_id": cama["id"], "nodo_id": cama["nodo_id"],
                "etiqueta": pendiente.etiqueta,
                "pendiente_pts_h": None if pendiente.ajuste is None else round(pendiente.ajuste.pendiente, 2),
                "estimacion": pred.texto(cama["nombre"]) if pred.estado == ESTIMACION else None,
            })
        conn.commit()
    except Exception as e:
        log.exception("Error al calcular las tendencias del tablero: %s", e)
        conn.rollback()
        return jsonify(camas=[])
    return jsonify(camas=resultado)


@bp.get("/api/camas/<int:cama_id>/tendencia")
def tendencia_cama(cama_id: int):
    ctx, conn = contexto(), bd()
    cama = consultas.cama(conn, cama_id)
    if cama is None:
        abort(404)
    ahora = ctx.reloj()
    try:
        datos = descriptiva.resumen(conn, ctx.cfg.bd, cama_id, ahora)
        vigentes = ajustes.leer(conn, ctx.cfg.bd)
        cama_completa = repo_analitica.camas(conn, cama_id)[0]
        p = parametros(ctx.cfg.bd, vigentes)
        pred, ms = predecir_cama(conn, cama_completa, ahora, p)
        datos["prediccion"] = prediccion_json(pred, cama["nombre"], ms, p.horizonte_h)
        datos["alerta_preventiva_activa"] = bool(vigentes["tendencia_activa"])
        conn.commit()
        horas = request.args.get("horas", type=int)
        if horas:
            horas = max(1, min(horas, HORAS_MAX))
            datos["serie_media_movil"] = descriptiva.serie_medias_moviles(
                conn, cama_id, ahora - timedelta(hours=horas), ahora)
    except Exception as e:
        log.exception("Error al calcular la tendencia de la cama %s: %s", cama_id, e)
        conn.rollback()
        return jsonify(error="No se pudo calcular la tendencia", etiqueta=None), 200
    return jsonify(datos)
