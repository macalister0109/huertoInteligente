"""Proveedor Open-Meteo (por defecto, sin API key).

API:  https://api.open-meteo.com/v1/forecast   (no https://open-meteo.com, que es el sitio web)
Variables verificadas en https://open-meteo.com/en/docs y con una respuesta real (2026-11-27):

  current: temperature_2m (°C), relative_humidity_2m (%), precipitation (mm),
           shortwave_radiation (W/m²). current.time es hora LOCAL sin offset,
           en pasos de 15 min (current.interval = 900 s).
  hourly:  soil_temperature_0cm (°C), soil_moisture_0_to_1cm (m³/m³),
           et0_fao_evapotranspiration (mm, suma de la hora anterior).
           hourly.time es hora LOCAL sin offset, cada 1 h.
  utc_offset_seconds: offset fijo de toda la respuesta (Chile en verano: -10800).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from .base import (TIMEOUT_S, ClimaReferencia, ErrorClima, ObtenerJson, ProveedorClima, num,
                   obtener_json_http)

URL = "https://api.open-meteo.com/v1/forecast"
FUENTE = "open-meteo"
VARIABLES_ACTUALES = "temperature_2m,relative_humidity_2m,precipitation,shortwave_radiation"
VARIABLES_HORARIAS = "soil_temperature_0cm,soil_moisture_0_to_1cm,et0_fao_evapotranspiration"


def parametros(lat: float, lon: float, zona_horaria: str = "America/Santiago") -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "current": VARIABLES_ACTUALES,
        "hourly": VARIABLES_HORARIAS,
        "timezone": zona_horaria,
        "past_days": 0,
        "forecast_days": 1,       # solo se usa la hora actual: no es un pronóstico
    }


def _local(texto: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(texto))
    except ValueError as e:
        raise ErrorClima(f"hora no válida en la respuesta: {texto!r}") from e


def indice_hora(horas: list, hora_actual_local: datetime) -> Optional[int]:
    """Índice del arreglo horario que corresponde a la hora de `current.time`
    (la hora en punto anterior o igual). NO el primero del arreglo."""
    objetivo = hora_actual_local.replace(minute=0, second=0, microsecond=0)
    for i, texto in enumerate(horas):
        if _local(texto) == objetivo:
            return i
    return None


def _valor(serie: Mapping[str, list], variable: str, i: Optional[int]) -> Optional[float]:
    valores = serie.get(variable)
    if i is None or not isinstance(valores, list) or i >= len(valores):
        return None
    return num(valores[i])


def normalizar(datos: Mapping[str, Any], lat: float, lon: float) -> ClimaReferencia:
    """Respuesta JSON de Open-Meteo -> ClimaReferencia. Función pura."""
    if not isinstance(datos, Mapping) or not isinstance(datos.get("current"), Mapping):
        razon = datos.get("reason") if isinstance(datos, Mapping) else None
        raise ErrorClima(f"respuesta sin datos actuales{': ' + str(razon) if razon else ''}")
    actual = datos["current"]
    offset = timedelta(seconds=int(datos.get("utc_offset_seconds") or 0))
    hora_local = _local(actual.get("time"))

    horario = datos.get("hourly") if isinstance(datos.get("hourly"), Mapping) else {}
    horas = horario.get("time") if isinstance(horario.get("time"), list) else []
    i = indice_hora(horas, hora_local)

    vwc = _valor(horario, "soil_moisture_0_to_1cm", i)
    # ET0 acumulada hoy: suma de las horas del mismo día local hasta la actual
    et0_hoy = None
    et0 = horario.get("et0_fao_evapotranspiration")
    if i is not None and isinstance(et0, list):
        dia = hora_local.date()
        valores = [num(et0[j]) for j in range(min(i + 1, len(et0)))
                   if _local(horas[j]).date() == dia]
        valores = [v for v in valores if v is not None]
        et0_hoy = round(sum(valores), 2) if valores else None

    return ClimaReferencia(
        temp_aire_c=num(actual.get("temperature_2m")),
        hum_rel_pct=num(actual.get("relative_humidity_2m")),
        precipitacion_mm=num(actual.get("precipitation")),
        radiacion_wm2=num(actual.get("shortwave_radiation")),
        temp_suelo_c=_valor(horario, "soil_temperature_0cm", i),
        # m³/m³ -> % volumétrico
        hum_suelo_vwc_pct=None if vwc is None else round(vwc * 100, 1),
        et0_mm=_valor(horario, "et0_fao_evapotranspiration", i),
        observado_en=hora_local - offset,          # local -> UTC
        fuente=FUENTE,
        lat=float(lat),
        lon=float(lon),
        et0_hoy_mm=et0_hoy,
    )


class ProveedorOpenMeteo(ProveedorClima):
    nombre = FUENTE
    titulo = "Open-Meteo (gratis, sin clave)"
    nombre_corto = "Open-Meteo"

    def __init__(self, zona_horaria: str = "America/Santiago",
                 obtener_json: ObtenerJson = obtener_json_http):
        self.zona_horaria = zona_horaria
        self._obtener_json = obtener_json

    def obtener(self, lat: float, lon: float, timeout: float = TIMEOUT_S) -> ClimaReferencia:
        datos = self._obtener_json(URL, parametros(lat, lon, self.zona_horaria), timeout)
        return normalizar(datos, lat, lon)
