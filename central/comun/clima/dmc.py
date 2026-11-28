"""Proveedor DMC — Dirección Meteorológica de Chile (opcional).

Documentación oficial (leída el 2026-11-27):
  https://climatologia.meteochile.gob.cl/application/requerimiento/producto/RE8011
  https://climatologia.meteochile.gob.cl/application/documentacion/getDocumento/2
    «Datos 12 Horas Recientes de una Estación Automática» (EMA)

  GET https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesEma/{codigoNacional}
      ?usuario={correo}&token={token}

Credenciales (solo en el .env del servidor): DMC_USER_EMAIL y DMC_API_TOKEN.
El código de la estación (codigoNacional) se elige en /configuracion; la DMC
publica el catastro de estaciones en el mismo portal (getDocumento/0).

Formato documentado (ejemplo de la DMC):
  {"timezone": "UTC", "status": "...", "datosEstaciones": {
       "estacion": {"codigoNacional": "410005", "latitud": "-41.44750", "longitud": "-73.09583", ...},
       "datos": [{"momento": "2023-07-04 19:00:00", "temperatura": "8.0 °C",
                  "humedadRelativa": "79 %", "radiacionGlobalInst": "158.900 Watt/m2",
                  "aguaCaidaDelMinuto": "0.0 mm", ...}, ...]}}
  * Los valores vienen como TEXTO con la unidad: se extrae el número.
  * La documentación no dice el orden de `datos`: se usa el `momento` más reciente.
  * No entrega temperatura ni humedad del suelo ni ET0: quedan en None.

TODO: verificar con un token real (no se pudo probar sin credenciales). Si la
respuesta real difiere del ejemplo documentado, la normalización lanza
ErrorClima y el tablero muestra «Clima exterior no disponible».
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from .base import (TIMEOUT_S, ClimaReferencia, ErrorClima, ObtenerJson, ProveedorClima,
                   ProveedorNoConfigurado, obtener_json_http)

URL = "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesEma"
FUENTE = "dmc"
_NUMERO = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def numero_con_unidad(valor: Any) -> Optional[float]:
    """«8.0 °C» -> 8.0 · «79 %» -> 79.0 · None o «» -> None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    m = _NUMERO.search(str(valor))
    return float(m.group().replace(",", ".")) if m else None


def _momento(texto: Any) -> datetime:
    try:
        return datetime.strptime(str(texto), "%Y-%m-%d %H:%M:%S")      # UTC según la DMC
    except ValueError as e:
        raise ErrorClima(f"hora no válida en la respuesta de la DMC: {texto!r}") from e


def normalizar(datos: Mapping[str, Any], lat: float, lon: float) -> ClimaReferencia:
    """Respuesta documentada de la DMC -> ClimaReferencia. Función pura."""
    if not isinstance(datos, Mapping) or not isinstance(datos.get("datosEstaciones"), Mapping):
        raise ErrorClima("respuesta de la DMC sin datosEstaciones")
    bloque = datos["datosEstaciones"]
    filas = [f for f in bloque.get("datos") or [] if isinstance(f, Mapping) and f.get("momento")]
    if not filas:
        raise ErrorClima("la estación de la DMC no tiene datos recientes")
    filas.sort(key=lambda f: _momento(f["momento"]))
    ultima = filas[-1]
    momento = _momento(ultima["momento"])

    # Lluvia de la última hora: suma de la lluvia minuto a minuto
    lluvias = [numero_con_unidad(f.get("aguaCaidaDelMinuto")) for f in filas
               if _momento(f["momento"]) > momento - timedelta(hours=1)]
    lluvias = [v for v in lluvias if v is not None]

    estacion = bloque.get("estacion") if isinstance(bloque.get("estacion"), Mapping) else {}
    lat_est = numero_con_unidad(estacion.get("latitud"))
    lon_est = numero_con_unidad(estacion.get("longitud"))
    return ClimaReferencia(
        temp_aire_c=numero_con_unidad(ultima.get("temperatura")),
        hum_rel_pct=numero_con_unidad(ultima.get("humedadRelativa")),
        precipitacion_mm=round(sum(lluvias), 1) if lluvias else None,
        radiacion_wm2=numero_con_unidad(ultima.get("radiacionGlobalInst")),
        temp_suelo_c=None,
        hum_suelo_vwc_pct=None,
        et0_mm=None,
        observado_en=momento,
        fuente=FUENTE,
        # Coordenadas de la ESTACIÓN (la DMC no interpola a la ubicación del huerto)
        lat=lat_est if lat_est is not None else float(lat),
        lon=lon_est if lon_est is not None else float(lon),
    )


class ProveedorDMC(ProveedorClima):
    nombre = FUENTE
    titulo = "DMC — Dirección Meteorológica de Chile (requiere registro)"
    nombre_corto = "DMC"
    usa_coordenadas = False          # usa una estación, no la latitud/longitud

    def __init__(self, correo: str = "", token: str = "", estacion: str = "",
                 obtener_json: ObtenerJson = obtener_json_http):
        self.correo = (correo or "").strip()
        self.token = (token or "").strip()
        self.estacion = (estacion or "").strip()
        self._obtener_json = obtener_json

    def aplicar_ajustes(self, ajustes: Mapping[str, Any]) -> None:
        self.estacion = str(ajustes.get("dmc_estacion") or self.estacion).strip()

    def motivo_no_configurado(self) -> Optional[str]:
        faltan = []
        if not self.correo:
            faltan.append("DMC_USER_EMAIL")
        if not self.token:
            faltan.append("DMC_API_TOKEN")
        if faltan:
            return f"falta {' y '.join(faltan)} en el .env del servidor"
        if not self.estacion:
            return "falta el código de la estación (EMA) más cercana"
        return None

    def obtener(self, lat: float, lon: float, timeout: float = TIMEOUT_S) -> ClimaReferencia:
        motivo = self.motivo_no_configurado()
        if motivo:
            raise ProveedorNoConfigurado(motivo)
        datos = self._obtener_json(f"{URL}/{self.estacion}",
                                   {"usuario": self.correo, "token": self.token}, timeout)
        return normalizar(datos, lat, lon)
