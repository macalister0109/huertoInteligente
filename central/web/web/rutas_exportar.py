"""Exportación de datos para análisis (CSV estándar).

    GET /api/exportar/<conjunto>.csv?desde=AAAA-MM-DD&hasta=AAAA-MM-DD&cama=<id>

conjunto: lecturas | agregados_hora | agregados_dia | eventos_riego | alertas | clima
Fechas en hora de Chile, ambas incluidas (por defecto, los últimos 7 días).

Acceso: sesión docente (PIN) o «Authorization: Bearer <EXPORT_TOKEN>» (para
scripts y notebooks). Parquet: con el comando tools/exportar.py.
"""

from __future__ import annotations

import hmac
from datetime import date, timedelta

from flask import Blueprint, Response, abort, jsonify, redirect, request, stream_with_context, url_for

from comun.analitica import exportacion

from . import contexto
from .rutas_config import es_docente
from .rutas_historial import hoy_local

bp = Blueprint("exportar", __name__)

DIAS_MAX = 366
DIAS_POR_DEFECTO = 7


def autorizado() -> bool:
    if es_docente():
        return True
    token = contexto().cfg.export_token
    cabecera = request.headers.get("Authorization", "")
    if not token or not cabecera.startswith("Bearer "):
        return False
    return hmac.compare_digest(cabecera[len("Bearer "):].strip().encode(), token.encode())


def _fecha(nombre: str, por_defecto: date) -> date:
    texto = request.args.get(nombre)
    if not texto:
        return por_defecto
    try:
        return date.fromisoformat(texto)
    except ValueError:
        abort(400, f"{nombre}: usa el formato AAAA-MM-DD")


@bp.get("/api/exportar")
def exportar_formulario():
    """El formulario de /configuracion envía ?conjunto=…: se redirige a la URL del archivo."""
    conjunto = request.args.get("conjunto", "")
    if conjunto not in exportacion.CONJUNTOS:
        abort(404)
    parametros = {k: v for k, v in request.args.items() if k != "conjunto" and v}
    return redirect(url_for("exportar.exportar_csv", conjunto=conjunto, **parametros))


@bp.get("/api/exportar/<conjunto>.csv")
def exportar_csv(conjunto: str):
    if not autorizado():
        return jsonify(error="Necesitas entrar con el PIN docente o enviar el token de exportación."), 401
    if conjunto not in exportacion.CONJUNTOS:
        abort(404)
    hasta = _fecha("hasta", hoy_local())
    desde = _fecha("desde", hasta - timedelta(days=DIAS_POR_DEFECTO - 1))
    if desde > hasta:
        abort(400, "La fecha «desde» debe ser anterior o igual a «hasta».")
    if (hasta - desde).days + 1 > DIAS_MAX:
        abort(400, f"Como máximo {DIAS_MAX} días por archivo.")
    cama_id = request.args.get("cama", type=int)
    ctx = contexto()

    def partes():
        # Conexión propia: la de la petición se cierra antes de terminar de enviar
        conn = ctx.conectar_bd()
        try:
            yield from exportacion.csv_por_partes(
                conjunto, exportacion.filas(conn, conjunto, desde, hasta, ctx.zona, cama_id))
        finally:
            conn.close()

    sufijo = f"_cama{cama_id}" if cama_id is not None else ""
    nombre = f"{conjunto}{sufijo}_{desde.isoformat()}_{hasta.isoformat()}.csv"
    return Response(stream_with_context(partes()), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                             "Cache-Control": "no-store"})
