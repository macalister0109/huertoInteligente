"""Acceso a la BD del procesador. Todas las consultas son parametrizadas.

Las funciones NO hacen commit: el servicio decide cuándo cerrar cada
transacción (una por mensaje procesado).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .validacion import LecturaValidada

# Columnas de la cama + las de su cultivo con prefijo, para rango_efectivo()
_SELECT_CAMA = """
    SELECT c.*, cu.nombre AS cultivo_nombre,
           cu.humedad_min AS cultivo_humedad_min, cu.humedad_max AS cultivo_humedad_max,
           cu.temp_min AS cultivo_temp_min, cu.temp_max AS cultivo_temp_max,
           cu.horas_luz_min AS cultivo_horas_luz_min
      FROM camas c
      LEFT JOIN cultivos cu ON cu.id = c.cultivo_id
"""

# Una lectura válida "de un sensor" es una fila válida con esa columna no nula
COLUMNA_SENSOR = {"suelo": "suelo_prom", "temperatura": "temp", "luz": "lux"}


def _json(valor: Any) -> Any:
    if valor is None or not isinstance(valor, (str, bytes)):
        return valor
    return json.loads(valor)


def nombre_por_defecto(nodo_id: str) -> str:
    """'cama-a' -> 'Cama A', 'cama-1' -> 'Cama 1', 'huerto-norte' -> 'Huerto norte'."""
    partes = [p for p in nodo_id.replace("_", "-").split("-") if p]
    if not partes:
        return nodo_id
    partes = [p.upper() if len(p) == 1 else p for p in partes]
    texto = " ".join(partes)
    return texto[:1].upper() + texto[1:]


# ---------------------------------------------------------------------------
# Camas
# ---------------------------------------------------------------------------

def obtener_o_crear_cama(conn, nodo_id: str) -> dict:
    """Un nodo desconocido crea su cama sin cultivo (queda «sin configurar»)."""
    cama = obtener_cama_por_nodo(conn, nodo_id)
    if cama is not None:
        return cama
    with conn.cursor() as cur:
        cur.execute("INSERT IGNORE INTO camas (nombre, nodo_id) VALUES (%s, %s)",
                    (nombre_por_defecto(nodo_id), nodo_id))
    return obtener_cama_por_nodo(conn, nodo_id)


def obtener_cama_por_nodo(conn, nodo_id: str) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_CAMA + " WHERE c.nodo_id = %s", (nodo_id,))
        return cur.fetchone()


def obtener_cama(conn, cama_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_CAMA + " WHERE c.id = %s", (cama_id,))
        return cur.fetchone()


def camas_activas(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_CAMA + " WHERE c.activa = 1 ORDER BY c.nombre")
        return list(cur.fetchall())


def cultivos_de_sombra(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT nombre FROM cultivos WHERE tolera_sombra = 1 ORDER BY nombre")
        return [f["nombre"] for f in cur.fetchall()]


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------

def insertar_lectura(conn, cama_id: int, lv: LecturaValidada, recibido_en: datetime) -> int:
    """Lanza pymysql.err.IntegrityError si (cama_id, seq) ya existe."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO lecturas
                   (cama_id, seq, medido_en, recibido_en, suelo_prom, suelo_detalle,
                    temp, hum_aire, lux, valida, campos_invalidos, motivo_invalida)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (cama_id, lv.seq, lv.medido_en, recibido_en, lv.suelo_prom,
             None if lv.suelo_detalle is None else json.dumps(lv.suelo_detalle),
             lv.temp, lv.hum_aire, lv.lux, int(lv.valida),
             json.dumps(lv.invalidos) if lv.invalidos else None, lv.motivo),
        )
        return cur.lastrowid


def lectura_por_seq(conn, cama_id: int, seq: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, medido_en FROM lecturas WHERE cama_id = %s AND seq = %s",
                    (cama_id, seq))
        return cur.fetchone()


def lectura_anterior(conn, cama_id: int, medido_en: datetime) -> Optional[dict]:
    """Lectura inmediatamente anterior EN EL TIEMPO (válida o no), para
    detectar saltos. Solo mira los últimos 30 minutos."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT medido_en, suelo_prom, temp, hum_aire, campos_invalidos
                 FROM lecturas
                WHERE cama_id = %s AND medido_en < %s AND medido_en >= %s
                ORDER BY medido_en DESC, id DESC LIMIT 1""",
            (cama_id, medido_en, medido_en - timedelta(minutes=30)),
        )
        return cur.fetchone()


