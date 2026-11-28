"""Tendencias: regresión lineal y textos simples. Funciones puras (sin BD).

* regresion_lineal: mínimos cuadrados (y = a + b·t) con t en horas. Devuelve
  la pendiente (puntos % por hora), el intercepto, el R² y el número de puntos.
  Python puro: no necesita numpy (corre igual en la Raspberry Pi).
* Etiqueta de la pendiente de la humedad del suelo (valores de EJEMPLO,
  configurables con TENDENCIA_PTS_RAPIDO y TENDENCIA_PTS_ESTABLE):
      pendiente < −1,0 pts/h       «Secándose rápido»
      −1,0 ≤ pendiente < −0,2      «Secándose lento»
      −0,2 ≤ pendiente ≤ +0,2      «Estable»
      pendiente > +0,2             «Subiendo»
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

SECANDOSE_RAPIDO = "Secándose rápido"
SECANDOSE_LENTO = "Secándose lento"
ESTABLE = "Estable"
SUBIENDO = "Subiendo"
SIN_DATOS = "Sin datos suficientes"


@dataclass(frozen=True)
class Ajuste:
    pendiente: float          # unidades por hora
    intercepto: float         # valor en t = 0 (el instante de referencia)
    r2: Optional[float]       # None si los valores son todos iguales (no hay varianza)
    n: int
    t0: datetime              # instante de referencia (t = 0)

    def valor_en(self, t: datetime) -> float:
        return self.intercepto + self.pendiente * (t - self.t0).total_seconds() / 3600


def regresion_lineal(puntos: Sequence[tuple[datetime, float]],
                     t0: Optional[datetime] = None) -> Optional[Ajuste]:
    """None con menos de 2 puntos o si todos tienen la misma hora."""
    n = len(puntos)
    if n < 2:
        return None
    t0 = t0 or puntos[0][0]
    xs = [(t - t0).total_seconds() / 3600 for t, _ in puntos]
    ys = [float(v) for _, v in puntos]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    b = sxy / sxx
    a = my - b * mx
    if syy == 0:
        r2 = None                       # recta perfecta y plana: R² no está definido
    else:
        sse = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
        r2 = max(0.0, 1 - sse / syy)
    return Ajuste(b, a, r2, n, t0)


def etiqueta_suelo(pendiente: Optional[float], rapido: float = 1.0, estable: float = 0.2) -> str:
    if pendiente is None:
        return SIN_DATOS
    if pendiente > estable:
        return SUBIENDO
    if pendiente >= -estable:
        return ESTABLE
    if pendiente >= -rapido:
        return SECANDOSE_LENTO
    return SECANDOSE_RAPIDO


def _decimal(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


@dataclass(frozen=True)
class PendienteVentana:
    horas: float
    ajuste: Optional[Ajuste]
    etiqueta: str

    @property
    def texto(self) -> str:
        if self.ajuste is None:
            return f"{SIN_DATOS} en las últimas {self.horas:g} h"
        p = self.ajuste.pendiente
        signo = "+" if p > 0 else "−" if p < 0 else ""
        return f"{self.etiqueta} ({signo}{_decimal(abs(p))} puntos por hora en las últimas {self.horas:g} h)"


def pendiente_ventana(puntos: Iterable[tuple[datetime, float]], ahora: datetime, horas: float,
                      min_puntos: int = 6, cobertura_min: float = 0.5,
                      rapido: float = 1.0, estable: float = 0.2) -> PendienteVentana:
    """Pendiente de los puntos en [ahora − horas, ahora]. Exige `min_puntos` y
    que los datos cubran al menos `cobertura_min` de la ventana (de la primera
    a la última lectura): con dos lecturas juntas no se puede hablar de tendencia."""
    desde = ahora - timedelta(hours=horas)
    en_ventana = sorted((t, v) for t, v in puntos if desde <= t <= ahora)
    if len(en_ventana) < min_puntos:
        return PendienteVentana(horas, None, SIN_DATOS)
    if (en_ventana[-1][0] - en_ventana[0][0]) < timedelta(hours=horas * cobertura_min):
        return PendienteVentana(horas, None, SIN_DATOS)
    ajuste = regresion_lineal(en_ventana, t0=ahora)
    if ajuste is None:
        return PendienteVentana(horas, None, SIN_DATOS)
    return PendienteVentana(horas, ajuste, etiqueta_suelo(ajuste.pendiente, rapido, estable))


# --------------------------------------------------------------- media móvil

def media_movil(horas: Sequence[tuple[datetime, float, int]], ahora: datetime,
                ventana_h: float = 24, min_n: int = 1) -> Optional[float]:
    """Media de las últimas `ventana_h` horas a partir de los agregados por hora
    (hora_inicio, media, n_lecturas), ponderada por el número de lecturas."""
    desde = ahora - timedelta(hours=ventana_h)
    usados = [(m, n) for t, m, n in horas if desde <= t < ahora and m is not None and n >= min_n]
    total = sum(n for _, n in usados)
    return None if total == 0 else round(sum(m * n for m, n in usados) / total, 2)


def serie_media_movil(horas: Sequence[tuple[datetime, float, int]], desde: datetime,
                      hasta: datetime, ventana_h: float = 24) -> list[tuple[datetime, Optional[float]]]:
    """Media móvil al final de cada hora entre `desde` y `hasta` (para graficar)."""
    ordenadas = sorted(horas)
    resultado = []
    t = desde.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t <= hasta:
        resultado.append((t, media_movil(ordenadas, t, ventana_h)))
        t += timedelta(hours=1)
    return resultado


# ---------------------------------------------------------- amplitud térmica

@dataclass(frozen=True)
class ComparacionAmplitud:
    cama_min: Optional[float]
    cama_max: Optional[float]
    exterior_min: Optional[float]
    exterior_max: Optional[float]

    @property
    def cama(self) -> Optional[float]:
        return None if self.cama_min is None else round(self.cama_max - self.cama_min, 1)

    @property
    def exterior(self) -> Optional[float]:
        return None if self.exterior_min is None else round(self.exterior_max - self.exterior_min, 1)

    @property
    def diferencia(self) -> Optional[float]:
        if self.cama is None or self.exterior is None:
            return None
        return round(self.cama - self.exterior, 1)

    def texto(self, cuando: str = "ayer") -> Optional[str]:
        if self.cama is None:
            return None
        base = (f"{cuando.capitalize()} la temperatura de la cama varió {_decimal(self.cama, 0)} °C "
                f"(de {_decimal(self.cama_min, 0)} a {_decimal(self.cama_max, 0)} °C)")
        if self.exterior is None:
            return base + "."
        d = self.diferencia
        if abs(d) < 2:                       # dentro del error del DHT11
            comparacion = "parecido a la zona"
        elif d > 0:
            comparacion = f"{_decimal(d, 0)} °C más que la zona"
        else:
            comparacion = f"{_decimal(abs(d), 0)} °C menos que la zona"
        return f"{base}; afuera, {_decimal(self.exterior, 0)} °C: {comparacion}."
