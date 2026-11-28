"""SQL de la capa de análisis. Solo LEE `lecturas`; escribe en las tablas
calculadas (calidad_lecturas, agregados_hora, agregados_dia). Sin commit."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Iterable, Optional

from ..rangos import SELECT_CAMA as _SELECT_CAMA_COMUN
from .agregados import Agregado
from .calidad import LecturaCruda, Marca
from .riego import DETECTADO, EventoRiego

SELECT_CAMA = _SELECT_CAMA_COMUN      # cama + cultivo + zona (comun/rangos.py)


def _num(v) -> Optional[float]:
    return None if v is None else float(v)


def camas(conn, cama_id: Optional[int] = None) -> list[dict]:
    with conn.cursor() as cur:
        if cama_id is None:
            cur.execute(SELECT_CAMA + " ORDER BY c.id")
        else:
            cur.execute(SELECT_CAMA + " WHERE c.id = %s", (cama_id,))
        return list(cur.fetchall())


def lecturas_entre(conn, cama_id: int, desde: datetime, hasta: datetime) -> list[LecturaCruda]:
    """Lecturas medidas en [desde, hasta), en orden. Incluye las inválidas
    (cuentan para los huecos y la cobertura; sus valores ya vienen en NULL)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT id, medido_en, suelo_prom, temp, hum_aire, campos_invalidos
                         FROM lecturas
                        WHERE cama_id = %s AND medido_en >= %s AND medido_en < %s
                        ORDER BY medido_en, id""", (cama_id, desde, hasta))
        filas = cur.fetchall()
    resultado = []
    for f in filas:
        invalidos = f["campos_invalidos"]
        if isinstance(invalidos, (str, bytes)):
            try:
                invalidos = json.loads(invalidos)
            except ValueError:
                invalidos = {}
        resultado.append(LecturaCruda(f["id"], f["medido_en"], _num(f["suelo_prom"]),
                                      _num(f["temp"]), _num(f["hum_aire"]), invalidos or {}))
    return resultado


def reemplazar_marcas(conn, cama_id: int, desde: datetime, hasta: datetime,
                      marcas: Iterable[Marca], ahora: datetime) -> int:
    """Borra las marcas del rango y escribe las nuevas (recalcular no duplica)."""
    filas = [(m.lectura_id, cama_id, m.medido_en, m.variable, m.marca, m.detalle, ahora)
             for m in marcas if desde <= m.medido_en < hasta]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM calidad_lecturas WHERE cama_id = %s AND medido_en >= %s "
                    "AND medido_en < %s", (cama_id, desde, hasta))
        if filas:
            cur.executemany("""INSERT INTO calidad_lecturas
                                   (lectura_id, cama_id, medido_en, variable, marca, detalle, calculado_en)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""", filas)
    return len(filas)


def reemplazar_agregados_hora(conn, cama_id: int, desde: datetime, hasta: datetime,
                              agregados: Iterable[Agregado], ahora: datetime) -> int:
    filas = [(a.cama_id, a.periodo, a.variable, a.estadisticas.media, a.estadisticas.minimo,
              a.estadisticas.maximo, a.estadisticas.desviacion, a.estadisticas.n, a.n_excluidas,
              a.n_esperadas, a.cobertura, ahora) for a in agregados]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agregados_hora WHERE cama_id = %s AND hora_inicio >= %s "
                    "AND hora_inicio < %s", (cama_id, desde, hasta))
        if filas:
            cur.executemany("""INSERT INTO agregados_hora
                    (cama_id, hora_inicio, variable, media, minimo, maximo, desviacion,
                     n_lecturas, n_excluidas, n_esperadas, cobertura, calculado_en)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", filas)
    return len(filas)


