"""HU-03: helada y calor.

* Helada: inmediata apenas la temperatura baja del mínimo.
* Calor: solo si se mantiene SOBRE el máximo más de N minutos seguidos
  (por defecto 30). Una lectura en o bajo el máximo, o un hueco sin datos
  mayor a `max_hueco_min`, corta la racha. La racha se calcula desde las
  lecturas guardadas (no en memoria), así sobrevive a un reinicio.
* Ambas se resuelven al volver al rango con histéresis y quedan en el
  historial con su hora de inicio y término.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from comun import mensajes
from comun.rangos import Rango

from . import RESOLVER, Decision, abrir_o_actualizar

HELADA = "helada"
CALOR = "calor"


def inicio_racha_sobre_maximo(lecturas_desc: Sequence[tuple[datetime, float]],
                              maximo: float, max_hueco_min: float) -> Optional[datetime]:
    """Hora de inicio de la racha continua sobre el máximo que termina en la
    lectura más reciente. `lecturas_desc`: (medido_en, temp) de la más nueva
    a la más antigua, solo temperaturas válidas. None si la última no está
    sobre el máximo."""
    if not lecturas_desc or lecturas_desc[0][1] <= maximo:
        return None
    hueco = timedelta(minutes=max_hueco_min)
    inicio = lecturas_desc[0][0]
    for t, temp in lecturas_desc[1:]:
        if temp <= maximo or inicio - t > hueco:
            break
        inicio = t
    return inicio


def evaluar_temperatura(nombre: str, temp: float, medido_en: datetime, rango: Rango,
                        abiertas: set[str], histeresis: float,
                        inicio_racha_calor: Optional[datetime],
                        minutos_sostenido: float) -> list[Decision]:
    decisiones: list[Decision] = []

    # --- Helada (inmediata) ---
    if rango.temp_min is None:
        if HELADA in abiertas:
            decisiones.append(Decision(RESOLVER, HELADA, "temperatura", temp))
    elif temp < rango.temp_min:
        decisiones.append(abrir_o_actualizar(
            HELADA, "temperatura", temp, mensajes.helada(nombre, temp, rango.temp_min), abiertas))
    elif HELADA in abiertas and temp >= rango.temp_min + histeresis:
        decisiones.append(Decision(RESOLVER, HELADA, "temperatura", temp))

    # --- Calor (sostenido) ---
    if rango.temp_max is None:
        if CALOR in abiertas:
            decisiones.append(Decision(RESOLVER, CALOR, "temperatura", temp))
    elif temp > rango.temp_max:
        texto = mensajes.calor(nombre, temp, rango.temp_max)
        if CALOR in abiertas:
            decisiones.append(abrir_o_actualizar(CALOR, "temperatura", temp, texto, abiertas))
        elif (inicio_racha_calor is not None
              and medido_en - inicio_racha_calor >= timedelta(minutes=minutos_sostenido)):
            decisiones.append(abrir_o_actualizar(
                CALOR, "temperatura", temp, texto, abiertas, iniciada_en=inicio_racha_calor))
    elif CALOR in abiertas and temp <= rango.temp_max - histeresis:
        decisiones.append(Decision(RESOLVER, CALOR, "temperatura", temp))

    return decisiones