def existe_valida_posterior(conn, cama_id: int, medido_en: datetime, excluir_id: int) -> bool:
    """¿Hay otra lectura válida medida DESPUÉS? Entonces esta es atrasada (HU-01)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM lecturas
                WHERE cama_id = %s AND valida = 1 AND medido_en > %s AND id <> %s
                LIMIT 1""",
            (cama_id, medido_en, excluir_id),
        )
        return cur.fetchone() is not None


def lectura_actual(conn, cama_id: int) -> Optional[dict]:
    """HU-01: la lectura válida de mayor medido_en (no la última en llegar)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, seq, medido_en, recibido_en, suelo_prom, suelo_detalle,
                      temp, hum_aire, lux, campos_invalidos
                 FROM lecturas
                WHERE cama_id = %s AND valida = 1
                ORDER BY medido_en DESC, id DESC LIMIT 1""",
            (cama_id,),
        )
        fila = cur.fetchone()
    if fila:
        fila["suelo_detalle"] = _json(fila["suelo_detalle"])
        fila["campos_invalidos"] = _json(fila["campos_invalidos"])
    return fila


def temperaturas_desc(conn, cama_id: int, desde: datetime, hasta: datetime) -> list[tuple[datetime, float]]:
    """Temperaturas válidas entre `desde` y `hasta`, de la más nueva a la más antigua."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT medido_en, temp FROM lecturas
                WHERE cama_id = %s AND valida = 1 AND temp IS NOT NULL
                  AND medido_en BETWEEN %s AND %s
                ORDER BY medido_en DESC""",
            (cama_id, desde, hasta),
        )
        return [(f["medido_en"], float(f["temp"])) for f in cur.fetchall()]


def lux_asc(conn, cama_id: int, desde: datetime, hasta: datetime) -> list[tuple[datetime, float]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT medido_en, lux FROM lecturas
                WHERE cama_id = %s AND valida = 1 AND lux IS NOT NULL
                  AND medido_en >= %s AND medido_en < %s
                ORDER BY medido_en""",
            (cama_id, desde, hasta),
        )
        return [(f["medido_en"], float(f["lux"])) for f in cur.fetchall()]


def ultima_valida_por_sensor(conn, cama_id: int, desde: datetime) -> dict[str, Optional[datetime]]:
    """Hora de la última lectura válida de cada sensor desde `desde`.
    Una consulta por sensor: usa el índice (cama_id, medido_en) hacia atrás."""
    resultado: dict[str, Optional[datetime]] = {}
    with conn.cursor() as cur:
        for sensor, columna in COLUMNA_SENSOR.items():
            # `columna` viene de un diccionario fijo, nunca del usuario
            cur.execute(
                f"""SELECT medido_en FROM lecturas
                     WHERE cama_id = %s AND valida = 1 AND {columna} IS NOT NULL
                       AND medido_en >= %s
                     ORDER BY medido_en DESC LIMIT 1""",
                (cama_id, desde),
            )
            fila = cur.fetchone()
            resultado[sensor] = fila["medido_en"] if fila else None
    return resultado


def primera_lectura(conn, cama_id: int) -> Optional[datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(medido_en) AS t FROM lecturas WHERE cama_id = %s", (cama_id,))
        fila = cur.fetchone()
        return fila["t"] if fila else None


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

def alertas_abiertas(conn, cama_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, tipo, variable, mensaje, valor_inicial, valor_actual,
                      iniciada_en, actualizada_en
                 FROM alertas WHERE cama_id = %s AND estado = 'abierta'
                ORDER BY iniciada_en""",
            (cama_id,),
        )
        return list(cur.fetchall())


def abrir_alerta(conn, cama_id: int, tipo: str, variable: str, mensaje: str,
                 valor: Optional[float], iniciada_en: datetime, actualizada_en: datetime) -> int:
    """Lanza IntegrityError si ya hay una abierta del mismo tipo (lo evita la BD)."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO alertas
                   (cama_id, tipo, variable, mensaje, valor_inicial, valor_actual,
                    iniciada_en, actualizada_en)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (cama_id, tipo, variable, mensaje, valor, valor, iniciada_en, actualizada_en),
        )
        return cur.lastrowid


def actualizar_alerta(conn, alerta_id: int, valor: Optional[float], mensaje: Optional[str],
                      actualizada_en: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE alertas
                  SET valor_actual = %s, mensaje = COALESCE(%s, mensaje), actualizada_en = %s
                WHERE id = %s AND estado = 'abierta'""",
            (valor, mensaje, actualizada_en, alerta_id),
        )


