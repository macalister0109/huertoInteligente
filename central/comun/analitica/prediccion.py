"""Predicción del tiempo hasta el mínimo de humedad (RF-15). Funciones puras.

1. Se toma el TRAMO DE SECADO actual: solo los datos desde el último riego.
   Los riegos se detectan aquí mismo con los datos recibidos (≤ ahora), y se
   suman los riegos ya conocidos (ej. manuales). Así la función nunca necesita
   ni usa datos posteriores a «ahora» (clave para el backtesting, CQ-12).
2. Dentro del tramo, se usan las últimas `ventana_h` horas (por defecto 6).
3. Regresión lineal. Hay estimación SOLO si:
     * hay al menos `min_puntos` puntos válidos (por defecto 12),
     * la pendiente es negativa (se está secando),
     * el ajuste es aceptable: R² ≥ `r2_min` (por defecto 0,6).
   Si no: «Sin tendencia clara».
4. horas = (mínimo − valor ajustado ahora) / pendiente, con un horizonte
   máximo de `horizonte_h` (6 h). Más allá: «no llegaría en las próximas 6 h».

Es una ESTIMACIÓN: el texto siempre lo dice.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from .riego import EventoRiego, Punto, detectar_riegos
from .tendencia import Ajuste, regresion_lineal

ESTIMACION = "estimacion"            # llegaría al mínimo dentro del horizonte
FUERA_HORIZONTE = "fuera_horizonte"  # se seca, pero no llegaría en las próximas 6 h
BAJO_MINIMO = "bajo_minimo"          # ya está bajo el mínimo (eso lo avisa la alerta normal)
SIN_TENDENCIA = "sin_tendencia"      # pocos puntos, no se seca o mal ajuste
SIN_RANGO = "sin_rango"              # la cama no tiene mínimo de humedad

SIN_TENDENCIA_TEXTO = "Sin tendencia clara"


@dataclass(frozen=True)
class ParametrosPrediccion:
    ventana_h: float = 6.0
    min_puntos: int = 12
    r2_min: float = 0.6
    horizonte_h: float = 6.0
    riego_umbral_pts: float = 10.0
    riego_ventana_min: float = 30.0


@dataclass(frozen=True)
class Prediccion:
    estado: str
    horas: Optional[float]               # solo con estado «estimacion»
    minimo: Optional[float]
    ajuste: Optional[Ajuste]
    desde: Optional[datetime]            # inicio de los datos usados
    inicio_tramo: Optional[datetime]     # fin del último riego (None = no hubo)
    motivo: str = ""

    @property
    def n_puntos(self) -> int:
        return 0 if self.ajuste is None else self.ajuste.n

    def texto(self, nombre_cama: str) -> str:
        if self.estado == ESTIMACION:
            return (f"Al ritmo actual, {en_frase(nombre_cama)} llegaría a {entero(self.minimo)} % "
                    f"en {duracion(self.horas)} (estimación)")
        if self.estado == FUERA_HORIZONTE:
            return (f"Al ritmo actual, {en_frase(nombre_cama)} no llegaría a {entero(self.minimo)} % "
                    f"en las próximas 6 h (estimación)")
        if self.estado == BAJO_MINIMO:
            return f"{nombre_cama} ya está bajo {entero(self.minimo)} %"
        if self.estado == SIN_RANGO:
            return "Configura un cultivo o un mínimo de humedad para estimar"
        return SIN_TENDENCIA_TEXTO


def en_frase(nombre: str) -> str:
    """«Cama A» -> «la Cama A» (para el texto del tablero)."""
    return nombre if nombre.lower().startswith(("la ", "el ")) else f"la {nombre}"


def entero(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(x):d}"


def duracion(horas: float) -> str:
    """0,7 -> «unos 40 min» · 1,6 -> «unas 1,5 h» · 4,6 -> «unas 5 h»."""
    if horas < 1:
        minutos = max(10, int(round(horas * 60 / 10.0)) * 10)
        return f"unos {minutos} min"
    if horas < 3:
        medias = round(horas * 2) / 2
        texto = f"{medias:g}".replace(".", ",")
        return f"una hora" if medias == 1 else f"unas {texto} h"
    return f"unas {round(horas)} h"


def predecir(puntos: Sequence[Punto], ahora: datetime, minimo: Optional[float],
             p: ParametrosPrediccion = ParametrosPrediccion(),
             riegos_conocidos: Iterable[EventoRiego] = (),
             tiempos: Optional[Sequence[datetime]] = None) -> Prediccion:
    """`puntos`: serie de humedad del suelo VÁLIDA en orden de tiempo. Solo se
    usan los puntos con t ≤ ahora (los posteriores se ignoran).
    `tiempos` = [q.t for q in puntos] ya calculado (acelera el backtesting)."""
    if minimo is None:
        return Prediccion(SIN_RANGO, None, None, None, None, None, "la cama no tiene mínimo")

    tiempos = tiempos if tiempos is not None else [q.t for q in puntos]
    hasta = bisect.bisect_right(tiempos, ahora)                  # nada después de «ahora»
    margen_riego = timedelta(minutes=p.riego_ventana_min) * 2
    desde_busqueda = ahora - timedelta(hours=p.ventana_h) - margen_riego
    inicio = bisect.bisect_left(tiempos, desde_busqueda)
    recientes = list(puntos[inicio:hasta])

    # Fin del último riego conocido o detectado con los datos hasta ahora
    fines = [e.fin or e.inicio for e in riegos_conocidos if (e.fin or e.inicio) <= ahora]
    fines += [e.fin for e in detectar_riegos(recientes, p.riego_umbral_pts, p.riego_ventana_min)
              if e.fin is not None]
    inicio_tramo = max(fines) if fines else None

    desde = ahora - timedelta(hours=p.ventana_h)
    if inicio_tramo is not None and inicio_tramo > desde:
        desde = inicio_tramo                                    # solo el tramo de secado actual
    usados = [(q.t, q.valor) for q in recientes if q.t >= desde]

    if len(usados) < p.min_puntos:
        return Prediccion(SIN_TENDENCIA, None, minimo, None, desde, inicio_tramo,
                          f"pocos puntos ({len(usados)} de {p.min_puntos})")
    ajuste = regresion_lineal(usados, t0=ahora)
    if ajuste is None:
        return Prediccion(SIN_TENDENCIA, None, minimo, None, desde, inicio_tramo, "sin variación en el tiempo")
    if ajuste.pendiente >= 0:
        return Prediccion(SIN_TENDENCIA, None, minimo, ajuste, desde, inicio_tramo, "no se está secando")
    if ajuste.r2 is None or ajuste.r2 < p.r2_min:
        return Prediccion(SIN_TENDENCIA, None, minimo, ajuste, desde, inicio_tramo,
                          f"ajuste insuficiente (R² {0 if ajuste.r2 is None else ajuste.r2:.2f})")

    actual = ajuste.intercepto                                   # valor ajustado en «ahora»
    if actual <= minimo:
        return Prediccion(BAJO_MINIMO, 0.0, minimo, ajuste, desde, inicio_tramo, "ya bajo el mínimo")
    horas = (minimo - actual) / ajuste.pendiente
    if horas > p.horizonte_h:
        return Prediccion(FUERA_HORIZONTE, None, minimo, ajuste, desde, inicio_tramo,
                          f"llegaría en {horas:.1f} h (más que el horizonte)")
    return Prediccion(ESTIMACION, round(horas, 2), minimo, ajuste, desde, inicio_tramo)
