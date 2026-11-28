"""Consultas de la web. Todas parametrizadas."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterator, Optional, Sequence

import pymysql.cursors

from comun.rangos import SELECT_CAMA

_SELECT_CAMA = SELECT_CAMA      # cama + cultivo + zona (comun/rangos.py)

_SELECT_ALERTA = """
    SELECT a.id, a.cama_id, c.nombre AS cama, c.nodo_id, a.tipo, a.variable, a.estado, a.mensaje,
           a.valor_actual, a.iniciada_en, a.actualizada_en, a.resuelta_en
      FROM alertas a JOIN camas c ON c.id = a.cama_id
"""


def _filas(conn, sql: str, args: Sequence[Any] = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def _fila(conn, sql: str, args: Sequence[Any] = ()) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Camas y cultivos
# ---------------------------------------------------------------------------

def camas(conn, solo_activas: bool = True) -> list[dict]:
    where = " WHERE c.activa = 1" if solo_activas else ""
    return _filas(conn, _SELECT_CAMA + where + " ORDER BY c.nombre")


def cama(conn, cama_id: int) -> Optional[dict]:
    return _fila(conn, _SELECT_CAMA + " WHERE c.id = %s", (cama_id,))


def cultivos(conn) -> list[dict]:
    return _filas(conn, "SELECT * FROM cultivos ORDER BY nombre")


def cultivo(conn, cultivo_id: int) -> Optional[dict]:
    return _fila(conn, "SELECT * FROM cultivos WHERE id = %s", (cultivo_id,))


def camas_con_cultivo(conn, cultivo_id: int) -> list[int]:
    return [f["id"] for f in _filas(conn, "SELECT id FROM camas WHERE cultivo_id = %s", (cultivo_id,))]


CAMPOS_CAMA = ("nombre", "cultivo_id", "zona_climatica", "zona_id", "humedad_min", "humedad_max",
               "temp_min", "temp_max", "horas_luz_min", "activa")
CAMPOS_CULTIVO = ("nombre", "humedad_min", "humedad_max", "temp_min", "temp_max",
                  "horas_luz_min", "tolera_sombra", "por_confirmar", "notas")


def actualizar_cama(conn, cama_id: int, valores: dict) -> None:
    columnas = [c for c in CAMPOS_CAMA if c in valores]        # nombres de una lista fija
    asignaciones = ", ".join(f"{c} = %s" for c in columnas)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE camas SET {asignaciones} WHERE id = %s",
                    [valores[c] for c in columnas] + [cama_id])
    conn.commit()


# ---------------------------------------------------------------------------
# Zonas climáticas
# ---------------------------------------------------------------------------

CAMPOS_RANGO_ZONA = ("humedad_min", "humedad_max", "temp_min", "temp_max", "horas_luz_min")


def zonas(conn) -> list[dict]:
    return _filas(conn, "SELECT * FROM zonas_climaticas ORDER BY id")


def rangos_por_zona(conn) -> dict[tuple[int, int], dict]:
    """(cultivo_id, zona_id) -> fila de rangos_cultivo_zona."""
    return {(f["cultivo_id"], f["zona_id"]): f for f in _filas(conn, "SELECT * FROM rangos_cultivo_zona")}


def guardar_rangos_zona(conn, cultivo_id: int, zona_id: int, valores: dict, por_confirmar: bool) -> None:
    """Sin ningún valor se borra la fila: el cultivo usa su rango genérico en esa zona."""
    with conn.cursor() as cur:
        if all(valores.get(c) is None for c in CAMPOS_RANGO_ZONA):
            cur.execute("DELETE FROM rangos_cultivo_zona WHERE cultivo_id = %s AND zona_id = %s",
                        (cultivo_id, zona_id))
            return
        cur.execute(f"""INSERT INTO rangos_cultivo_zona
                            (cultivo_id, zona_id, {', '.join(CAMPOS_RANGO_ZONA)}, por_confirmar)
                        VALUES (%s, %s, {', '.join(['%s'] * len(CAMPOS_RANGO_ZONA))}, %s)
                        ON DUPLICATE KEY UPDATE {', '.join(f'{c} = VALUES({c})' for c in CAMPOS_RANGO_ZONA)},
                            por_confirmar = VALUES(por_confirmar)""",
                    (cultivo_id, zona_id, *[valores.get(c) for c in CAMPOS_RANGO_ZONA], int(por_confirmar)))


def camas_ids(conn) -> list[int]:
    return [f["id"] for f in _filas(conn, "SELECT id FROM camas")]


def guardar_cultivo(conn, cultivo_id: Optional[int], valores: dict) -> int:
    columnas = [c for c in CAMPOS_CULTIVO if c in valores]
    with conn.cursor() as cur:
        if cultivo_id is None:
            cur.execute(f"INSERT INTO cultivos ({', '.join(columnas)}) "
                        f"VALUES ({', '.join(['%s'] * len(columnas))})",
                        [valores[c] for c in columnas])
            cultivo_id = cur.lastrowid
        else:
            asignaciones = ", ".join(f"{c} = %s" for c in columnas)
            cur.execute(f"UPDATE cultivos SET {asignaciones} WHERE id = %s",
                        [valores[c] for c in columnas] + [cultivo_id])
    conn.commit()
    return cultivo_id


# ---------------------------------------------------------------------------
# Estado y lecturas
# ---------------------------------------------------------------------------

def ultimos_estados(conn) -> dict[int, dict]:
    filas = _filas(conn, """
        SELECT ce.cama_id, ce.estado_nuevo, ce.mensaje, ce.ocurrido_en
          FROM cambios_estado ce
          JOIN (SELECT cama_id, MAX(id) AS id FROM cambios_estado GROUP BY cama_id) u ON u.id = ce.id""")
    return {f["cama_id"]: f for f in filas}


def lectura_actual(conn, cama_id: int) -> Optional[dict]:
    fila = _fila(conn, """
        SELECT seq, medido_en, recibido_en, suelo_prom, suelo_detalle, suelo_mv,
               temp, hum_aire, lux
          FROM lecturas WHERE cama_id = %s AND valida = 1
         ORDER BY medido_en DESC, id DESC LIMIT 1""", (cama_id,))
    if fila and isinstance(fila["suelo_detalle"], (str, bytes)):
        fila["suelo_detalle"] = json.loads(fila["suelo_detalle"])
    return fila


def serie(conn, cama_id: int, desde: datetime, hasta: datetime, segundos_balde: int) -> list[dict]:
    """Promedios por intervalo (para que el gráfico de 24 h no tenga miles de puntos)."""
    return _filas(conn, """
        SELECT FLOOR(UNIX_TIMESTAMP(medido_en) / %s) * %s AS t,
               AVG(suelo_prom) AS suelo, AVG(temp) AS temp,
               AVG(hum_aire) AS hum_aire, AVG(lux) AS lux
          FROM lecturas
         WHERE cama_id = %s AND valida = 1 AND medido_en >= %s AND medido_en < %s
         GROUP BY 1 ORDER BY 1""",
        (segundos_balde, segundos_balde, cama_id, desde, hasta))


def resumen_por_hora(conn, cama_id: int, desde: datetime, hasta: datetime) -> list[dict]:
    """Suma, cuenta, mínimo y máximo por hora (UTC) de las lecturas válidas.
    La web junta las horas en días de Chile (ver rutas_historial.resumen_diario)."""
    return _filas(conn, """
        SELECT FLOOR(UNIX_TIMESTAMP(medido_en) / 3600) * 3600 AS hora,
               COUNT(*) AS lecturas,
               SUM(suelo_prom) AS suelo_suma, COUNT(suelo_prom) AS suelo_n,
               MIN(suelo_prom) AS suelo_min, MAX(suelo_prom) AS suelo_max,
               SUM(temp) AS temp_suma, COUNT(temp) AS temp_n,
               MIN(temp) AS temp_min, MAX(temp) AS temp_max,
               SUM(hum_aire) AS hum_aire_suma, COUNT(hum_aire) AS hum_aire_n,
               MIN(hum_aire) AS hum_aire_min, MAX(hum_aire) AS hum_aire_max
          FROM lecturas
         WHERE cama_id = %s AND valida = 1 AND medido_en >= %s AND medido_en < %s
         GROUP BY 1 ORDER BY 1""", (cama_id, desde, hasta))


def lecturas_para_csv(conn, cama_id: int, desde: datetime, hasta: datetime) -> Iterator[dict]:
    """Todas las lecturas (válidas o no) en orden de medición.

    `conn` debe ser una conexión PROPIA (no la de la petición): se sigue usando
    mientras se envía el archivo, después de que la petición terminó.
    Usa un cursor sin buffer: las filas se leen de a poco mientras se envía
    el archivo, así un año de lecturas no llena la memoria del servidor.
    """
    with conn.cursor(pymysql.cursors.SSDictCursor) as cur:
        cur.execute("""
            SELECT medido_en, seq, suelo_prom, suelo_mv, temp, hum_aire, lux, valida, motivo_invalida
              FROM lecturas
             WHERE cama_id = %s AND medido_en >= %s AND medido_en < %s
             ORDER BY medido_en, id""", (cama_id, desde, hasta))
        yield from cur


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

def alertas_abiertas(conn) -> list[dict]:
    return _filas(conn, _SELECT_ALERTA + """
        WHERE a.estado = 'abierta' AND c.activa = 1 ORDER BY a.iniciada_en DESC""")


def alertas_resueltas_desde(conn, desde: datetime) -> list[dict]:
    return _filas(conn, _SELECT_ALERTA + """
        WHERE a.estado = 'resuelta' AND a.resuelta_en >= %s AND c.activa = 1
        ORDER BY a.resuelta_en DESC""", (desde,))


def alertas_de_cama(conn, cama_id: int, desde: datetime) -> list[dict]:
    return _filas(conn, _SELECT_ALERTA + """
        WHERE a.cama_id = %s AND (a.estado = 'abierta' OR a.resuelta_en >= %s)
        ORDER BY a.iniciada_en DESC""", (cama_id, desde))


def marcar_alertas_visibles(conn, ids: Sequence[int], visible_en: datetime) -> int:
    """CQ-02: primera vez que el aviso se vio en la pantalla del huerto."""
    if not ids:
        return 0
    marcadores = ", ".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        n = cur.execute(f"""UPDATE eventos_alerta SET visible_en = %s
                             WHERE evento = 'apertura' AND visible_en IS NULL
                               AND alerta_id IN ({marcadores})""", [visible_en, *ids])
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# Latencias e incidencias
# ---------------------------------------------------------------------------

def cama_por_nodo(conn, nodo_id: str) -> Optional[dict]:
    return _fila(conn, "SELECT id FROM camas WHERE nodo_id = %s", (nodo_id,))


def registrar_latencia(conn, cama_id: int, seq: int, medido_en: datetime,
                       mostrado_en: datetime) -> int:
    latencia_ms = int((mostrado_en - medido_en).total_seconds() * 1000)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO latencias_pantalla (cama_id, seq, medido_en, mostrado_en, latencia_ms)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (cama_id, seq, medido_en, mostrado_en, latencia_ms))
    conn.commit()
    return latencia_ms


def incidencias_pendientes(conn) -> list[dict]:
    return _filas(conn, """SELECT * FROM incidencias WHERE revisada = 0
                            ORDER BY ocurrido_en DESC LIMIT 50""")


def marcar_incidencia_revisada(conn, incidencia_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE incidencias SET revisada = 1 WHERE id = %s", (incidencia_id,))
    conn.commit()
