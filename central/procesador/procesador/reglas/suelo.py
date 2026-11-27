"""HU-02: alertas de humedad del suelo, con histéresis (CQ-05).

* Bajo el mínimo  -> abre (o actualiza) `suelo_seco`.
* Sobre el máximo -> abre (o actualiza) `suelo_encharcado`.
* Se resuelve solo al volver al rango con margen:
    seco:       humedad >= mínimo + histéresis
    encharcado: humedad <= máximo - histéresis
  Entre el borde y el margen la alerta sigue abierta, sin cambios: así no
  se abre y se cierra una y otra vez cuando el valor oscila en el borde.
"""

from __future__ import annotations

from comun import mensajes
from comun.rangos import Rango

from . import RESOLVER, Decision, abrir_o_actualizar

SECO = "suelo_seco"
ENCHARCADO = "suelo_encharcado"


def evaluar_suelo(nombre: str, humedad: float, rango: Rango, abiertas: set[str],
                  histeresis: float) -> list[Decision]:
    decisiones: list[Decision] = []

    # --- Seco ---
    if rango.humedad_min is None:
        if SECO in abiertas:
            decisiones.append(Decision(RESOLVER, SECO, "suelo", humedad))
    elif humedad < rango.humedad_min:
        texto = mensajes.suelo_seco(nombre, humedad, rango.humedad_min, rango.humedad_max)
        decisiones.append(abrir_o_actualizar(SECO, "suelo", humedad, texto, abiertas))
    elif SECO in abiertas and humedad >= rango.humedad_min + histeresis:
        decisiones.append(Decision(RESOLVER, SECO, "suelo", humedad))

    # --- Encharcado ---
    if rango.humedad_max is None:
        if ENCHARCADO in abiertas:
            decisiones.append(Decision(RESOLVER, ENCHARCADO, "suelo", humedad))
    elif humedad > rango.humedad_max:
        texto = mensajes.suelo_encharcado(nombre, humedad, rango.humedad_max)
        decisiones.append(abrir_o_actualizar(ENCHARCADO, "suelo", humedad, texto, abiertas))
    elif ENCHARCADO in abiertas and humedad <= rango.humedad_max - histeresis:
        decisiones.append(Decision(RESOLVER, ENCHARCADO, "suelo", humedad))

    return decisiones
