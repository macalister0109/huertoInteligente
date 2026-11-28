"""Exportación de datos para ciencia de datos (CSV estándar y Parquet).

Conjuntos (detalle de cada columna en docs/diccionario_de_datos.md):
  lecturas        lecturas crudas con sus marcas de calidad
  agregados_hora  estadísticas por cama, hora y variable
  agregados_dia   estadísticas por cama, día (hora de Chile) y variable
  eventos_riego   riegos detectados (y manuales, en el futuro)
  alertas         alertas abiertas y resueltas
  clima           clima de referencia (instantáneas horarias)

Formato: separador «,», punto decimal, fechas ISO 8601 en UTC (…Z), vacío =
sin dato. Cada fila lleva origen = «real»: los datos sintéticos se generan
aparte (tools/generar_sinteticos.py) con origen = «sintetico» y NUNCA se
mezclan con estos.

Sin datos personales: solo variables ambientales y nombres de camas. Las
notas de los riegos manuales no se exportan (texto libre).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

from .agregados import limites_dia_local

ORIGEN = "real"
EXCLUYEN = ("rango", "salto", "pegado")

COLUMNAS = {
    "lecturas": ["origen", "lectura_id", "cama_id", "cama", "nodo_id", "seq", "medido_en_utc",
                 "recibido_en_utc", "suelo_pct", "suelo_mv", "temp_c", "hum_aire_pct", "luz_lux",
                 "valida", "motivo_invalida", "marcas", "excluir_suelo", "excluir_temp",
                 "excluir_hum_aire", "hueco_antes"],
    "agregados_hora": ["origen", "cama_id", "cama", "hora_inicio_utc", "variable", "media", "minimo",
                       "maximo", "desviacion", "n_lecturas", "n_excluidas", "n_esperadas", "cobertura"],
    "agregados_dia": ["origen", "cama_id", "cama", "fecha", "variable", "media", "minimo", "maximo",
                      "desviacion", "amplitud", "horas_fuera_rango", "n_lecturas", "n_excluidas",
                      "n_esperadas", "cobertura"],
    "eventos_riego": ["origen", "evento_id", "cama_id", "cama", "tipo_registro", "inicio_utc", "fin_utc",
                      "humedad_antes", "humedad_despues", "subida"],
    "alertas": ["origen", "alerta_id", "cama_id", "cama", "tipo", "variable", "estado", "mensaje",
                "valor_inicial", "valor_actual", "iniciada_en_utc", "actualizada_en_utc", "resuelta_en_utc"],
    "clima": ["origen", "fuente", "observado_en_utc", "lat", "lon", "temp_aire_c", "hum_rel_pct",
              "precipitacion_mm", "radiacion_wm2", "temp_suelo_c", "hum_suelo_vwc_pct", "et0_mm",
              "et0_hoy_mm"],
}
CONJUNTOS = tuple(COLUMNAS)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v) -> Optional[float]:
    return None if v is None else float(v)


def limites_utc(desde: date, hasta: date, zona: ZoneInfo) -> tuple[datetime, datetime]:
    """Días en hora de Chile [desde, hasta] (ambos incluidos) -> [inicio, fin) en UTC."""
    return limites_dia_local(desde, zona)[0], limites_dia_local(hasta, zona)[1]


def _filtro_cama(alias: str, cama_id: Optional[int]) -> tuple[str, list]:
    return (f" AND {alias}.cama_id = %s", [cama_id]) if cama_id is not None else ("", [])


def filas(conn, conjunto: str, desde: date, hasta: date, zona: ZoneInfo,
          cama_id: Optional[int] = None, lote: int = 2000) -> Iterator[dict]:
    """Filas del conjunto como dict (valores Python: datetime, float, int, str)."""
    if conjunto not in COLUMNAS:
        raise ValueError(f"Conjunto desconocido: {conjunto}")
    inicio, fin = limites_utc(desde, hasta, zona)
    yield from _GENERADORES[conjunto](conn, inicio, fin, desde, hasta, cama_id, lote)


def _consulta(conn, sql: str, args: list, lote: int) -> Iterator[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        while True:
            bloque = cur.fetchmany(lote)
            if not bloque:
                break
            yield from bloque
    conn.commit()


def _lecturas(conn, inicio, fin, desde, hasta, cama_id, lote):
    extra, args = _filtro_cama("l", cama_id)
    sql = f"""
        SELECT l.id, l.cama_id, c.nombre AS cama, c.nodo_id, l.seq, l.medido_en, l.recibido_en,
               l.suelo_prom, l.suelo_mv, l.temp, l.hum_aire, l.lux, l.valida, l.motivo_invalida,
               GROUP_CONCAT(CONCAT(q.variable, ':', q.marca) ORDER BY q.variable, q.marca SEPARATOR ';') AS marcas
          FROM lecturas l
          JOIN camas c ON c.id = l.cama_id
          LEFT JOIN calidad_lecturas q ON q.lectura_id = l.id
         WHERE l.medido_en >= %s AND l.medido_en < %s{extra}
         GROUP BY l.id
         ORDER BY l.cama_id, l.medido_en, l.id"""
    for f in _consulta(conn, sql, [inicio, fin, *args], lote):
        marcas = f["marcas"] or ""
        lista = marcas.split(";") if marcas else []
        yield {
            "origen": ORIGEN, "lectura_id": f["id"], "cama_id": f["cama_id"], "cama": f["cama"],
            "nodo_id": f["nodo_id"], "seq": f["seq"], "medido_en_utc": f["medido_en"],
            "recibido_en_utc": f["recibido_en"], "suelo_pct": _num(f["suelo_prom"]),
            "suelo_mv": f["suelo_mv"], "temp_c": _num(f["temp"]), "hum_aire_pct": _num(f["hum_aire"]),
            "luz_lux": _num(f["lux"]), "valida": int(f["valida"]), "motivo_invalida": f["motivo_invalida"],
            "marcas": marcas or None,
            **{f"excluir_{v}": int(any(m in lista for m in (f"{v}:{x}" for x in EXCLUYEN)))
               for v in ("suelo", "temp", "hum_aire")},
            "hueco_antes": int("lectura:hueco" in lista),
        }


def _agregados_hora(conn, inicio, fin, desde, hasta, cama_id, lote):
    extra, args = _filtro_cama("a", cama_id)
    sql = f"""SELECT a.*, c.nombre AS cama FROM agregados_hora a JOIN camas c ON c.id = a.cama_id
               WHERE a.hora_inicio >= %s AND a.hora_inicio < %s{extra}
               ORDER BY a.cama_id, a.hora_inicio, a.variable"""
    for f in _consulta(conn, sql, [inicio, fin, *args], lote):
        yield {"origen": ORIGEN, "cama_id": f["cama_id"], "cama": f["cama"],
               "hora_inicio_utc": f["hora_inicio"], "variable": f["variable"],
               **{k: _num(f[k]) for k in ("media", "minimo", "maximo", "desviacion", "cobertura")},
               **{k: f[k] for k in ("n_lecturas", "n_excluidas", "n_esperadas")}}


def _agregados_dia(conn, inicio, fin, desde, hasta, cama_id, lote):
    extra, args = _filtro_cama("a", cama_id)
    sql = f"""SELECT a.*, c.nombre AS cama FROM agregados_dia a JOIN camas c ON c.id = a.cama_id
               WHERE a.fecha BETWEEN %s AND %s{extra}
               ORDER BY a.cama_id, a.fecha, a.variable"""
    for f in _consulta(conn, sql, [desde, hasta, *args], lote):
        yield {"origen": ORIGEN, "cama_id": f["cama_id"], "cama": f["cama"], "fecha": f["fecha"],
               "variable": f["variable"],
               **{k: _num(f[k]) for k in ("media", "minimo", "maximo", "desviacion", "amplitud",
                                          "horas_fuera_rango", "cobertura")},
               **{k: f[k] for k in ("n_lecturas", "n_excluidas", "n_esperadas")}}


def _eventos_riego(conn, inicio, fin, desde, hasta, cama_id, lote):
    extra, args = _filtro_cama("e", cama_id)
    sql = f"""SELECT e.id, e.cama_id, c.nombre AS cama, e.origen, e.inicio, e.fin,
                     e.humedad_antes, e.humedad_despues
                FROM eventos_riego e JOIN camas c ON c.id = e.cama_id
               WHERE e.inicio >= %s AND e.inicio < %s{extra}
               ORDER BY e.cama_id, e.inicio"""
    for f in _consulta(conn, sql, [inicio, fin, *args], lote):
        antes, despues = _num(f["humedad_antes"]), _num(f["humedad_despues"])
        yield {"origen": ORIGEN, "evento_id": f["id"], "cama_id": f["cama_id"], "cama": f["cama"],
               "tipo_registro": f["origen"], "inicio_utc": f["inicio"], "fin_utc": f["fin"],
               "humedad_antes": antes, "humedad_despues": despues,
               "subida": None if antes is None or despues is None else round(despues - antes, 2)}


def _alertas(conn, inicio, fin, desde, hasta, cama_id, lote):
    extra, args = _filtro_cama("a", cama_id)
    sql = f"""SELECT a.*, c.nombre AS cama FROM alertas a JOIN camas c ON c.id = a.cama_id
               WHERE a.iniciada_en >= %s AND a.iniciada_en < %s{extra}
               ORDER BY a.cama_id, a.iniciada_en"""
    for f in _consulta(conn, sql, [inicio, fin, *args], lote):
        yield {"origen": ORIGEN, "alerta_id": f["id"], "cama_id": f["cama_id"], "cama": f["cama"],
               "tipo": f["tipo"], "variable": f["variable"], "estado": f["estado"], "mensaje": f["mensaje"],
               "valor_inicial": _num(f["valor_inicial"]), "valor_actual": _num(f["valor_actual"]),
               "iniciada_en_utc": f["iniciada_en"], "actualizada_en_utc": f["actualizada_en"],
               "resuelta_en_utc": f["resuelta_en"]}


def _clima(conn, inicio, fin, desde, hasta, cama_id, lote):
    sql = """SELECT * FROM clima_referencia WHERE observado_en >= %s AND observado_en < %s
              ORDER BY fuente, observado_en"""
    for f in _consulta(conn, sql, [inicio, fin], lote):
        yield {"origen": ORIGEN, "fuente": f["fuente"], "observado_en_utc": f["observado_en"],
               **{k: _num(f[k]) for k in COLUMNAS["clima"][3:]}}


_GENERADORES = {"lecturas": _lecturas, "agregados_hora": _agregados_hora,
                "agregados_dia": _agregados_dia, "eventos_riego": _eventos_riego,
                "alertas": _alertas, "clima": _clima}


# ------------------------------------------------------------------- CSV

def _celda(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return _iso(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(round(v, 6))
    return str(v)


def csv_por_partes(conjunto: str, filas_: Iterable[dict], cada: int = 1000) -> Iterator[str]:
    """CSV estándar (UTF-8, «,», punto decimal) en trozos, para enviarlo sin
    cargar todo en memoria."""
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    columnas = COLUMNAS[conjunto]
    w.writerow(columnas)
    for i, f in enumerate(filas_, start=1):
        w.writerow([_celda(f.get(c)) for c in columnas])
        if i % cada == 0:
            yield salida.getvalue()
            salida.seek(0)
            salida.truncate()
    yield salida.getvalue()


def escribir_csv(conjunto: str, filas_: Iterable[dict], destino) -> int:
    n = 0
    with open(destino, "w", encoding="utf-8", newline="") as f:
        for parte in csv_por_partes(conjunto, filas_):
            f.write(parte)
            n += parte.count("\n")
    return max(0, n - 1)
