"""Historial de una cama: resumen por día y descarga de las lecturas en CSV.

    GET /api/camas/<id>/diario?dias=30          promedio, mínimo y máximo de cada día
    GET /cama/<id>/lecturas.csv?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

Los días se cuentan en hora de Chile (ZONA_HORARIA), no en UTC.
El CSV usa ";" y coma decimal: así Excel en español lo abre en columnas.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Iterator, Optional

from flask import Blueprint, Response, abort, jsonify, request, stream_with_context

from . import bd, consultas, contexto

bp = Blueprint("historial", __name__)

DIAS_MAX_RESUMEN = 366
DIAS_MAX_CSV = 366
DIAS_CSV_POR_DEFECTO = 7


# ---------------------------------------------------------------------------
# Días en hora local
# ---------------------------------------------------------------------------

def hoy_local() -> date:
    ctx = contexto()
    return ctx.reloj().replace(tzinfo=timezone.utc).astimezone(ctx.zona).date()


def inicio_dia_utc(dia: date) -> datetime:
    """Medianoche (hora de Chile) de `dia`, en UTC ingenuo."""
    local = datetime.combine(dia, time(0), tzinfo=contexto().zona)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def dia_local(t_utc: datetime) -> date:
    return t_utc.replace(tzinfo=timezone.utc).astimezone(contexto().zona).date()


def _cama_activa(cama_id: int) -> dict:
    cama = consultas.cama(bd(), cama_id)
    if cama is None or not cama["activa"]:
        abort(404)
    return cama


# ---------------------------------------------------------------------------
# Resumen diario
# ---------------------------------------------------------------------------

class _Acumulador:
    """Suma, cuenta, mínimo y máximo de una variable a lo largo de un día."""

    def __init__(self):
        self.suma, self.n, self.minimo, self.maximo = 0.0, 0, None, None

    def agregar(self, suma, n, minimo, maximo) -> None:
        if not n:
            return
        self.suma += float(suma)
        self.n += int(n)
        self.minimo = float(minimo) if self.minimo is None else min(self.minimo, float(minimo))
        self.maximo = float(maximo) if self.maximo is None else max(self.maximo, float(maximo))

    def resultado(self) -> Optional[dict]:
        if not self.n:
            return None
        return {"prom": round(self.suma / self.n, 1), "min": round(self.minimo, 1),
                "max": round(self.maximo, 1)}


def resumen_diario(cama_id: int, dias: int) -> list[dict]:
    """Un elemento por día (del más reciente al más antiguo), incluidos los días
    sin datos (lecturas = 0), para que se noten los huecos."""
    hoy = hoy_local()
    primer_dia = hoy - timedelta(days=dias - 1)
    desde = inicio_dia_utc(primer_dia)
    hasta = inicio_dia_utc(hoy + timedelta(days=1))

    por_dia: dict[date, dict] = {
        primer_dia + timedelta(days=i): {"suelo": _Acumulador(), "temp": _Acumulador(),
                                         "hum_aire": _Acumulador(), "lecturas": 0}
        for i in range(dias)
    }
    # La BD agrupa por hora (UTC) y aquí se juntan las horas de cada día local:
    # así los cambios de horario de verano quedan bien sin tablas de zonas en MariaDB.
    for f in consultas.resumen_por_hora(bd(), cama_id, desde, hasta):
        dia = por_dia.get(dia_local(datetime.fromtimestamp(int(f["hora"]), timezone.utc)
                                    .replace(tzinfo=None)))
        if dia is None:
            continue
        dia["lecturas"] += int(f["lecturas"])
        for var in ("suelo", "temp", "hum_aire"):
            dia[var].agregar(f[f"{var}_suma"], f[f"{var}_n"], f[f"{var}_min"], f[f"{var}_max"])

    return [
        {"fecha": d.isoformat(), "lecturas": v["lecturas"], "suelo": v["suelo"].resultado(),
         "temp": v["temp"].resultado(), "hum_aire": v["hum_aire"].resultado()}
        for d, v in sorted(por_dia.items(), reverse=True)
    ]


@bp.get("/api/camas/<int:cama_id>/diario")
def api_diario(cama_id: int):
    cama = _cama_activa(cama_id)
    dias = max(1, min(request.args.get("dias", 30, type=int), DIAS_MAX_RESUMEN))
    return jsonify(cama={"id": cama["id"], "nombre": cama["nombre"]}, dias=resumen_diario(cama_id, dias))


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

COLUMNAS_CSV = ["fecha_hora_chile", "fecha_hora_utc", "seq", "humedad_suelo_pct", "suelo_mv",
                "temperatura_c", "humedad_aire_pct", "luz_lux", "valida", "motivo_invalida"]


def _numero(valor, decimales: int = 1) -> str:
    """12.5 -> '12,5' (coma decimal); None -> '' (celda vacía)."""
    if valor is None:
        return ""
    texto = f"{float(valor):.{decimales}f}".rstrip("0").rstrip(".") if decimales else f"{float(valor):.0f}"
    return texto.replace(".", ",")


def _fecha_param(nombre: str, por_defecto: date) -> date:
    texto = request.args.get(nombre)
    if not texto:
        return por_defecto
    try:
        return date.fromisoformat(texto)
    except ValueError:
        abort(400, f"{nombre}: usa el formato AAAA-MM-DD")


def filas_csv(filas: Iterable[dict]) -> Iterator[str]:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")

    def volcar() -> str:
        texto = salida.getvalue()
        salida.seek(0)
        salida.truncate()
        return texto

    # BOM: Excel reconoce el archivo como UTF-8 y muestra bien los acentos
    yield "﻿"
    escritor.writerow(COLUMNAS_CSV)
    yield volcar()
    zona = contexto().zona
    for i, f in enumerate(filas, start=1):
        utc = f["medido_en"]
        local = utc.replace(tzinfo=timezone.utc).astimezone(zona)
        escritor.writerow([
            local.strftime("%Y-%m-%d %H:%M:%S"), utc.strftime("%Y-%m-%d %H:%M:%S"), f["seq"],
            _numero(f["suelo_prom"]), "" if f["suelo_mv"] is None else f["suelo_mv"],
            _numero(f["temp"]), _numero(f["hum_aire"]), _numero(f["lux"], 0),
            "sí" if f["valida"] else "no", f["motivo_invalida"] or "",
        ])
        if i % 500 == 0:
            yield volcar()
    yield volcar()


@bp.get("/cama/<int:cama_id>/lecturas.csv")
def descargar_csv(cama_id: int):
    cama = _cama_activa(cama_id)
    hoy = hoy_local()
    hasta = _fecha_param("hasta", hoy)
    desde = _fecha_param("desde", hasta - timedelta(days=DIAS_CSV_POR_DEFECTO - 1))
    if desde > hasta:
        abort(400, "La fecha «desde» debe ser anterior o igual a «hasta».")
    if (hasta - desde).days + 1 > DIAS_MAX_CSV:
        abort(400, f"Como máximo {DIAS_MAX_CSV} días por archivo.")

    desde_utc, hasta_utc = inicio_dia_utc(desde), inicio_dia_utc(hasta + timedelta(days=1))

    def filas() -> Iterator[dict]:
        # Conexión propia: la de la petición se cierra antes de terminar de enviar
        conn = contexto().conectar_bd()
        try:
            yield from consultas.lecturas_para_csv(conn, cama_id, desde_utc, hasta_utc)
        finally:
            conn.close()

    nombre = f"lecturas_{cama['nodo_id']}_{desde.isoformat()}_{hasta.isoformat()}.csv"
    return Response(
        stream_with_context(filas_csv(filas())),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                 "Cache-Control": "no-store"},
    )
