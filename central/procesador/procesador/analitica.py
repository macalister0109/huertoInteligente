"""Tarea del procesador: mantiene al día las marcas de calidad y los agregados.

* Cada `cada_min` minutos busca las lecturas que LLEGARON desde la última
  vez (por recibido_en, así también cuenta las atrasadas del buffer de los
  nodos) y recalcula los días completos que tocan.
* Al cambiar la hora recalcula «hoy» de todas las camas, para cerrar la
  cobertura de la hora que terminó aunque no hayan llegado lecturas.
* Es idempotente: si se repite, reemplaza lo calculado sin duplicar.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from comun import ajustes
from comun.analitica import repositorio as repo
from comun.analitica.agregados import fecha_local
from comun.analitica.proceso import Resumen, recalcular_fechas
from comun.config import Config

log = logging.getLogger(__name__)

MARGEN_RECEPCION = timedelta(minutes=1)


class TareaAnalitica:
    def __init__(self, cfg: Config, cada_min: float = 5):
        self.cfg = cfg
        self.zona = ZoneInfo(cfg.zona_horaria)
        self.cada = timedelta(minutes=cada_min)
        self._revisado_hasta: Optional[datetime] = None
        self._ultima_ejecucion: Optional[datetime] = None
        self._ultima_hora: Optional[datetime] = None

    def pendiente(self, ahora: datetime) -> bool:
        return self._ultima_ejecucion is None or ahora - self._ultima_ejecucion >= self.cada

    def ejecutar(self, conn, ahora: datetime) -> Resumen:
        if not self.pendiente(ahora):
            return Resumen()
        self._ultima_ejecucion = ahora

        if self._revisado_hasta is None:
            # Al arrancar: desde el último cálculo guardado (o desde la primera lectura)
            self._revisado_hasta = repo.ultimo_calculo(conn) or repo.primera_recepcion(conn)
        if self._revisado_hasta is None:
            conn.commit()
            return Resumen()            # todavía no hay lecturas

        por_cama: dict[int, set] = {}
        for cama_id, medido_en in repo.recibidas_desde(conn, self._revisado_hasta - MARGEN_RECEPCION):
            por_cama.setdefault(cama_id, set()).add(fecha_local(medido_en, self.zona))

        hora = ahora.replace(minute=0, second=0, microsecond=0)
        if self._ultima_hora is not None and hora != self._ultima_hora:
            # Cambió la hora: se cierra la cobertura de la hora anterior
            anterior = fecha_local(hora - timedelta(minutes=1), self.zona)
            for cama in repo.camas(conn):
                if cama["activa"]:
                    por_cama.setdefault(cama["id"], set()).update({anterior, fecha_local(ahora, self.zona)})
        self._ultima_hora = hora

        total = Resumen()
        camas = {c["id"]: c for c in repo.camas(conn)} if por_cama else {}
        cfg = ajustes.config_vigente(conn, self.cfg) if por_cama else self.cfg   # umbral de riego
        conn.commit()
        for cama_id, fechas in por_cama.items():
            if cama_id in camas:
                total.sumar(recalcular_fechas(conn, cfg, camas[cama_id], fechas, ahora))
        self._revisado_hasta = ahora
        if total.dias:
            log.info("Agregados recalculados: %s día(s) de %s cama(s), %s marcas de calidad",
                     total.dias, len(total.camas), total.marcas)
        return total
