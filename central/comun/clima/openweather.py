"""Proveedor OpenWeatherMap (opcional).

Documentación oficial (leída el 2026-11-27): https://openweathermap.org/current

  GET https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units=metric

Funciona con una API key gratuita. Clave SOLO en el .env del servidor:
OPENWEATHER_API_KEY (nunca llega al navegador).

Campos usados (units=metric):
  main.temp (°C), main.humidity (%), rain.1h (mm/h, solo si hubo lluvia),
  dt (unix, UTC), coord.lat / coord.lon.
No entrega radiación solar ni datos de suelo ni ET0: quedan en None.

One Call API 3.0 (https://api.openweathermap.org/data/3.0/onecall) exige una
suscripción aparte («One Call by Call»). Se deja solo como opción comentada:
    # URL_ONE_CALL = "https://api.openweathermap.org/data/3.0/onecall"
    # parametros = {"lat": lat, "lon": lon, "appid": clave, "units": "metric",
    #               "exclude": "minutely,hourly,daily,alerts"}
    # -> current.temp, current.humidity, current.rain["1h"], current.dt, current.uvi
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .base import (TIMEOUT_S, ClimaReferencia, ErrorClima, ObtenerJson, ProveedorClima,
                   ProveedorNoConfigurado, num, obtener_json_http)

URL = "https://api.openweathermap.org/data/2.5/weather"
FUENTE = "openweather"


def normalizar(datos: Mapping[str, Any], lat: float, lon: float) -> ClimaReferencia:
    """Respuesta de Current Weather -> ClimaReferencia. Función pura."""
    if not isinstance(datos, Mapping) or not isinstance(datos.get("main"), Mapping):
        mensaje = datos.get("message") if isinstance(datos, Mapping) else None
        raise ErrorClima(f"respuesta sin datos actuales{': ' + str(mensaje) if mensaje else ''}")
    try:
        observado = datetime.fromtimestamp(int(datos["dt"]), tz=timezone.utc).replace(tzinfo=None)
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as e:
        raise ErrorClima("respuesta sin hora (dt)") from e
    lluvia = datos.get("rain") if isinstance(datos.get("rain"), Mapping) else {}
    return ClimaReferencia(
        temp_aire_c=num(datos["main"].get("temp")),
        hum_rel_pct=num(datos["main"].get("humidity")),
        # rain.1h solo viene si hubo lluvia; si no viene, no se inventa un 0
        precipitacion_mm=num(lluvia.get("1h")),
        radiacion_wm2=None,
        temp_suelo_c=None,
        hum_suelo_vwc_pct=None,
        et0_mm=None,
        observado_en=observado,
        fuente=FUENTE,
        lat=float(lat),
        lon=float(lon),
    )


class ProveedorOpenWeather(ProveedorClima):
    nombre = FUENTE
    titulo = "OpenWeatherMap (requiere API key gratuita)"
    nombre_corto = "OpenWeatherMap"

    def __init__(self, clave: str = "", obtener_json: ObtenerJson = obtener_json_http):
        self.clave = (clave or "").strip()
        self._obtener_json = obtener_json

    def motivo_no_configurado(self) -> Optional[str]:
        return None if self.clave else "falta OPENWEATHER_API_KEY en el .env del servidor"

    def obtener(self, lat: float, lon: float, timeout: float = TIMEOUT_S) -> ClimaReferencia:
        if not self.clave:
            raise ProveedorNoConfigurado(self.motivo_no_configurado())
        try:
            datos = self._obtener_json(URL, {"lat": lat, "lon": lon, "appid": self.clave,
                                             "units": "metric"}, timeout)
        except ErrorClima as e:
            if "HTTP 401" in str(e):
                raise ErrorClima("la API key fue rechazada (HTTP 401)") from e
            raise
        return normalizar(datos, lat, lon)
