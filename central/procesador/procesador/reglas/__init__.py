"""Reglas de negocio puras (sin BD ni MQTT).

Cada evaluador recibe el valor actual, el rango efectivo y las alertas
abiertas, y devuelve una lista de `Decision` que el servicio aplica en la BD.
La deduplicación (una sola alerta abierta por tipo) la garantiza además la BD.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

ABRIR = "abrir"
ACTUALIZAR = "actualizar"
RESOLVER = "resolver"


@dataclass(frozen=True)
class Decision:
    accion: str                       # abrir | actualizar | resolver
    tipo: str                         # suelo_seco, helada, …
    variable: str                     # suelo | temperatura | luz
    valor: Optional[float] = None
    mensaje: Optional[str] = None
    iniciada_en: Optional[datetime] = None   # solo si difiere de la hora de la lectura


def abrir_o_actualizar(tipo: str, variable: str, valor: float, mensaje: str,
                       abiertas: set[str], iniciada_en: Optional[datetime] = None) -> Decision:
    """Si ya hay una alerta abierta de ese tipo, se ACTUALIZA (sin aviso nuevo)."""
    accion = ACTUALIZAR if tipo in abiertas else ABRIR
    return Decision(accion, tipo, variable, valor, mensaje,
                    iniciada_en if accion == ABRIR else None)
