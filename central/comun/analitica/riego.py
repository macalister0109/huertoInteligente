"""Eventos de riego y tramos de secado. Funciones puras (sin BD).

Riego detectado: la humedad del suelo sube al menos `umbral` puntos respecto
del valor más bajo de los últimos `ventana` minutos (por defecto +10 puntos
en 30 min o menos).

* inicio = la lectura más baja antes de la subida (humedad_antes).
* fin    = el punto más alto de la subida: se sigue avanzando mientras la
  humedad siga subiendo dentro de la ventana (humedad_despues).
* Un riego nuevo solo puede empezar después del fin del anterior.
* Solo se usan valores válidos: los marcados rango/salto/pegado no cuentan.
  (Las subidas de suelo NUNCA se marcan como salto: se permiten por el riego.)

Cada riego parte un «tramo de secado»: desde su fin hasta el inicio del
siguiente riego. Las tendencias se calculan dentro del tramo en curso.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from .calidad import LecturaCruda, Marca, excluidas

DETECTADO, MANUAL = "detectado", "manual"


@dataclass(frozen=True)
class Punto:
    lectura_id: int
    t: datetime
    valor: float


@dataclass(frozen=True)
class EventoRiego:
    inicio: datetime
    fin: Optional[datetime]
    humedad_antes: Optional[float]
    humedad_despues: Optional[float]
    origen: str = DETECTADO
    lectura_antes_id: Optional[int] = None
    lectura_despues_id: Optional[int] = None
    id: Optional[int] = None

    @property
    def subida(self) -> Optional[float]:
        if self.humedad_antes is None or self.humedad_despues is None:
            return None
        return round(self.humedad_despues - self.humedad_antes, 1)


@dataclass(frozen=True)
class Tramo:
    """Período de secado entre dos riegos. `fin` None = tramo en curso."""
    inicio: datetime
    fin: Optional[datetime]
    evento: Optional[EventoRiego]          # el riego que lo inició (None = antes del primero)

    def contiene(self, t: datetime) -> bool:
        return t >= self.inicio and (self.fin is None or t < self.fin)


def puntos_suelo(lecturas: Iterable[LecturaCruda], marcas: Iterable[Marca] = ()) -> list[Punto]:
    """Serie de humedad del suelo válida y sin marcas que la excluyan, en orden."""
    fuera = excluidas(marcas)
    return sorted((Punto(l.id, l.medido_en, l.suelo) for l in lecturas
                   if l.suelo is not None and (l.id, "suelo") not in fuera),
                  key=lambda p: (p.t, p.lectura_id))


def detectar_riegos(puntos: Sequence[Punto], umbral: float = 10.0,
                    ventana_min: float = 30.0) -> list[EventoRiego]:
    """O(n): el mínimo de la ventana se mantiene en una cola monótona."""
    ventana = timedelta(minutes=ventana_min)
    eventos: list[EventoRiego] = []
    ultimo_fin: Optional[datetime] = None
    # Índices de candidatos con valores crecientes: el primero es el más bajo.
    # En un empate queda el más reciente (ahí empieza la subida).
    cola: deque[int] = deque()
    n = len(puntos)
    j = 0
    while j < n:
        actual = puntos[j]
        if ultimo_fin is not None and actual.t <= ultimo_fin:
            if actual.t == ultimo_fin:          # el pico del riego anterior sí es candidato
                _agregar(cola, puntos, j)
            j += 1
            continue
        while cola and puntos[cola[0]].t < actual.t - ventana:
            cola.popleft()
        if cola and actual.valor - puntos[cola[0]].valor >= umbral:
            bajo = puntos[cola[0]]
            # Se busca el punto más alto mientras siga subiendo dentro de la ventana
            alto = actual
            m = j + 1
            while m < n and puntos[m].t - alto.t <= ventana:
                if puntos[m].valor > alto.valor:
                    alto = puntos[m]
                m += 1
            eventos.append(EventoRiego(bajo.t, alto.t, bajo.valor, alto.valor, DETECTADO,
                                       bajo.lectura_id, alto.lectura_id))
            ultimo_fin = alto.t
            cola.clear()
            j += 1
            continue
        _agregar(cola, puntos, j)
        j += 1
    return eventos


def _agregar(cola: "deque[int]", puntos: Sequence[Punto], j: int) -> None:
    while cola and puntos[cola[-1]].valor >= puntos[j].valor:
        cola.pop()
    cola.append(j)


def tramos(eventos: Iterable[EventoRiego], desde: datetime) -> list[Tramo]:
    """Parte el tiempo desde `desde` en tramos de secado. Riegos de distinto
    origen (detectado y manual) separados por menos de 30 min se cuentan como
    el mismo riego."""
    ordenados = sorted(eventos, key=lambda e: e.inicio)
    unicos: list[EventoRiego] = []
    for e in ordenados:
        if unicos and e.inicio - (unicos[-1].fin or unicos[-1].inicio) < timedelta(minutes=30):
            continue
        unicos.append(e)
    resultado: list[Tramo] = []
    inicio, evento = desde, None
    for e in unicos:
        fin_riego = e.fin or e.inicio
        if fin_riego <= desde:
            inicio, evento = max(desde, fin_riego), e
            continue
        if e.inicio > inicio:
            resultado.append(Tramo(inicio, e.inicio, evento))
        inicio, evento = fin_riego, e
    resultado.append(Tramo(inicio, None, evento))
    return resultado


def tramo_actual(eventos: Iterable[EventoRiego], desde: datetime) -> Tramo:
    return tramos(eventos, desde)[-1]
