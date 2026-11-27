"""Pantalla del huerto: tablero, detalle de cama, API y eventos en tiempo real."""

from __future__ import annotations

import queue
from datetime import timedelta
from typing import Any, Optional

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request

from comun import mensajes
from comun.fechas import inicio_del_dia_utc, iso, parsear_iso_utc
from comun.rangos import rango_efectivo

from . import bd, consultas, contexto

bp = Blueprint("tablero", __name__)

LATIDO_SSE_S = 15
PUNTOS_MAX_GRAFICO = 720


def _num(valor: Any, decimales: int = 1) -> Optional[float]:
    return None if valor is None else round(float(valor), decimales)


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@bp.get("/")
def tablero():
    # ?kiosco=1 en la pantalla del huerto: solo esa pantalla mide latencias (CQ-02/03),
    # porque usa el mismo reloj que la Pi y los nodos.
    return render_template("tablero.html", kiosco=request.args.get("kiosco") == "1")


@bp.get("/favicon.ico")
def favicon():
    return current_app.send_static_file("favicon.svg")


@bp.get("/cama/<int:cama_id>")
def detalle(cama_id: int):
    cama = consultas.cama(bd(), cama_id)
    if cama is None or not cama["activa"]:
        abort(404)
    return render_template("cama.html", cama=cama)


# ---------------------------------------------------------------------------
# API de lectura
# ---------------------------------------------------------------------------

def _tarjeta_desde_bd(conn, cama: dict, estado: Optional[dict]) -> dict:
    """Respaldo si la web arrancó y aún no recibe la tarjeta retenida del broker."""
    actual = consultas.lectura_actual(conn, cama["id"])
    lectura = None
    if actual:
        lectura = {"seq": actual["seq"], "medido_en": iso(actual["medido_en"]),
                   "suelo_prom": _num(actual["suelo_prom"]), "suelo": actual["suelo_detalle"],
                   "temp": _num(actual["temp"]), "hum_aire": _num(actual["hum_aire"]),
                   "lux": _num(actual["lux"], 0)}
    return {
        "nodo_id": cama["nodo_id"],
        "color": estado["estado_nuevo"] if estado else "gris",
        "mensaje": estado["mensaje"] if estado else mensajes.SIN_LECTURAS,
        "lectura": lectura,
        "texto_lectura": None if actual else mensajes.SIN_LECTURAS,
        "horas_luz_hoy": None,
        "texto_luz": None,            # desconocido hasta que llegue la tarjeta del procesador
        "alertas_nuevas": [],
    }


@bp.get("/api/tablero")
def api_tablero():
    ctx, conn = contexto(), bd()
    estados = None
    camas = []
    for cama in consultas.camas(conn):
        tarjeta = ctx.difusor.tarjetas.get(cama["nodo_id"])
        if tarjeta is None:
            if estados is None:
                estados = consultas.ultimos_estados(conn)
            tarjeta = _tarjeta_desde_bd(conn, cama, estados.get(cama["id"]))
        # Nombre y cultivo siempre desde la BD (pueden haber cambiado recién)
        camas.append({**tarjeta, "cama_id": cama["id"], "nombre": cama["nombre"],
                      "cultivo": cama["cultivo_nombre"],
                      "conexion": ctx.difusor.conexiones.get(cama["nodo_id"])})
    return jsonify(camas=camas, central_conectada=ctx.difusor.conectado,
                   hora_servidor=iso(ctx.reloj()))


def _alerta(a: dict) -> dict:
    return {"id": a["id"], "cama_id": a["cama_id"], "cama": a["cama"], "tipo": a["tipo"],
            "mensaje": a["mensaje"], "estado": a["estado"],
            "iniciada_en": iso(a["iniciada_en"]), "resuelta_en": iso(a["resuelta_en"])}


@bp.get("/api/alertas")
def api_alertas():
    ctx, conn = contexto(), bd()
    inicio_hoy = inicio_del_dia_utc(ctx.reloj(), ctx.zona)
    return jsonify(
        abiertas=[_alerta(a) for a in consultas.alertas_abiertas(conn)],
        resueltas_hoy=[_alerta(a) for a in consultas.alertas_resueltas_desde(conn, inicio_hoy)],
    )


