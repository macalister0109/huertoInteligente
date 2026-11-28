"""Calibración de la sonda de suelo por cama, calculada en el equipo central.

El nodo envía los mV crudos de la sonda (lecturas.suelo_mv). Si la cama tiene
sus dos puntos de calibración (camas.cal_seco_mv y camas.cal_mojado_mv), el %
de humedad se calcula aquí desde los mV, con la misma fórmula del firmware:

    % = (seco - mV) * 100 / (seco - mojado), acotado a 0–100

(en la YL-69 más agua = menos voltaje). Así el docente puede recalibrar desde
/configuracion sin conectar la placa, y aplicar la calibración nueva a las
lecturas ya guardadas con `recalcular_lecturas`.

Sin calibración en la cama se usa el % que envía el nodo, como antes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NamedTuple, Optional

# Límites del ADC del ESP32 a 3,3 V (igual que la validación del procesador)
MV_MIN, MV_MAX = 0, 3600
# Con menos diferencia que esto entre seco y mojado, la escala no sirve
DIFERENCIA_MINIMA_MV = 100


class Calibracion(NamedTuple):
    seco_mv: int
    mojado_mv: int


def de_cama(cama: Optional[dict]) -> Optional[Calibracion]:
    """La calibración de una fila de camas, o None si le falta algún punto."""
    if not cama:
        return None
    seco, mojado = cama.get("cal_seco_mv"), cama.get("cal_mojado_mv")
    if seco is None or mojado is None or int(seco) <= int(mojado):
        return None
    return Calibracion(int(seco), int(mojado))


def porcentaje(mv: float, cal: Calibracion) -> float:
    """% de humedad (1 decimal, 0–100) para unos mV con esta calibración."""
    pct = (cal.seco_mv - float(mv)) * 100.0 / (cal.seco_mv - cal.mojado_mv)
    pct = min(100.0, max(0.0, pct))
    return float(Decimal(str(pct)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def validar(seco: Any, mojado: Any) -> tuple[Optional[Calibracion], list[str]]:
    """Valida los dos valores de un formulario. Ambos vacíos = sin calibración."""
    errores: list[str] = []
    valores = []
    for texto, nombre in ((seco, "Seco"), (mojado, "Mojado")):
        texto = ("" if texto is None else str(texto)).strip()
        if texto == "":
            valores.append(None)
            continue
        if not texto.isdigit():
            errores.append(f"{nombre}: «{texto}» debe ser un número entero de mV.")
            valores.append(None)
            continue
        valor = int(texto)
        if not MV_MIN <= valor <= MV_MAX:
            errores.append(f"{nombre}: debe estar entre {MV_MIN} y {MV_MAX} mV.")
        valores.append(valor)
    if errores:
        return None, errores
    seco_mv, mojado_mv = valores
    if seco_mv is None and mojado_mv is None:
        return None, []
    if seco_mv is None or mojado_mv is None:
        return None, ["Escribe los dos valores (seco y mojado), o deja ambos vacíos para usar "
                      "el % que calcula la placa."]
    if seco_mv - mojado_mv < DIFERENCIA_MINIMA_MV:
        return None, [f"Seco ({seco_mv} mV) debe ser al menos {DIFERENCIA_MINIMA_MV} mV mayor que "
                      f"mojado ({mojado_mv} mV): en esta sonda, más agua = menos mV."]
    return Calibracion(seco_mv, mojado_mv), []


def guardar(conn, cama_id: int, cal: Optional[Calibracion], ahora: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute("""UPDATE camas SET cal_seco_mv = %s, cal_mojado_mv = %s,
                              cal_actualizada_en = %s WHERE id = %s""",
                    (cal.seco_mv if cal else None, cal.mojado_mv if cal else None, ahora, cama_id))


def recalcular_lecturas(conn, cama_id: int, cal: Calibracion,
                        desde: Optional[datetime] = None) -> int:
    """Aplica la calibración a las lecturas guardadas que tienen mV.

    Solo cambia suelo_prom de las lecturas cuyo suelo NO fue descartado (las
    que tienen suelo_prom). Los mV crudos y el % original del nodo
    (suelo_detalle) no se tocan, así que se puede repetir con otra
    calibración. Devuelve cuántas lecturas cambiaron.
    """
    sql = ["""UPDATE lecturas
                 SET suelo_prom = ROUND(LEAST(100, GREATEST(0,
                         (%s - suelo_mv) * 100.0 / (%s - %s))), 1)
               WHERE cama_id = %s AND suelo_mv IS NOT NULL AND suelo_prom IS NOT NULL
                 AND suelo_mv BETWEEN %s AND %s"""]
    args: list[Any] = [cal.seco_mv, cal.seco_mv, cal.mojado_mv, cama_id, MV_MIN, MV_MAX]
    if desde is not None:
        sql.append("AND medido_en >= %s")
        args.append(desde)
    with conn.cursor() as cur:
        return cur.execute(" ".join(sql), args)


def restaurar_lecturas(conn, cama_id: int) -> int:
    """Al quitar la calibración: suelo_prom vuelve al % que envió el nodo."""
    with conn.cursor() as cur:
        return cur.execute("""UPDATE lecturas
                                 SET suelo_prom = ROUND(JSON_VALUE(suelo_detalle, '$[0]'), 1)
                               WHERE cama_id = %s AND suelo_mv IS NOT NULL AND suelo_prom IS NOT NULL
                                 AND JSON_VALUE(suelo_detalle, '$[0]') BETWEEN 0 AND 100""",
                           (cama_id,))


def primera_lectura(conn, cama_id: int) -> Optional[datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(medido_en) AS t FROM lecturas WHERE cama_id = %s", (cama_id,))
        fila = cur.fetchone()
    return fila["t"] if fila else None


def mv_actual(conn, cama_id: int, lecturas: int = 10, minutos: int = 10) -> Optional[dict]:
    """mV actuales de la cama (para «usar la lectura actual»).

    Promedia las últimas `lecturas` con mV de los `minutos` anteriores a la
    más reciente (unos 5 min a 30 s): una sola lectura de la YL-69 es ruidosa.
    Devuelve {"mv": int, "lecturas": n, "medido_en": hora de la última} o None.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT suelo_mv, medido_en FROM lecturas
                        WHERE cama_id = %s AND valida = 1 AND suelo_mv IS NOT NULL
                        ORDER BY medido_en DESC, id DESC LIMIT %s""", (cama_id, lecturas))
        filas = list(cur.fetchall())
    if not filas:
        return None
    ultima = filas[0]["medido_en"]
    cercanas = [f["suelo_mv"] for f in filas if (ultima - f["medido_en"]).total_seconds() <= minutos * 60]
    return {"mv": int(round(sum(cercanas) / len(cercanas))), "lecturas": len(cercanas),
            "medido_en": ultima}
