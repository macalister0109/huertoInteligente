"""Comparación sensor vs. clima de la zona. Funciones puras (sin BD ni red).

delta = lectura_sensor − referencia_externa

* Temperatura del aire: si |delta| < 2 °C → «similar al exterior», porque
  está dentro del error del DHT11 (±2 °C).
* Humedad relativa: si |delta| < 5 puntos → «similar» (error del DHT11).
* Humedad del suelo: SIN delta. El % de la sonda es una escala calibrada de
  0 a 100 entre seco y mojado; el de la zona es contenido volumétrico
  modelado para una celda de varios km. Solo se muestra como referencia.
* ET0: dato informativo para el riego.

Las sugerencias son solo texto: no crean alertas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .base import ClimaReferencia

MARGEN_MAX_MIN = 60
SIMILAR_TEMP_C = 2.0          # error del DHT11
SIMILAR_HUM_PTS = 5.0         # error del DHT11
CALOR_DELTA_C = 5.0           # cama 5 °C o más sobre el exterior…
CALOR_RADIACION_WM2 = 600.0   # …con radiación alta (sol fuerte)


@dataclass(frozen=True)
class Diferencia:
    sensor: float
    externo: float
    delta: float
    similar: bool
    texto: str


def _decimal(x: float, decimales: int = 0) -> str:
    """Número con coma decimal (estilo Chile)."""
    texto = f"{x:.{decimales}f}" if decimales else f"{round(x):d}"
    return texto.replace(".", ",")


def referencia_mas_cercana(medido_en: datetime, candidatas: Iterable[ClimaReferencia],
                           margen_min: float = MARGEN_MAX_MIN) -> Optional[ClimaReferencia]:
    """La instantánea más cercana a `medido_en`, con un máximo de `margen_min`.
    None si ninguna cae dentro del margen (entonces no se muestra delta)."""
    margen = timedelta(minutes=margen_min)
    mejor, mejor_dist = None, None
    for c in candidatas:
        dist = abs(c.observado_en - medido_en)
        if dist <= margen and (mejor_dist is None or dist < mejor_dist):
            mejor, mejor_dist = c, dist
    return mejor


def diferencia_temperatura(sensor: Optional[float], externo: Optional[float]) -> Optional[Diferencia]:
    if sensor is None or externo is None:
        return None
    delta = round(sensor - externo, 1)
    similar = abs(delta) < SIMILAR_TEMP_C
    if similar:
        texto = "similar al exterior"
    elif delta > 0:
        texto = f"+{_decimal(delta)} °C más que afuera"
    else:
        texto = f"{_decimal(abs(delta))} °C menos que afuera"
    return Diferencia(sensor, externo, delta, similar, texto)


def diferencia_humedad_aire(sensor: Optional[float], externo: Optional[float]) -> Optional[Diferencia]:
    if sensor is None or externo is None:
        return None
    delta = round(sensor - externo, 1)
    similar = abs(delta) < SIMILAR_HUM_PTS
    if similar:
        texto = "similar al exterior"
    elif delta > 0:
        texto = f"+{_decimal(delta)} puntos más húmedo que afuera"
    else:
        texto = f"{_decimal(abs(delta))} puntos más seco que afuera"
    return Diferencia(sensor, externo, delta, similar, texto)


def texto_suelo_zona(ref: Optional[ClimaReferencia]) -> Optional[str]:
    """Solo referencia: NO se calcula delta con la sonda (escalas distintas)."""
    if ref is None or ref.hum_suelo_vwc_pct is None:
        return None
    return f"Suelo de la zona (modelo): {_decimal(ref.hum_suelo_vwc_pct)} % vol."


def texto_et0(ref: Optional[ClimaReferencia]) -> Optional[str]:
    if ref is None:
        return None
    if ref.et0_hoy_mm is not None:
        return (f"La zona perdió {_decimal(ref.et0_hoy_mm, 1)} mm de agua hoy por "
                f"evaporación")
    if ref.et0_mm is not None:
        return f"La zona pierde {_decimal(ref.et0_mm, 1)} mm de agua por hora por evaporación"
    return None


def sugerencias(temp: Optional[Diferencia], ref: Optional[ClimaReferencia]) -> list[str]:
    """Textos informativos (no crean alertas)."""
    textos = []
    if (temp is not None and ref is not None and ref.radiacion_wm2 is not None
            and temp.delta >= CALOR_DELTA_C and ref.radiacion_wm2 >= CALOR_RADIACION_WM2):
        textos.append("Posible acumulación de calor: revisa sombra y ventilación.")
    if ref is not None and ref.precipitacion_mm is not None and ref.precipitacion_mm > 0:
        textos.append("Está lloviendo en la zona: revisa la humedad antes de regar.")
    return textos


def comparar(lectura: dict, candidatas: Iterable[ClimaReferencia],
             margen_min: float = MARGEN_MAX_MIN) -> Optional[dict]:
    """Comparación completa de una lectura (dict con medido_en, temp, hum_aire).
    None si no hay referencia de la misma hora."""
    medido_en = lectura.get("medido_en")
    if medido_en is None:
        return None
    ref = referencia_mas_cercana(medido_en, candidatas, margen_min)
    if ref is None:
        return None
    temp = diferencia_temperatura(lectura.get("temp"), ref.temp_aire_c)
    hum = diferencia_humedad_aire(lectura.get("hum_aire"), ref.hum_rel_pct)
    return {
        "referencia_observada_en": ref.observado_en,
        "fuente": ref.fuente,
        "temperatura": None if temp is None else temp.__dict__,
        "humedad_aire": None if hum is None else hum.__dict__,
        "suelo_zona": texto_suelo_zona(ref),
        "suelo_zona_vwc_pct": ref.hum_suelo_vwc_pct,
        "et0": texto_et0(ref),
        "sugerencias": sugerencias(temp, ref),
    }
