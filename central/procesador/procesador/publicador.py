"""Tópicos MQTT y publicación de estados y tarjetas del tablero."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

TOPICO_ALERTAS = "huerto/tablero/alertas"


def topico_estado(nodo_id: str) -> str:
    """Estado de la cama (retenido): lo usan el LED del nodo y el tablero."""
    return f"huerto/cama/{nodo_id}/estado"


def topico_tarjeta(nodo_id: str) -> str:
    """Ficha completa de la cama para el tablero (retenida)."""
    return f"huerto/tablero/cama/{nodo_id}"


def iso(t: datetime | None) -> str | None:
    """datetime UTC ingenuo -> '2026-11-26T12:00:00Z' (con ms si los tiene)."""
    if t is None:
        return None
    if t.microsecond:
        return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _por_defecto(valor: Any):
    if isinstance(valor, datetime):
        return iso(valor)
    return float(valor)          # Decimal de la BD


class Publicador(Protocol):
    def publicar(self, topico: str, datos: dict, retener: bool = False) -> None: ...


class PublicadorMqtt:
    def __init__(self, cliente):
        self.cliente = cliente

    def publicar(self, topico: str, datos: dict, retener: bool = False) -> None:
        texto = json.dumps(datos, ensure_ascii=False, default=_por_defecto)
        self.cliente.publish(topico, texto, qos=1, retain=retener)


class PublicadorMemoria:
    """Para los tests: guarda lo publicado en una lista."""

    def __init__(self):
        self.mensajes: list[tuple[str, dict, bool]] = []

    def publicar(self, topico: str, datos: dict, retener: bool = False) -> None:
        # Se serializa igual que el real, para detectar tipos no serializables
        self.mensajes.append((topico, json.loads(json.dumps(datos, default=_por_defecto)), retener))

    def de_topico(self, topico: str) -> list[dict]:
        return [d for t, d, _ in self.mensajes if t == topico]

    def ultimo(self, topico: str) -> dict | None:
        lista = self.de_topico(topico)
        return lista[-1] if lista else None

    def limpiar(self) -> None:
        self.mensajes.clear()