@bp.get("/api/camas/<int:cama_id>/serie")
def api_serie(cama_id: int):
    ctx, conn = contexto(), bd()
    cama = consultas.cama(conn, cama_id)
    if cama is None:
        abort(404)
    horas = max(1, min(request.args.get("horas", 24, type=int), 168))
    hasta = ctx.reloj()
    desde = hasta - timedelta(hours=horas)
    balde = max(60, horas * 3600 // PUNTOS_MAX_GRAFICO)

    puntos: list[dict] = []
    anterior = None
    for f in consultas.serie(conn, cama_id, desde, hasta, balde):
        t = int(f["t"])
        if anterior is not None and t - anterior > 3 * balde:
            # Hueco sin datos: un punto vacío corta la línea del gráfico
            puntos.append({"t": (anterior + balde) * 1000, "suelo": None, "temp": None,
                           "hum_aire": None, "lux": None})
        puntos.append({"t": t * 1000, "suelo": _num(f["suelo"]), "temp": _num(f["temp"]),
                       "hum_aire": _num(f["hum_aire"]), "lux": _num(f["lux"], 0)})
        anterior = t

    rango = rango_efectivo(cama)
    alertas = consultas.alertas_de_cama(conn, cama_id, hasta - timedelta(days=7))
    return jsonify(
        cama={"id": cama["id"], "nombre": cama["nombre"], "cultivo": cama["cultivo_nombre"],
              "zona": cama["zona_climatica"]},
        rango={"humedad_min": rango.humedad_min, "humedad_max": rango.humedad_max,
               "temp_min": rango.temp_min, "temp_max": rango.temp_max,
               "horas_luz_min": rango.horas_luz_min},
        umbral_luz=ctx.cfg.umbral_luz_lux,
        desde=iso(desde), hasta=iso(hasta),
        puntos=puntos,
        alertas=[_alerta(a) for a in alertas],
    )


# ---------------------------------------------------------------------------
# Tiempo real (Server-Sent Events)
# ---------------------------------------------------------------------------

@bp.get("/api/eventos")
def api_eventos():
    difusor = contexto().difusor
    cola = difusor.suscribir()

    def generar():
        try:
            yield "retry: 3000\n\n"            # el navegador reintenta a los 3 s si se corta
            while True:
                try:
                    tipo, datos = cola.get(timeout=LATIDO_SSE_S)
                except queue.Empty:
                    yield ": latido\n\n"       # mantiene viva la conexión
                    continue
                yield f"event: {tipo}\ndata: {datos}\n\n"
        finally:
            difusor.desuscribir(cola)

    return Response(generar(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Mediciones de calidad que envía la pantalla del kiosco (CQ-02, CQ-03)
# ---------------------------------------------------------------------------

def _json_requerido() -> dict:
    # Exigir JSON obliga a otros sitios a pasar por CORS: no pueden enviar datos falsos
    if not request.is_json:
        abort(415)
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        abort(400)
    return datos


@bp.post("/api/latencia")
def api_latencia():
    datos = _json_requerido()
    medido = parsear_iso_utc(datos.get("medido_en"))
    mostrado = parsear_iso_utc(datos.get("mostrado_en"))
    seq, nodo_id = datos.get("seq"), datos.get("nodo_id")
    if (medido is None or mostrado is None or not isinstance(seq, int)
            or not isinstance(nodo_id, str)):
        abort(400)
    if not timedelta(seconds=-60) <= mostrado - medido <= timedelta(days=1):
        abort(422)        # relojes muy desfasados: no sirve como medición
    cama = consultas.cama_por_nodo(bd(), nodo_id)
    if cama is None:
        abort(404)
    ms = consultas.registrar_latencia(bd(), cama["id"], seq, medido, mostrado)
    return jsonify(latencia_ms=ms), 201


@bp.post("/api/alertas/visibles")
def api_alertas_visibles():
    datos = _json_requerido()
    ids, visible = datos.get("ids"), parsear_iso_utc(datos.get("visible_en"))
    if (visible is None or not isinstance(ids, list) or len(ids) > 200
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        abort(400)
    n = consultas.marcar_alertas_visibles(bd(), ids, visible)
    return jsonify(marcadas=n)
