"""Tendencias descriptivas de una cama (para el tablero y para las clases).

* Pendiente de la humedad del suelo en las últimas 6 h y 24 h, con etiqueta.
  Usa las lecturas crudas válidas, sin las marcadas rango, salto o pegado.
* Media móvil de 24 h de temperatura y humedad del aire (de agregados_hora).
* Amplitud térmica de la cama (agregados_dia) frente a la exterior
  (clima_referencia), ayer y hoy hasta ahora.

Solo lee: no escribe nada en la BD.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..config import Config
from ..fechas import iso
from . import repositorio as repo
from .agregados import fecha_local, limites_dia_local
from .riego import puntos_suelo
from .tendencia import (ComparacionAmplitud, PendienteVentana, media_movil, pendiente_ventana,
                        serie_media_movil)

VENTANAS_H = (6, 24)
# Para comparar amplitudes, los datos deben repartirse en el día (si no, falta
# el mínimo de la madrugada o el máximo de la tarde): horas con datos de la cama
# y del exterior, sobre 24 (o sobre las horas transcurridas, si es hoy).
HORAS_MIN_CAMA = 18
INSTANTANEAS_MIN_EXTERIOR = 12


def _pendiente_json(p: PendienteVentana) -> dict:
    a = p.ajuste
    return {"horas": p.horas, "etiqueta": p.etiqueta, "texto": p.texto,
            "pendiente_pts_h": None if a is None else round(a.pendiente, 3),
            "r2": None if a is None or a.r2 is None else round(a.r2, 3),
            "n_puntos": 0 if a is None else a.n}


def pendientes_suelo(conn, cfg: Config, cama_id: int, ahora: datetime) -> dict[int, PendienteVentana]:
    desde = ahora - timedelta(hours=max(VENTANAS_H))
    hasta = ahora + timedelta(seconds=1)
    lecturas = repo.lecturas_entre(conn, cama_id, desde, hasta)
    marcas = repo.marcas_entre(conn, cama_id, desde, hasta)
    puntos = [(p.t, p.valor) for p in puntos_suelo(lecturas, marcas)]
    return {h: pendiente_ventana(puntos, ahora, h, rapido=cfg.tendencia_pts_rapido,
                                 estable=cfg.tendencia_pts_estable) for h in VENTANAS_H}


def amplitud(conn, cama_id: int, fecha, zona: ZoneInfo, hasta: datetime) -> Optional[ComparacionAmplitud]:
    fila = repo.agregado_dia(conn, cama_id, fecha, "temp")
    if fila is None or fila["minimo"] is None:
        return None
    inicio, fin = limites_dia_local(fecha, zona)
    horas_transcurridas = (min(fin, hasta) - inicio).total_seconds() / 3600
    horas_cama = repo.horas_con_datos(conn, cama_id, "temp", inicio, min(fin, hasta))
    if horas_cama < min(HORAS_MIN_CAMA, horas_transcurridas * 0.75):
        return None
    exterior = repo.temperatura_exterior_entre(conn, inicio, min(fin, hasta))
    suficientes = len(exterior) >= min(INSTANTANEAS_MIN_EXTERIOR, horas_transcurridas / 2)
    return ComparacionAmplitud(float(fila["minimo"]), float(fila["maximo"]),
                               min(exterior) if exterior and suficientes else None,
                               max(exterior) if exterior and suficientes else None)


def _amplitud_json(c: Optional[ComparacionAmplitud], fecha, cuando: str) -> Optional[dict]:
    if c is None:
        return None
    return {"fecha": fecha.isoformat(), "cama_c": c.cama, "exterior_c": c.exterior,
            "diferencia_c": c.diferencia, "texto": c.texto(cuando),
            "cama_min": c.cama_min, "cama_max": c.cama_max,
            "exterior_min": c.exterior_min, "exterior_max": c.exterior_max}


def resumen(conn, cfg: Config, cama_id: int, ahora: datetime) -> dict:
    zona = ZoneInfo(cfg.zona_horaria)
    pendientes = pendientes_suelo(conn, cfg, cama_id, ahora)

    moviles = {}
    for variable in ("temp", "hum_aire"):
        horas = repo.agregados_hora_entre(conn, cama_id, variable, ahora - timedelta(hours=25), ahora)
        moviles[variable] = media_movil(horas, ahora, 24)

    hoy = fecha_local(ahora, zona)
    ayer = hoy - timedelta(days=1)
    resultado = {
        "calculado_en": iso(ahora),
        "suelo": {f"{h}h": _pendiente_json(p) for h, p in pendientes.items()},
        "etiqueta": pendientes[6].etiqueta,               # la de la tarjeta (últimas 6 h)
        "media_movil_24h": {"temp": moviles["temp"], "hum_aire": moviles["hum_aire"]},
        "amplitud": {
            "ayer": _amplitud_json(amplitud(conn, cama_id, ayer, zona, ahora), ayer, "ayer"),
            "hoy": _amplitud_json(amplitud(conn, cama_id, hoy, zona, ahora), hoy, "hoy"),
        },
    }
    conn.commit()
    return resultado


def serie_medias_moviles(conn, cama_id: int, desde: datetime, hasta: datetime) -> dict:
    """Media móvil de 24 h, una por hora, para graficar."""
    serie = {}
    for variable in ("temp", "hum_aire"):
        horas = repo.agregados_hora_entre(conn, cama_id, variable, desde - timedelta(hours=24), hasta)
        serie[variable] = [{"t": iso(t), "valor": v}
                           for t, v in serie_media_movil(horas, desde, hasta)]
    conn.commit()
    return serie
