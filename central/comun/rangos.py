"""Rango efectivo de una cama (RF-09).

Cada rango personalizado de la cama reemplaza, campo por campo, al de su
cultivo: no es lo mismo plantar en el norte que en el sur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

CAMPOS_RANGO = ("humedad_min", "humedad_max", "temp_min", "temp_max", "horas_luz_min")


def _num(valor: Any) -> Optional[float]:
    return None if valor is None else float(valor)


@dataclass(frozen=True)
class Rango:
    humedad_min: Optional[float] = None
    humedad_max: Optional[float] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    horas_luz_min: Optional[float] = None
    cultivo: Optional[str] = None

    @property
    def configurado(self) -> bool:
        """Sin ningún rango no hay alertas: «Configura un cultivo…»."""
        return any(getattr(self, c) is not None for c in CAMPOS_RANGO)


def rango_efectivo(cama: Mapping[str, Any]) -> Rango:
    """Recibe una fila de `camas` unida con su cultivo.

    Las columnas del cultivo deben venir con el prefijo `cultivo_`
    (cultivo_humedad_min, …) y su nombre en `cultivo_nombre`.
    """
    valores = {}
    for campo in CAMPOS_RANGO:
        propio = cama.get(campo)
        valores[campo] = _num(propio if propio is not None else cama.get(f"cultivo_{campo}"))
    return Rango(**valores, cultivo=cama.get("cultivo_nombre"))
