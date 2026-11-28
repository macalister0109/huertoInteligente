"""Clima externo de REFERENCIA: interfaz común de los proveedores.

Es una capa de referencia de las condiciones actuales de la zona, NO un
pronóstico (el pronóstico está fuera de alcance, sección 3.2 de la
documentación). El huerto funciona igual sin ella: si no hay internet, solo
falta el bloque de clima.

Patrón adaptador: cada proveedor (Open-Meteo, DMC, OpenWeatherMap) traduce
su respuesta a un `ClimaReferencia` normalizado. Cualquier campo puede ser
None si el proveedor no lo entrega.

Convención del proyecto: datetime ingenuos en UTC.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

TIMEOUT_S = 5.0

# Firma de la función que hace la petición HTTP: (url, parámetros, timeout) -> JSON.
# Los tests la reemplazan para no llamar a internet.
ObtenerJson = Callable[[str, Mapping[str, Any], float], Any]


class ErrorClima(Exception):
    """La API no respondió, tardó demasiado o respondió algo inesperado."""


class ProveedorNoConfigurado(ErrorClima):
    """Faltan credenciales o datos (ej. la API key): no es una falla."""


@dataclass(frozen=True)
class ClimaReferencia:
    temp_aire_c: Optional[float]
    hum_rel_pct: Optional[float]
    precipitacion_mm: Optional[float]
    radiacion_wm2: Optional[float]
    temp_suelo_c: Optional[float]
    hum_suelo_vwc_pct: Optional[float]   # contenido volumétrico de agua (% vol.), modelado
    et0_mm: Optional[float]              # ET0 de la hora (mm)
    observado_en: datetime               # UTC
    fuente: str
    lat: float
    lon: float
    # Extra: ET0 acumulada hoy (hora local) hasta la hora observada.
    # Sirve para «La zona perdió X mm de agua hoy por evaporación».
    et0_hoy_mm: Optional[float] = None

    def como_dict(self) -> dict:
        return asdict(self)


class ProveedorClima(ABC):
    """Interfaz común. `nombre` es el código que se guarda en la configuración."""

    nombre: str = ""
    titulo: str = ""            # nombre visible en /configuracion
    nombre_corto: str = ""      # nombre visible en el tablero, ej. «Open-Meteo»
    usa_coordenadas: bool = True   # False = usa una estación fija (DMC)

    def aplicar_ajustes(self, ajustes: Mapping[str, Any]) -> None:
        """Recibe la configuración del huerto (ej. la estación de la DMC)."""

    def configurado(self) -> bool:
        return self.motivo_no_configurado() is None

    def motivo_no_configurado(self) -> Optional[str]:
        """None si está listo para usarse; si no, un texto simple del motivo."""
        return None

    @abstractmethod
    def obtener(self, lat: float, lon: float, timeout: float = TIMEOUT_S) -> ClimaReferencia:
        """Devuelve el clima actual. Lanza ErrorClima ante cualquier falla."""


def obtener_json_http(url: str, parametros: Mapping[str, Any], timeout: float) -> Any:
    """GET con timeout. Cualquier error se convierte en ErrorClima."""
    consulta = urllib.parse.urlencode(parametros, safe=",")
    pedido = urllib.request.Request(f"{url}?{consulta}",
                                    headers={"User-Agent": "huerto-inteligente/1.0",
                                             "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorClima(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorClima(f"sin conexión ({getattr(e, 'reason', e)})") from e
    except ValueError as e:
        raise ErrorClima("respuesta que no es JSON") from e


def validar_coordenadas(lat: Any, lon: Any) -> list[str]:
    """Errores en lenguaje simple; lista vacía si son válidas."""
    errores = []
    try:
        if not -90 <= float(lat) <= 90:
            errores.append("La latitud debe estar entre -90 y 90.")
    except (TypeError, ValueError):
        errores.append("La latitud debe ser un número.")
    try:
        if not -180 <= float(lon) <= 180:
            errores.append("La longitud debe estar entre -180 y 180.")
    except (TypeError, ValueError):
        errores.append("La longitud debe ser un número.")
    return errores


def num(valor: Any) -> Optional[float]:
    """Número o None (acepta None, int, float y texto numérico)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None
