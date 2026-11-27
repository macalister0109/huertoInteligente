"""Interfaz de sincronización con la nube (ITERACIÓN 2, no implementada).

Queda definida ahora para no rehacer nada después: el procesador llama a
`sincronizar()` en cada ciclo. En la iteración 2 bastará con escribir una
clase que suba las filas con `sincronizado = 0` (lecturas, alertas,
luz_diaria) y las marque con 1, y elegirla por configuración.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Sincronizador(ABC):
    @abstractmethod
    def sincronizar(self, conn) -> int:
        """Sube lo pendiente. Devuelve cuántas filas se sincronizaron."""


class SincronizadorNulo(Sincronizador):
    """Iteración 1: el sistema funciona sin internet; no se sincroniza nada."""

    def sincronizar(self, conn) -> int:
        return 0