def reemplazar_agregados_dia(conn, cama_id: int, fechas: Iterable[date],
                             agregados: Iterable[Agregado], ahora: datetime) -> int:
    fechas = list(fechas)
    filas = [(a.cama_id, a.periodo, a.variable, a.estadisticas.media, a.estadisticas.minimo,
              a.estadisticas.maximo, a.estadisticas.desviacion, a.amplitud, a.horas_fuera_rango,
              a.estadisticas.n, a.n_excluidas, a.n_esperadas, a.cobertura, ahora)
             for a in agregados]
    with conn.cursor() as cur:
        if fechas:
            marcadores = ", ".join(["%s"] * len(fechas))
            cur.execute(f"DELETE FROM agregados_dia WHERE cama_id = %s AND fecha IN ({marcadores})",
                        (cama_id, *fechas))
        if filas:
            cur.executemany("""INSERT INTO agregados_dia
                    (cama_id, fecha, variable, media, minimo, maximo, desviacion, amplitud,
                     horas_fuera_rango, n_lecturas, n_excluidas, n_esperadas, cobertura, calculado_en)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", filas)
    return len(filas)


def reemplazar_riegos_detectados(conn, cama_id: int, desde: datetime, hasta: datetime,
                                 eventos: Iterable[EventoRiego], ahora: datetime) -> int:
    """Riegos detectados con inicio en [desde, hasta). Se actualizan por
    (cama, inicio) para que su id no cambie al recalcular; los que ya no se
    detectan se borran. Los de origen 'manual' nunca se tocan."""
    nuevos = [e for e in eventos if desde <= e.inicio < hasta]
    with conn.cursor() as cur:
        for e in nuevos:
            cur.execute("""INSERT INTO eventos_riego
                               (cama_id, origen, inicio, fin, humedad_antes, humedad_despues,
                                lectura_antes_id, lectura_despues_id, calculado_en)
                           VALUES (%s, 'detectado', %s, %s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE fin = VALUES(fin),
                               humedad_antes = VALUES(humedad_antes),
                               humedad_despues = VALUES(humedad_despues),
                               lectura_antes_id = VALUES(lectura_antes_id),
                               lectura_despues_id = VALUES(lectura_despues_id),
                               calculado_en = VALUES(calculado_en)""",
                        (cama_id, e.inicio, e.fin, e.humedad_antes, e.humedad_despues,
                         e.lectura_antes_id, e.lectura_despues_id, ahora))
        inicios = [e.inicio for e in nuevos]
        sql = ("DELETE FROM eventos_riego WHERE cama_id = %s AND origen = 'detectado' "
               "AND inicio >= %s AND inicio < %s")
        args: list = [cama_id, desde, hasta]
        if inicios:
            sql += f" AND inicio NOT IN ({', '.join(['%s'] * len(inicios))})"
            args += inicios
        cur.execute(sql, args)
    return len(nuevos)


def riegos(conn, cama_id: int, desde: Optional[datetime] = None,
           hasta: Optional[datetime] = None) -> list[EventoRiego]:
    """Riegos (detectados y manuales) cuyo fin cae en [desde, hasta]."""
    condiciones, args = ["cama_id = %s"], [cama_id]
    if desde is not None:
        condiciones.append("COALESCE(fin, inicio) >= %s")
        args.append(desde)
    if hasta is not None:
        condiciones.append("inicio <= %s")
        args.append(hasta)
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM eventos_riego WHERE {' AND '.join(condiciones)} ORDER BY inicio, id",
                    args)
        filas = cur.fetchall()
    return [EventoRiego(f["inicio"], f["fin"], _num(f["humedad_antes"]), _num(f["humedad_despues"]),
                        f["origen"], f["lectura_antes_id"], f["lectura_despues_id"], f["id"])
            for f in filas]


def ultimo_riego(conn, cama_id: int, hasta: Optional[datetime] = None) -> Optional[EventoRiego]:
    args: list = [cama_id]
    extra = ""
    if hasta is not None:
        extra = " AND inicio <= %s"
        args.append(hasta)
    with conn.cursor() as cur:
        cur.execute(f"""SELECT * FROM eventos_riego WHERE cama_id = %s{extra}
                        ORDER BY COALESCE(fin, inicio) DESC, id DESC LIMIT 1""", args)
        f = cur.fetchone()
    if f is None:
        return None
    return EventoRiego(f["inicio"], f["fin"], _num(f["humedad_antes"]), _num(f["humedad_despues"]),
                       f["origen"], f["lectura_antes_id"], f["lectura_despues_id"], f["id"])


def marcas_entre(conn, cama_id: int, desde: datetime, hasta: datetime) -> list[Marca]:
    with conn.cursor() as cur:
        cur.execute("""SELECT lectura_id, medido_en, variable, marca, detalle FROM calidad_lecturas
                        WHERE cama_id = %s AND medido_en >= %s AND medido_en < %s""",
                    (cama_id, desde, hasta))
        return [Marca(f["lectura_id"], f["medido_en"], f["variable"], f["marca"], f["detalle"] or "")
                for f in cur.fetchall()]


def agregados_hora_entre(conn, cama_id: int, variable: str, desde: datetime,
                         hasta: datetime) -> list[tuple[datetime, Optional[float], int]]:
    with conn.cursor() as cur:
        cur.execute("""SELECT hora_inicio, media, n_lecturas FROM agregados_hora
                        WHERE cama_id = %s AND variable = %s AND hora_inicio >= %s AND hora_inicio < %s
                        ORDER BY hora_inicio""", (cama_id, variable, desde, hasta))
        return [(f["hora_inicio"], _num(f["media"]), f["n_lecturas"]) for f in cur.fetchall()]


def horas_con_datos(conn, cama_id: int, variable: str, desde: datetime, hasta: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) AS n FROM agregados_hora
                        WHERE cama_id = %s AND variable = %s AND hora_inicio >= %s
                          AND hora_inicio < %s AND n_lecturas > 0""", (cama_id, variable, desde, hasta))
        return cur.fetchone()["n"]


def agregado_dia(conn, cama_id: int, fecha: date, variable: str) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM agregados_dia WHERE cama_id = %s AND fecha = %s AND variable = %s",
                    (cama_id, fecha, variable))
        return cur.fetchone()


