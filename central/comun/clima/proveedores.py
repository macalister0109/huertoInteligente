"""Registro de proveedores de clima y elección del activo.

Las credenciales se leen SOLO del entorno (.env) del servidor: nunca se
guardan en la BD ni llegan al navegador.
"""

from __future__ import annotations

import os
from typing import Callable, Mapping, Optional

from .base import ProveedorClima
from .dmc import ProveedorDMC
from .open_meteo import ProveedorOpenMeteo
from .openweather import ProveedorOpenWeather

# nombre -> fábrica(entorno, zona_horaria)
Fabrica = Callable[[Mapping[str, str], str], ProveedorClima]

FABRICAS: dict[str, Fabrica] = {
    "open-meteo": lambda entorno, zona: ProveedorOpenMeteo(zona_horaria=zona),
    "dmc": lambda entorno, zona: ProveedorDMC(correo=entorno.get("DMC_USER_EMAIL", ""),
                                              token=entorno.get("DMC_API_TOKEN", ""),
                                              estacion=entorno.get("DMC_ESTACION", "")),
    "openweather": lambda entorno, zona: ProveedorOpenWeather(
        clave=entorno.get("OPENWEATHER_API_KEY", "")),
}

PROVEEDOR_POR_DEFECTO = "open-meteo"


def nombres() -> tuple[str, ...]:
    return tuple(FABRICAS)


def crear_proveedor(nombre: str, entorno: Optional[Mapping[str, str]] = None,
                    zona_horaria: str = "America/Santiago") -> ProveedorClima:
    """Crea el proveedor pedido; si el nombre no existe, usa Open-Meteo."""
    entorno = os.environ if entorno is None else entorno
    fabrica = FABRICAS.get(nombre) or FABRICAS[PROVEEDOR_POR_DEFECTO]
    return fabrica(entorno, zona_horaria)


