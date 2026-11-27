"""Configuración leída desde variables de entorno (central/.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Optional


def _a_bool(valor: str) -> bool:
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# Nombre de cada campo -> variable de entorno
_VARIABLES = {
    "db_host": "DB_HOST",
    "db_puerto": "DB_PORT",
    "db_usuario": "MARIADB_USER",
    "db_clave": "MARIADB_PASSWORD",
    "db_nombre": "MARIADB_DATABASE",
    "mqtt_host": "MQTT_HOST",
    "mqtt_puerto": "MQTT_PORT",
    "mqtt_usuario": "MQTT_USER_PROCESADOR",
    "mqtt_clave": "MQTT_PASS_PROCESADOR",
    "zona_horaria": "ZONA_HORARIA",
    "histeresis_suelo": "HISTERESIS_SUELO",
    "histeresis_temp": "HISTERESIS_TEMP",
    "calor_minutos_sostenido": "CALOR_MINUTOS_SOSTENIDO",
    "max_hueco_racha_min": "MAX_HUECO_RACHA_MIN",
    "umbral_luz_lux": "UMBRAL_LUZ_LUX",
    "dias_poca_luz": "DIAS_POCA_LUZ",
    "hora_inicio_sol": "HORA_INICIO_SOL",
    "hora_fin_sol": "HORA_FIN_SOL",
    "cobertura_minima_luz": "COBERTURA_MINIMA_LUZ",
    "max_hueco_luz_min": "MAX_HUECO_LUZ_MIN",
    "gracia_cierre_dia_min": "GRACIA_CIERRE_DIA_MIN",
    "minutos_sin_datos_gris": "MINUTOS_SIN_DATOS_GRIS",
    "salto_max_bajada_suelo": "SALTO_MAX_BAJADA_SUELO",
    "salto_max_temp": "SALTO_MAX_TEMP",
    "salto_max_hum_aire": "SALTO_MAX_HUM_AIRE",
    "max_adelanto_reloj_min": "MAX_ADELANTO_RELOJ_MIN",
    "temp_min_fisico": "TEMP_MIN_FISICO",
    "temp_max_fisico": "TEMP_MAX_FISICO",
    "hum_aire_min_fisico": "HUM_AIRE_MIN_FISICO",
    "hum_aire_max_fisico": "HUM_AIRE_MAX_FISICO",
    "tendencia_activa": "TENDENCIA_ACTIVA",
    "sensores_requeridos": "SENSORES_REQUERIDOS",
}


@dataclass(frozen=True)
class Config:
    # Base de datos
    db_host: str = "localhost"
    db_puerto: int = 3306
    db_usuario: str = "huerto"
    db_clave: str = ""
    db_nombre: str = "huerto"
    # MQTT
    mqtt_host: str = "localhost"
    mqtt_puerto: int = 1883
    mqtt_usuario: str = "procesador"
    mqtt_clave: str = ""
    # Reglas
    zona_horaria: str = "America/Santiago"
    histeresis_suelo: float = 2.0
    histeresis_temp: float = 1.0
    calor_minutos_sostenido: float = 30.0
    max_hueco_racha_min: float = 10.0       # un hueco mayor corta la racha de calor
    umbral_luz_lux: float = 25000.0
    dias_poca_luz: int = 3
    hora_inicio_sol: int = 6
    hora_fin_sol: int = 21
    cobertura_minima_luz: float = 0.75
    max_hueco_luz_min: float = 10.0         # una lectura de luz "cubre" como máximo 10 min
    gracia_cierre_dia_min: int = 120        # espera lecturas atrasadas antes de cerrar el día
    minutos_sin_datos_gris: float = 120.0
    salto_max_bajada_suelo: float = 10.0    # puntos por minuto
    salto_max_temp: float = 3.0             # °C por minuto
    salto_max_hum_aire: float = 15.0        # puntos por minuto
    max_adelanto_reloj_min: float = 5.0     # medido_en más adelantado que esto = hora imposible
    # Rango físico del sensor de aire. Por defecto el DHT11 del prototipo 1:
    # 0 a 50 °C (no mide bajo cero) y humedad 0 a 100 %.
    temp_min_fisico: float = 0.0
    temp_max_fisico: float = 50.0
    hum_aire_min_fisico: float = 0.0
    hum_aire_max_fisico: float = 100.0
    tendencia_activa: bool = False
    # Sensores que, si pasan MINUTOS_SIN_DATOS_GRIS sin datos válidos, ponen la
    # cama en gris (HU-05). El prototipo 1 no tiene sensor de luz: no cuenta.
    # Cuando se agregue (prototipo 2): SENSORES_REQUERIDOS=suelo,temperatura,luz
    sensores_requeridos: str = "suelo,temperatura"

    @property
    def lista_sensores_requeridos(self) -> tuple[str, ...]:
        return tuple(s.strip().lower() for s in self.sensores_requeridos.split(",") if s.strip())

    @classmethod
    def desde_entorno(cls, entorno: Optional[Mapping[str, str]] = None) -> "Config":
        entorno = os.environ if entorno is None else entorno
        valores = {}
        for campo in fields(cls):
            texto = entorno.get(_VARIABLES[campo.name])
            if texto is None or texto == "":
                continue
            if campo.type in ("bool", bool):
                valores[campo.name] = _a_bool(texto)
            elif campo.type in ("int", int):
                valores[campo.name] = int(texto)
            elif campo.type in ("float", float):
                valores[campo.name] = float(texto.replace(",", "."))
            else:
                valores[campo.name] = texto
        return cls(**valores)


def cargar_env(ruta: Optional[Path] = None) -> None:
    """Carga central/.env si existe (útil al correr fuera de Docker)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    ruta = ruta or Path(__file__).resolve().parent.parent / ".env"
    if ruta.is_file():
        load_dotenv(ruta, override=False)
