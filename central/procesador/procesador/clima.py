"""Tarea del procesador: guarda una instantánea del clima de referencia por hora.

* Corre dentro del ciclo periódico (cada minuto), pero solo consulta la API
  una vez por hora: no depende de que alguien visite la página.
* La petición se hace en un hilo aparte con un tope de espera, para que una
  red colgada nunca detenga el procesamiento de lecturas y alertas.
* Si falla, reintenta en el ciclo siguiente cada `reintento_min` minutos.
  Un solo aviso en el log por falla.
* El huerto funciona igual sin internet: esto es solo una referencia.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as TiempoAgotado
from datetime import datetime, timedelta
from typing import Callable, Optional

from comun import ajustes
from comun.clima import ErrorClima, ProveedorClima
from comun.clima import repositorio as repo_clima
from comun.clima.base import TIMEOUT_S
from comun.clima.proveedores import crear_proveedor
from comun.config import Config

log = logging.getLogger(__name__)

CrearProveedor = Callable[[str], ProveedorClima]


class TareaClima:
    def __init__(self, cfg: Config, crear: Optional[CrearProveedor] = None,
                 reintento_min: float = 10, espera_max_s: float = TIMEOUT_S + 2):
        self.cfg = cfg
        self.crear = crear or (lambda nombre: crear_proveedor(nombre, zona_horaria=cfg.zona_horaria))
        self.reintento = timedelta(minutes=reintento_min)
        self.espera_max_s = espera_max_s
        self._hora_guardada: Optional[datetime] = None
        self._ultimo_intento: Optional[datetime] = None
        self._en_falla = False
        self._hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clima")

    @staticmethod
    def _hora(t: datetime) -> datetime:
        return t.replace(minute=0, second=0, microsecond=0)

    def pendiente(self, ahora: datetime) -> bool:
        if self._hora_guardada == self._hora(ahora):
            return False
        return self._ultimo_intento is None or ahora - self._ultimo_intento >= self.reintento

    def ejecutar(self, conn, ahora: datetime) -> bool:
        """Devuelve True si guardó una instantánea nueva."""
        if not self.pendiente(ahora):
            return False
        self._ultimo_intento = ahora
        vigentes = ajustes.leer(conn, self.cfg)
        conn.commit()
        proveedor = self.crear(vigentes["clima_proveedor"])
        proveedor.aplicar_ajustes(vigentes)
        if not proveedor.configurado():
            # «No configurado» no es una falla: no se insiste hasta la próxima hora
            self._hora_guardada = self._hora(ahora)
            return False
        lat, lon = vigentes["clima_lat"], vigentes["clima_lon"]
        try:
            futuro = self._hilo.submit(proveedor.obtener, lat, lon, TIMEOUT_S)
            clima = futuro.result(timeout=self.espera_max_s)
        except (ErrorClima, TiempoAgotado, Exception) as e:   # nunca debe tumbar el procesador
            if not self._en_falla:
                log.warning("Clima externo (%s) no disponible: %s. Se reintenta más tarde.",
                            proveedor.nombre, e or "tiempo agotado")
            self._en_falla = True
            return False
        repo_clima.guardar_instantanea(conn, clima, ahora)
        conn.commit()
        if self._en_falla:
            log.info("Clima externo (%s) disponible de nuevo.", proveedor.nombre)
        self._en_falla = False
        self._hora_guardada = self._hora(ahora)
        log.info("Clima de referencia guardado: %s °C, %s %% (%s, %s UTC)", clima.temp_aire_c,
                 clima.hum_rel_pct, clima.fuente, clima.observado_en)
        return True

    def cerrar(self) -> None:
        self._hilo.shutdown(wait=False, cancel_futures=True)
