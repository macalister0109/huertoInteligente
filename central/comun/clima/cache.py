"""Caché del clima en el servidor (el navegador nunca llama a la API externa).

* Dentro del TTL (20 min por defecto) no se repite la petición.
* Ante un error se devuelve el último valor guardado, marcado como
  «desactualizado» con su hora. Si no hay ninguno: «no disponible».
* Tras un error se espera `espera_tras_error_s` antes de reintentar, para que
  cada visita a la página no quede esperando el timeout de 5 s.
* Un solo aviso en el log por falla (no uno por visita): se vuelve a avisar
  solo después de que la API se recupere y falle de nuevo.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

Respaldo = Callable[[str, float, float], Optional["ClimaReferencia"]]

from ..db import ahora_utc
from .base import TIMEOUT_S, ClimaReferencia, ErrorClima, ProveedorClima, ProveedorNoConfigurado

log = logging.getLogger(__name__)

OK = "ok"
DESACTUALIZADO = "desactualizado"
NO_DISPONIBLE = "no_disponible"
NO_CONFIGURADO = "no_configurado"


@dataclass(frozen=True)
class ResultadoClima:
    estado: str                         # ok | desactualizado | no_disponible | no_configurado
    clima: Optional[ClimaReferencia]
    obtenido_en: Optional[datetime]     # cuándo se consultó con éxito (UTC)
    error: Optional[str] = None

    def edad_s(self, ahora: datetime) -> Optional[int]:
        """Edad del dato: desde la observación del proveedor."""
        if self.clima is None:
            return None
        return max(0, int((ahora - self.clima.observado_en).total_seconds()))


@dataclass
class _Entrada:
    clima: ClimaReferencia
    obtenido_en: datetime


class CacheClima:
    def __init__(self, ttl_s: float = 20 * 60, espera_tras_error_s: float = 120,
                 timeout_s: float = TIMEOUT_S, reloj: Callable[[], datetime] = ahora_utc,
                 respaldo: Optional[Respaldo] = None):
        """`respaldo(fuente, lat, lon)` entrega el último clima guardado en la BD,
        para cuando la caché en memoria está vacía (ej. justo tras reiniciar)."""
        self.ttl = timedelta(seconds=ttl_s)
        self.espera_tras_error = timedelta(seconds=espera_tras_error_s)
        self.timeout_s = timeout_s
        self.reloj = reloj
        self.respaldo = respaldo
        self._entradas: dict[tuple, _Entrada] = {}
        self._ultimo_error: dict[tuple, tuple[datetime, str]] = {}
        self._con_falla: set[tuple] = set()
        self._candado = threading.Lock()

    @staticmethod
    def _clave(proveedor: ProveedorClima, lat: float, lon: float) -> tuple:
        return (proveedor.nombre, round(float(lat), 4), round(float(lon), 4))

    def invalidar(self) -> None:
        with self._candado:
            self._entradas.clear()
            self._ultimo_error.clear()

    def en_memoria(self) -> list[ClimaReferencia]:
        """Los datos guardados en memoria (sin consultar la red)."""
        with self._candado:
            return [e.clima for e in self._entradas.values()]

    def consultar(self, proveedor: ProveedorClima, lat: float, lon: float,
                  forzar: bool = False, respaldo: Optional[Respaldo] = None) -> ResultadoClima:
        """`forzar=True` ignora el TTL y la espera tras error (botón «Probar conexión»).
        `respaldo` reemplaza al del constructor en esta consulta (ej. con la
        conexión a la BD de la petición web en curso)."""
        respaldo = respaldo or self.respaldo
        clave = self._clave(proveedor, lat, lon)
        motivo = proveedor.motivo_no_configurado()
        if motivo:
            return ResultadoClima(NO_CONFIGURADO, None, None, motivo)

        ahora = self.reloj()
        with self._candado:
            entrada = self._entradas.get(clave)
            error_previo = self._ultimo_error.get(clave)
        if not forzar:
            if entrada and ahora - entrada.obtenido_en < self.ttl:
                return ResultadoClima(OK, entrada.clima, entrada.obtenido_en)
            if error_previo and ahora - error_previo[0] < self.espera_tras_error:
                return self._sin_conexion(clave, entrada, error_previo[1], proveedor, lat, lon, respaldo)

        try:
            clima = proveedor.obtener(lat, lon, self.timeout_s)
        except ProveedorNoConfigurado as e:
            return ResultadoClima(NO_CONFIGURADO, None, None, str(e))
        except ErrorClima as e:
            return self._registrar_error(clave, entrada, str(e), proveedor, lat, lon, respaldo)
        except Exception as e:                      # un proveedor nunca debe tumbar la página
            return self._registrar_error(clave, entrada, f"error inesperado: {e}", proveedor, lat,
                                         lon, respaldo)

        with self._candado:
            self._entradas[clave] = _Entrada(clima, ahora)
            self._ultimo_error.pop(clave, None)
            if clave in self._con_falla:
                self._con_falla.discard(clave)
                log.info("Clima externo (%s) disponible de nuevo.", proveedor.nombre)
        return ResultadoClima(OK, clima, ahora)

    def _registrar_error(self, clave, entrada, error, proveedor, lat, lon,
                         respaldo) -> ResultadoClima:
        ahora = self.reloj()
        with self._candado:
            self._ultimo_error[clave] = (ahora, error)
            primera = clave not in self._con_falla
            self._con_falla.add(clave)
        if primera:
            log.warning("Clima externo (%s) no disponible: %s. Se usa el último dato guardado.",
                        proveedor.nombre, error)
        return self._sin_conexion(clave, entrada, error, proveedor, lat, lon, respaldo)

    def _sin_conexion(self, clave, entrada, error, proveedor, lat, lon,
                      respaldo) -> ResultadoClima:
        if entrada is not None:
            return ResultadoClima(DESACTUALIZADO, entrada.clima, entrada.obtenido_en, error)
        if respaldo is not None:
            try:
                guardado = respaldo(proveedor.nombre, lat, lon)
            except Exception:
                guardado = None
            if guardado is not None:
                return ResultadoClima(DESACTUALIZADO, guardado, None, error)
        return ResultadoClima(NO_DISPONIBLE, None, None, error)