def resolver_alerta(conn, alerta_id: int, valor: Optional[float], resuelta_en: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE alertas
                  SET estado = 'resuelta', resuelta_en = %s, actualizada_en = %s,
                      valor_actual = COALESCE(%s, valor_actual)
                WHERE id = %s AND estado = 'abierta'""",
            (resuelta_en, resuelta_en, valor, alerta_id),
        )


def registrar_evento_alerta(conn, alerta_id: int, evento: str, lectura_medida_en: datetime,
                            procesado_en: datetime) -> None:
    """CQ-02: el tablero completa visible_en cuando el aviso se ve en pantalla."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT IGNORE INTO eventos_alerta (alerta_id, evento, lectura_medida_en, procesado_en)
               VALUES (%s, %s, %s, %s)""",
            (alerta_id, evento, lectura_medida_en, procesado_en),
        )


# ---------------------------------------------------------------------------
# Luz diaria
# ---------------------------------------------------------------------------

def guardar_luz_diaria(conn, cama_id: int, fecha: date, horas: Optional[float],
                       minutos: float, minutos_sol: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO luz_diaria (cama_id, fecha, horas_luz, minutos_con_datos, minutos_con_datos_sol)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE horas_luz = VALUES(horas_luz),
                   minutos_con_datos = VALUES(minutos_con_datos),
                   minutos_con_datos_sol = VALUES(minutos_con_datos_sol)""",
            (cama_id, fecha, horas, round(minutos), round(minutos_sol)),
        )


def ultima_fecha_luz(conn, cama_id: int) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(fecha) AS f FROM luz_diaria WHERE cama_id = %s", (cama_id,))
        fila = cur.fetchone()
        return fila["f"] if fila else None


def dias_luz_desc(conn, cama_id: int, limite: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fecha, horas_luz, minutos_con_datos_sol FROM luz_diaria
                WHERE cama_id = %s ORDER BY fecha DESC LIMIT %s""",
            (cama_id, limite),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Estados, nodos e incidencias
# ---------------------------------------------------------------------------

def ultimos_estados(conn) -> dict[int, dict]:
    """Último estado registrado de cada cama (para no repetir avisos al reiniciar)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT ce.cama_id, ce.estado_nuevo, ce.mensaje, ce.ocurrido_en
                 FROM cambios_estado ce
                 JOIN (SELECT cama_id, MAX(id) AS id FROM cambios_estado GROUP BY cama_id) u
                   ON u.id = ce.id"""
        )
        return {f["cama_id"]: f for f in cur.fetchall()}


def registrar_cambio_estado(conn, cama_id: int, anterior: Optional[str], nuevo: str,
                            mensaje: str, ocurrido_en: datetime,
                            ultima_valida_en: Optional[datetime]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO cambios_estado
                   (cama_id, estado_anterior, estado_nuevo, mensaje, ocurrido_en, ultima_valida_en)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (cama_id, anterior, nuevo, mensaje, ocurrido_en, ultima_valida_en),
        )


def registrar_heartbeat(conn, nodo_id: str, recibido_en: datetime, datos: dict) -> None:
    def entero(clave: str) -> Optional[int]:
        v = datos.get(clave)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    motivo = datos.get("motivo_reinicio")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO heartbeats
                   (nodo_id, recibido_en, uptime_s, rssi, motivo_reinicio, buffer_pendiente, heap_libre)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (nodo_id, recibido_en, entero("uptime_s"), entero("rssi"),
             str(motivo)[:30] if motivo is not None else None,
             entero("buffer_pendiente"), entero("heap_libre")),
        )


def registrar_conexion(conn, nodo_id: str, estado: str, ocurrido_en: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conexiones_nodo (nodo_id, estado, ocurrido_en) VALUES (%s, %s, %s)",
            (nodo_id, estado, ocurrido_en),
        )


def registrar_incidencia(conn, nodo_id: str, tipo: str, detalle: str, ocurrido_en: datetime,
                         no_repetir_minutos: float = 60) -> bool:
    """Registra una incidencia, salvo que ya haya una igual sin revisar reciente
    (para no llenar la lista del docente con el mismo problema)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM incidencias
                WHERE nodo_id = %s AND tipo = %s AND revisada = 0 AND ocurrido_en >= %s
                LIMIT 1""",
            (nodo_id, tipo, ocurrido_en - timedelta(minutes=no_repetir_minutos)),
        )
        if cur.fetchone():
            return False
        cur.execute(
            """INSERT INTO incidencias (nodo_id, tipo, detalle, ocurrido_en)
               VALUES (%s, %s, %s, %s)""",
            (nodo_id, tipo, detalle[:500], ocurrido_en),
        )
        return True