def temperatura_exterior_entre(conn, desde: datetime, hasta: datetime) -> list[float]:
    """Temperaturas del clima de referencia en [desde, hasta), del proveedor con
    más instantáneas en ese período (no se mezclan fuentes)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT fuente, COUNT(*) AS n FROM clima_referencia
                        WHERE observado_en >= %s AND observado_en < %s AND temp_aire_c IS NOT NULL
                        GROUP BY fuente ORDER BY n DESC LIMIT 1""", (desde, hasta))
        fila = cur.fetchone()
        if fila is None:
            return []
        cur.execute("""SELECT temp_aire_c FROM clima_referencia
                        WHERE fuente = %s AND observado_en >= %s AND observado_en < %s
                          AND temp_aire_c IS NOT NULL""", (fila["fuente"], desde, hasta))
        return [float(f["temp_aire_c"]) for f in cur.fetchall()]


def recibidas_desde(conn, desde: datetime) -> list[tuple[int, datetime]]:
    """(cama_id, medido_en) de las lecturas que LLEGARON desde `desde`
    (incluye las atrasadas del buffer de los nodos)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT cama_id, MIN(medido_en) AS desde, MAX(medido_en) AS hasta
                         FROM lecturas WHERE recibido_en >= %s
                        GROUP BY cama_id, DATE(medido_en)""", (desde,))
        filas = cur.fetchall()
    pares = []
    for f in filas:
        pares += [(f["cama_id"], f["desde"]), (f["cama_id"], f["hasta"])]
    return pares


def ultimo_calculo(conn) -> Optional[datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(calculado_en) AS t FROM agregados_hora")
        fila = cur.fetchone()
    return fila["t"] if fila else None


def primera_recepcion(conn) -> Optional[datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(recibido_en) AS t FROM lecturas")
        fila = cur.fetchone()
    return fila["t"] if fila else None
