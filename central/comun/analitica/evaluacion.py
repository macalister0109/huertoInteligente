"""Evaluación de la predicción de secado (CQ-10, CQ-11, CQ-12 y CQ-13). Puro.

Backtesting con ventana deslizante temporal (CQ-12):
* Se recorren instantes t cada `paso_min` minutos. En cada t el modelo
  recibe la serie completa, pero `predecir` solo usa puntos con tiempo ≤ t.
  La referencia ingenua usa solo tramos de secado que ya terminaron (y se
  confirmaron) antes de t. El futuro se usa ÚNICAMENTE para saber la verdad:
  el momento real en que la humedad cruzó el mínimo.
* Caso evaluable: en t la cama está sobre el mínimo y el cruce real ocurre
  dentro del horizonte (6 h) sin que antes haya un riego.
* Modelo: «estimacion» -> horas; «fuera_horizonte» -> 6 h (dijo «más de 6 h»);
  «bajo_minimo» -> 0 h; «sin_tendencia» -> no predice (se informa aparte).
* Referencia ingenua (CQ-11): tasa de secado promedio histórica constante,
  calculada con los tramos ya terminados antes de t:
  horas = (valor actual − mínimo) / tasa, con tope en el horizonte.
* Ambos se comparan sobre LOS MISMOS casos: aquellos en que los dos predicen.
* MAE = promedio de |predicho − real| en horas. Meta CQ-10: ≤ 2 h.
* Con pocos casos se informa «datos insuficientes» y NO se calculan métricas.
"""

from __future__ import annotations

import bisect
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .prediccion import BAJO_MINIMO, ESTIMACION, FUERA_HORIZONTE, ParametrosPrediccion, predecir
from .riego import EventoRiego, Punto, detectar_riegos
from .tendencia import regresion_lineal

MIN_CASOS = 30
META_MAE_H = 2.0
MIN_HORAS_TRAMO = 2.0            # tramos más cortos no sirven para estimar la tasa


@dataclass(frozen=True)
class Caso:
    cama: str
    t: datetime
    valor: float
    minimo: float
    real_h: float
    modelo_estado: str
    modelo_h: Optional[float]
    ingenuo_h: Optional[float]

    @property
    def comparable(self) -> bool:
        return self.modelo_h is not None and self.ingenuo_h is not None

    @property
    def error_modelo(self) -> Optional[float]:
        return None if self.modelo_h is None else abs(self.modelo_h - self.real_h)

    @property
    def error_ingenuo(self) -> Optional[float]:
        return None if self.ingenuo_h is None else abs(self.ingenuo_h - self.real_h)


@dataclass
class Resultado:
    casos: list[Caso] = field(default_factory=list)
    instantes: int = 0
    avisos_sin_cruce: int = 0            # el modelo estimó cruce ≤ 6 h y no ocurrió
    tiempos_ms: list[float] = field(default_factory=list)
    camas: list[str] = field(default_factory=list)

    @property
    def comparables(self) -> list[Caso]:
        return [c for c in self.casos if c.comparable]

    @property
    def suficiente(self) -> bool:
        return len(self.comparables) >= MIN_CASOS

    @property
    def mae_modelo(self) -> Optional[float]:
        c = self.comparables
        return round(statistics.fmean(x.error_modelo for x in c), 3) if c and self.suficiente else None

    @property
    def mae_ingenuo(self) -> Optional[float]:
        c = self.comparables
        return round(statistics.fmean(x.error_ingenuo for x in c), 3) if c and self.suficiente else None

    @property
    def supera_referencia(self) -> Optional[bool]:
        if self.mae_modelo is None or self.mae_ingenuo is None:
            return None
        return self.mae_modelo < self.mae_ingenuo

    @property
    def cumple_meta(self) -> Optional[bool]:
        return None if self.mae_modelo is None else self.mae_modelo <= META_MAE_H

    def sumar(self, otro: "Resultado") -> None:
        self.casos += otro.casos
        self.instantes += otro.instantes
        self.avisos_sin_cruce += otro.avisos_sin_cruce
        self.tiempos_ms += otro.tiempos_ms
        self.camas += otro.camas


# --------------------------------------------------------------- la verdad

