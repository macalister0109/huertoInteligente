"""Capa de clima externo de referencia (no es un pronóstico)."""

from .base import (ClimaReferencia, ErrorClima, ProveedorClima, ProveedorNoConfigurado,
                   validar_coordenadas)
from .cache import DESACTUALIZADO, NO_CONFIGURADO, NO_DISPONIBLE, OK, CacheClima, ResultadoClima
from .open_meteo import ProveedorOpenMeteo

__all__ = [
    "CacheClima", "ClimaReferencia", "ErrorClima", "ProveedorClima", "ProveedorNoConfigurado",
    "ProveedorOpenMeteo", "ResultadoClima", "validar_coordenadas",
    "OK", "DESACTUALIZADO", "NO_DISPONIBLE", "NO_CONFIGURADO",
]
