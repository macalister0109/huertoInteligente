"""Rango efectivo de una cama (RF-09) con ajuste por zona climática.

Para cada campo (humedad mín./máx., temperatura mín./máx., horas de luz) se
usa el primero que exista, en este orden:

  1. el rango PERSONALIZADO de la cama;
  2. el del CULTIVO EN LA ZONA de la cama (tabla rangos_cultivo_zona);
  3. el del CULTIVO genérico.

La zona de la cama es la elegida para esa cama o, si no tiene, la zona del
huerto (/configuracion; por defecto «centro»). No es lo mismo plantar en el
norte que en el sur. Los valores de zona son de EJEMPLO: por confirmar con
las fichas de INIA / INDAP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

CAMPOS_RANGO = ("humedad_min", "humedad_max", "temp_min", "temp_max", "horas_luz_min")

CAMA, ZONA, CULTIVO = "cama", "zona", "cultivo"

# Consulta ÚNICA de una cama con su cultivo y su zona (la usan el procesador,
# la web y la capa de análisis). Requiere la migración 007 (vista v_camas_zona).
SELECT_CAMA = """
    SELECT c.*, cu.nombre AS cultivo_nombre,
           cu.humedad_min AS cultivo_humedad_min, cu.humedad_max AS cultivo_humedad_max,
           cu.temp_min AS cultivo_temp_min, cu.temp_max AS cultivo_temp_max,
           cu.horas_luz_min AS cultivo_horas_luz_min,
           vz.zona_efectiva_id, vz.zona_codigo, vz.zona_nombre, vz.zona_heredada,
           vz.zona_humedad_min, vz.zona_humedad_max, vz.zona_temp_min, vz.zona_temp_max,
           vz.zona_horas_luz_min, vz.zona_por_confirmar
      FROM camas c
      LEFT JOIN cultivos cu ON cu.id = c.cultivo_id
      LEFT JOIN v_camas_zona vz ON vz.cama_id = c.id
"""


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
    zona: Optional[str] = None
    # De dónde salió cada campo: {"humedad_min": "cama" | "zona" | "cultivo"}
    origenes: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def configurado(self) -> bool:
        """Sin ningún rango no hay alertas: «Configura un cultivo…»."""
        return any(getattr(self, c) is not None for c in CAMPOS_RANGO)


def rango_efectivo(cama: Mapping[str, Any]) -> Rango:
    """Recibe una fila de SELECT_CAMA (cama unida con su cultivo y su zona).

    Columnas: las propias de la cama (humedad_min, …), las del cultivo con
    prefijo `cultivo_` y las del cultivo en la zona con prefijo `zona_`.
    """
    valores, origenes = {}, {}
    for campo in CAMPOS_RANGO:
        for origen, clave in ((CAMA, campo), (ZONA, f"zona_{campo}"), (CULTIVO, f"cultivo_{campo}")):
            valor = cama.get(clave)
            if valor is not None:
                valores[campo], origenes[campo] = _num(valor), origen
                break
        else:
            valores[campo] = None
    return Rango(**valores, cultivo=cama.get("cultivo_nombre"), zona=cama.get("zona_nombre"),
                 origenes=origenes)