def horas_reales_hasta_minimo(puntos: Sequence[Punto], tiempos: Sequence[datetime], t: datetime,
                              minimo: float, p: ParametrosPrediccion) -> Optional[float]:
    """Horas desde t hasta el primer punto ≤ mínimo, dentro del horizonte y sin
    un riego antes. None si no cruza. (Usa el futuro: es la verdad, no el modelo.)"""
    fin = t + timedelta(hours=p.horizonte_h)
    i0 = bisect.bisect_right(tiempos, t)
    i1 = bisect.bisect_right(tiempos, fin)
    cruce = next((q.t for q in puntos[i0:i1] if q.valor <= minimo), None)
    if cruce is None:
        return None
    desde = bisect.bisect_left(tiempos, t - timedelta(minutes=p.riego_ventana_min))
    riegos = detectar_riegos(puntos[desde:i1], p.riego_umbral_pts, p.riego_ventana_min)
    if any(t < e.inicio < cruce for e in riegos):
        return None
    return (cruce - t).total_seconds() / 3600


# ------------------------------------------------------ referencia ingenua

@dataclass(frozen=True)
class TramoCerrado:
    confirmado_en: datetime        # desde cuándo se puede usar sin mirar el futuro
    tasa: float                    # puntos por hora (positiva = se seca)


def tramos_cerrados(puntos: Sequence[Punto], p: ParametrosPrediccion) -> list[TramoCerrado]:
    """Tasa de secado de cada tramo entre dos riegos. Un tramo se puede usar
    desde que el riego que lo cierra quedó confirmado (su fin + la ventana de
    detección): antes de eso, saberlo sería mirar el futuro."""
    riegos = detectar_riegos(puntos, p.riego_umbral_pts, p.riego_ventana_min)
    tiempos = [q.t for q in puntos]
    resultado = []
    for anterior, siguiente in zip(riegos, riegos[1:]):
        desde, hasta = anterior.fin, siguiente.inicio
        if (hasta - desde) < timedelta(hours=MIN_HORAS_TRAMO):
            continue
        tramo = puntos[bisect.bisect_left(tiempos, desde):bisect.bisect_left(tiempos, hasta)]
        ajuste = regresion_lineal([(q.t, q.valor) for q in tramo])
        if ajuste is None or ajuste.pendiente >= 0 or len(tramo) < p.min_puntos:
            continue
        confirmado = siguiente.fin + timedelta(minutes=p.riego_ventana_min)
        resultado.append(TramoCerrado(confirmado, -ajuste.pendiente))
    return sorted(resultado, key=lambda x: x.confirmado_en)


def tasa_ingenua(tramos: Sequence[TramoCerrado], t: datetime) -> Optional[float]:
    usables = [x.tasa for x in tramos if x.confirmado_en <= t]
    return statistics.fmean(usables) if usables else None


# ------------------------------------------------------------ backtesting

def evaluar_cama(nombre: str, puntos: Sequence[Punto], minimo: float,
                 p: ParametrosPrediccion = ParametrosPrediccion(), paso_min: float = 30,
                 riegos_conocidos: Sequence[EventoRiego] = ()) -> Resultado:
    r = Resultado(camas=[nombre])
    if len(puntos) < 2:
        return r
    puntos = sorted(puntos, key=lambda q: q.t)
    tiempos = [q.t for q in puntos]
    tramos = tramos_cerrados(puntos, p)
    paso = timedelta(minutes=paso_min)
    t = tiempos[0] + timedelta(hours=p.ventana_h)
    ultimo = tiempos[-1] - timedelta(hours=p.horizonte_h)
    while t <= ultimo:
        i = bisect.bisect_right(tiempos, t) - 1
        if i >= 0 and t - tiempos[i] <= timedelta(minutes=10) and puntos[i].valor > minimo:
            r.instantes += 1
            conocidos = [e for e in riegos_conocidos if (e.fin or e.inicio) <= t]
            inicio = time.perf_counter()
            pred = predecir(puntos, t, minimo, p, conocidos, tiempos=tiempos)
            r.tiempos_ms.append((time.perf_counter() - inicio) * 1000)
            real = horas_reales_hasta_minimo(puntos, tiempos, t, minimo, p)
            if pred.estado == ESTIMACION and real is None:
                r.avisos_sin_cruce += 1
            if real is not None:
                modelo = {ESTIMACION: pred.horas, FUERA_HORIZONTE: p.horizonte_h,
                          BAJO_MINIMO: 0.0}.get(pred.estado)
                tasa = tasa_ingenua(tramos, t)
                ingenuo = None
                if tasa:
                    ingenuo = min(p.horizonte_h, max(0.0, (puntos[i].valor - minimo) / tasa))
                r.casos.append(Caso(nombre, t, puntos[i].valor, minimo, round(real, 3),
                                    pred.estado, modelo, ingenuo))
        t += paso
    return r
