"""Orquestación: mensaje MQTT -> validación -> BD -> reglas -> estado -> publicación.

Un mensaje = una transacción. Se hace commit ANTES de publicar, para que el
tablero nunca muestre algo que no quedó guardado.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pymysql

from comun import mensajes
from comun.config import Config
from comun.db import ahora_utc
from comun.rangos import rango_efectivo

from . import repositorio as repo
from .publicador import TOPICO_ALERTAS, Publicador, iso, topico_estado, topico_tarjeta
from .reglas import ABRIR, ACTUALIZAR, RESOLVER, Decision
from .reglas.estado import AlertaResumen, Estado, calcular_estado, sensores_sin_datos
from .reglas.luz import (DiaLuz, calcular_luz, evaluar_poca_luz, fecha_local, limites_dia,
                         limites_sol)
from .reglas.suelo import evaluar_suelo
from .reglas.temperatura import evaluar_temperatura, inicio_racha_sobre_maximo
from .sincronizador import Sincronizador, SincronizadorNulo
from .validacion import MensajeInvalido, interpretar, validar, valores_anteriores_desde_fila

log = logging.getLogger(__name__)

_ID = r"([a-z0-9-]{1,40})"
TOPICO_LECTURA = re.compile(rf"^huerto/cama/{_ID}/lectura$")
TOPICO_NODO = re.compile(rf"^huerto/nodo/{_ID}/(heartbeat|conexion)$")
# La web avisa aquí cuando el docente cambia la configuración de una cama
TOPICO_CONFIGURACION = "huerto/central/configuracion"

SENSOR_SIN_DATOS = "sensor_sin_datos"
DIAS_MAX_CIERRE = 30          # no recalcula más atrás que esto


@dataclass
class Resultado:
    """Qué pasó con un mensaje (lo usan los logs y los tests)."""
    estado: str        # guardada | atrasada | invalida_guardada | duplicada | seq_reiniciado | invalida | inactiva
    lectura_id: Optional[int] = None
    decisiones: list[Decision] = field(default_factory=list)
    alertas_nuevas: list[int] = field(default_factory=list)


class Procesador:
    def __init__(self, conn, cfg: Config, publicador: Publicador,
                 reloj: Callable[[], datetime] = ahora_utc,
                 sincronizador: Optional[Sincronizador] = None):
        self.conn = conn
        self.cfg = cfg
        self.publicador = publicador
        self.reloj = reloj
        self.sincronizador = sincronizador or SincronizadorNulo()
        self.zona = ZoneInfo(cfg.zona_horaria)
        # Último estado publicado por cama: cama_id -> (color, mensaje, desde)
        self.estados: dict[int, tuple[str, str, Optional[datetime]]] = {}

    # ------------------------------------------------------------------
    # Arranque
    # ------------------------------------------------------------------

    def inicializar(self) -> None:
        """Recupera los estados guardados y vuelve a publicar todo (retenido)."""
        for cama_id, fila in repo.ultimos_estados(self.conn).items():
            self.estados[cama_id] = (fila["estado_nuevo"], fila["mensaje"], fila["ocurrido_en"])
        self.conn.commit()
        ahora = self.reloj()
        for cama in repo.camas_activas(self.conn):
            self.cerrar_dias_luz(cama, ahora)
            estado, _, _ = self.actualizar_estado(cama, ahora, forzar_publicacion=True)
            self.publicar_tarjeta(cama, ahora)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Entrada de mensajes
    # ------------------------------------------------------------------

    def procesar_mensaje(self, topico: str, payload: bytes, retenido: bool = False) -> Optional[Resultado]:
        if TOPICO_LECTURA.match(topico):
            return self.procesar_lectura(topico, payload)
        if topico == TOPICO_CONFIGURACION:
            try:
                cama_id = int(json.loads(payload)["cama_id"])
            except (ValueError, KeyError, TypeError):
                log.warning("Aviso de configuración no válido: %r", payload[:100])
                return None
            self.reevaluar_cama(cama_id)
            return None
        m = TOPICO_NODO.match(topico)
        if m and m.group(2) == "heartbeat":
            self.procesar_heartbeat(m.group(1), payload)
        elif m and m.group(2) == "conexion" and not retenido:
            # Un "offline" retenido es historia vieja: solo se registran los cambios en vivo
            self.procesar_conexion(m.group(1), payload)
        return None

    def procesar_lectura(self, topico: str, payload: bytes) -> Resultado:
        ahora = self.reloj()
        m = TOPICO_LECTURA.match(topico)
        if not m:
            log.warning("Tópico de lectura no reconocido: %s", topico)
            return Resultado("invalida")
        nodo_id = m.group(1)

        try:
            datos = interpretar(nodo_id, payload)
        except MensajeInvalido as e:
            muestra = payload[:200] if isinstance(payload, (bytes, str)) else payload
            repo.registrar_incidencia(self.conn, nodo_id, "mensaje_invalido",
                                      f"{e}. Mensaje: {muestra!r}", ahora)
            self.conn.commit()
            log.warning("[%s] mensaje descartado: %s", nodo_id, e)
            return Resultado("invalida")
        if datos.nodo_id_mensaje and datos.nodo_id_mensaje != nodo_id:
            log.warning("[%s] el JSON dice nodo_id=%r; se usa el del tópico",
                        nodo_id, datos.nodo_id_mensaje)

        cama = repo.obtener_o_crear_cama(self.conn, nodo_id)
        fila_anterior = repo.lectura_anterior(self.conn, cama["id"], datos.medido_en)
        anterior = valores_anteriores_desde_fila(fila_anterior) if fila_anterior else None
        lectura = validar(datos, anterior, ahora, self.cfg)

        try:
            lectura_id = repo.insertar_lectura(self.conn, cama["id"], lectura, ahora)
        except pymysql.err.IntegrityError:
            return self._seq_repetido(cama, lectura, ahora)

        # HU-01: si ya existe una lectura válida medida después, esta es
        # atrasada: se guarda en el historial pero no cambia el estado actual.
        es_actual = lectura.valida and not repo.existe_valida_posterior(
            self.conn, cama["id"], lectura.medido_en, lectura_id)

        decisiones: list[Decision] = []
        nuevas: list[int] = []
        if es_actual and cama["activa"]:
            decisiones = self._evaluar_alertas(cama, lectura)
            nuevas = self._aplicar(cama["id"], decisiones, lectura.medido_en, ahora)
        self.conn.commit()

        if not lectura.valida:
            log.info("[%s] seq=%s guardada como inválida: %s", nodo_id, lectura.seq, lectura.motivo)
        if not cama["activa"]:
            return Resultado("inactiva", lectura_id)

        _, cambio_estado, cambio_alertas = self.actualizar_estado(cama, ahora,
                                                                  abrir_alertas_sensor=False)
        if es_actual or cambio_estado:
            self.publicar_tarjeta(cama, ahora, nuevas)
        if decisiones or cambio_alertas:
            self.publicador.publicar(TOPICO_ALERTAS, {"cama_id": cama["id"], "actualizado_en": iso(ahora)})

        estado = "guardada" if es_actual else ("atrasada" if lectura.valida else "invalida_guardada")
        return Resultado(estado, lectura_id, decisiones, nuevas)

    def _seq_repetido(self, cama: dict, lectura, ahora: datetime) -> Resultado:
        self.conn.rollback()
        existente = repo.lectura_por_seq(self.conn, cama["id"], lectura.seq)
        if existente and existente["medido_en"] == lectura.medido_en:
            # Reenvío normal desde el buffer (se perdió el PUBACK): se ignora.
            return Resultado("duplicada", existente["id"])
        detalle = (f"Llegó seq={lectura.seq} medida el {iso(lectura.medido_en)}, pero ese seq ya "
                   f"existe con hora {iso(existente['medido_en']) if existente else '?'}. "
                   "Probablemente se borró la memoria del nodo y su contador volvió a cero: "
                   "esas lecturas se están descartando.")
        if repo.registrar_incidencia(self.conn, cama["nodo_id"], "seq_reiniciado", detalle, ahora):
            log.error("[%s] %s", cama["nodo_id"], detalle)
        self.conn.commit()
        return Resultado("seq_reiniciado")

    def procesar_heartbeat(self, nodo_id: str, payload: bytes) -> None:
        try:
            datos = json.loads(payload)
            if not isinstance(datos, dict):
                raise ValueError
        except ValueError:
            log.warning("[%s] heartbeat no válido: %r", nodo_id, payload[:100])
            return
        repo.registrar_heartbeat(self.conn, nodo_id, self.reloj(), datos)
        self.conn.commit()

    def procesar_conexion(self, nodo_id: str, payload: bytes) -> None:
        estado = payload.decode("utf-8", "replace").strip().lower() if isinstance(payload, bytes) else str(payload)
        if estado not in ("online", "offline"):
            log.warning("[%s] estado de conexión desconocido: %r", nodo_id, estado)
            return
        repo.registrar_conexion(self.conn, nodo_id, estado, self.reloj())
        self.conn.commit()
        log.info("[%s] %s", nodo_id, "conectado" if estado == "online" else "desconectado")

    def reevaluar_cama(self, cama_id: int) -> None:
        """El docente cambió cultivo, rangos o nombre: se vuelve a evaluar la
        cama con su lectura actual y se publica el resultado al instante."""
        ahora = self.reloj()
        cama = repo.obtener_cama(self.conn, cama_id)
        if cama is None:
            return
        if not cama["activa"]:
            # Cama desactivada: se cierran sus alertas y desaparece del tablero
            abiertas = repo.alertas_abiertas(self.conn, cama_id)
            self._aplicar(cama_id, [Decision(RESOLVER, a["tipo"], a["variable"]) for a in abiertas],
                          ahora, ahora)
            self.conn.commit()
            self.estados.pop(cama_id, None)
            self.publicador.publicar(TOPICO_ALERTAS, {"cama_id": cama_id, "actualizado_en": iso(ahora)})
            return

        nuevas: list[int] = []
        actual = repo.lectura_actual(self.conn, cama_id)
        if actual is not None:
            lectura = SimpleNamespace(
                medido_en=actual["medido_en"],
                suelo_prom=None if actual["suelo_prom"] is None else float(actual["suelo_prom"]),
                temp=None if actual["temp"] is None else float(actual["temp"]))
            nuevas = self._aplicar(cama_id, self._evaluar_alertas(cama, lectura), ahora, ahora)
        self.conn.commit()
        self.cerrar_dias_luz(cama, ahora)
        self.actualizar_estado(cama, ahora, forzar_publicacion=True)
        self.publicar_tarjeta(cama, ahora, nuevas)
        self.publicador.publicar(TOPICO_ALERTAS, {"cama_id": cama_id, "actualizado_en": iso(ahora)})
        log.info("[%s] configuración actualizada", cama["nodo_id"])

    # ------------------------------------------------------------------
    # Alertas de suelo y temperatura (al recibir cada lectura)
    # ------------------------------------------------------------------

    def _evaluar_alertas(self, cama: dict, lectura) -> list[Decision]:
        rango = rango_efectivo(cama)
        abiertas_filas = repo.alertas_abiertas(self.conn, cama["id"])
        abiertas = {a["tipo"] for a in abiertas_filas}
        if not rango.configurado:
            # «Configura un cultivo…»: no hay alertas (las de sensor las cierra actualizar_estado)
            return [Decision(RESOLVER, a["tipo"], a["variable"]) for a in abiertas_filas
                    if a["tipo"] != SENSOR_SIN_DATOS]

        decisiones: list[Decision] = []
        if lectura.suelo_prom is not None:
            decisiones += evaluar_suelo(cama["nombre"], lectura.suelo_prom, rango, abiertas,
                                        self.cfg.histeresis_suelo)
        if lectura.temp is not None:
            inicio_racha = None
            if rango.temp_max is not None and lectura.temp > rango.temp_max:
                ventana = timedelta(minutes=self.cfg.calor_minutos_sostenido + 60)
                temps = repo.temperaturas_desc(self.conn, cama["id"],
                                               lectura.medido_en - ventana, lectura.medido_en)
                inicio_racha = inicio_racha_sobre_maximo(temps, rango.temp_max,
                                                         self.cfg.max_hueco_racha_min)
            decisiones += evaluar_temperatura(
                cama["nombre"], lectura.temp, lectura.medido_en, rango, abiertas,
                self.cfg.histeresis_temp, inicio_racha, self.cfg.calor_minutos_sostenido)
        return decisiones

    def _aplicar(self, cama_id: int, decisiones: list[Decision], momento: datetime,
                 ahora: datetime) -> list[int]:
        """Aplica las decisiones en la BD. `momento` = hora de la medición que
        las provocó. Devuelve los id de las alertas NUEVAS (las que avisan)."""
        if not decisiones:
            return []
        abiertas = {(a["tipo"], a["variable"]): a for a in repo.alertas_abiertas(self.conn, cama_id)}
        nuevas: list[int] = []
        for d in decisiones:
            existente = abiertas.get((d.tipo, d.variable))
            if d.accion == ABRIR and existente is None:
                try:
                    alerta_id = repo.abrir_alerta(self.conn, cama_id, d.tipo, d.variable, d.mensaje,
                                                  d.valor, d.iniciada_en or momento, momento)
                except pymysql.err.IntegrityError:
                    continue          # otra ya la abrió: la BD evita el duplicado
                repo.registrar_evento_alerta(self.conn, alerta_id, "apertura", momento, ahora)
                nuevas.append(alerta_id)
                log.info("[cama %s] ALERTA: %s", cama_id, d.mensaje)
            elif d.accion in (ABRIR, ACTUALIZAR) and existente is not None:
                # Sigue fuera de rango: se actualiza valor y hora, SIN aviso nuevo
                repo.actualizar_alerta(self.conn, existente["id"], d.valor, d.mensaje, momento)
            elif d.accion == RESOLVER and existente is not None:
                repo.resolver_alerta(self.conn, existente["id"], d.valor, momento)
                repo.registrar_evento_alerta(self.conn, existente["id"], "resolucion", momento, ahora)
                log.info("[cama %s] resuelta: %s", cama_id, existente["mensaje"])
        return nuevas

    # ------------------------------------------------------------------
    # Estado de la cama (HU-05) y alertas de sensor sin datos
    # ------------------------------------------------------------------

    def actualizar_estado(self, cama: dict, ahora: datetime, forzar_publicacion: bool = False,
                          abrir_alertas_sensor: bool = True) -> tuple[Estado, bool, bool]:
        """Devuelve (estado, ¿cambió el estado?, ¿cambiaron las alertas?).

        Las alertas `sensor_sin_datos` solo se ABREN desde el ciclo periódico
        (abrir_alertas_sensor=True). Al recibir lecturas solo se resuelven:
        si no, al reprocesar un buffer atrasado de varias horas se abrirían y
        cerrarían alertas falsas en segundos. El estado gris sí es inmediato.
        """
        rango = rango_efectivo(cama)
        primera = repo.primera_lectura(self.conn, cama["id"])
        ultimas = (repo.ultima_valida_por_sensor(self.conn, cama["id"], ahora - timedelta(days=7))
                   if primera else {})
        sin_datos = sensores_sin_datos(ultimas, primera, ahora, self.cfg.minutos_sin_datos_gris)

        abiertas = repo.alertas_abiertas(self.conn, cama["id"])
        decisiones: list[Decision] = []
        if rango.configurado:
            de_sensor = {a["variable"] for a in abiertas if a["tipo"] == SENSOR_SIN_DATOS}
            for sensor in sin_datos:
                if sensor not in de_sensor and abrir_alertas_sensor:
                    decisiones.append(Decision(ABRIR, SENSOR_SIN_DATOS, sensor, None,
                                               mensajes.sensores_sin_conexion([sensor])))
            for sensor in de_sensor - set(sin_datos):
                decisiones.append(Decision(RESOLVER, SENSOR_SIN_DATOS, sensor))
        else:
            # Sin cultivo ni rangos no hay alertas de ningún tipo
            decisiones = [Decision(RESOLVER, a["tipo"], a["variable"]) for a in abiertas]
        if decisiones:
            self._aplicar(cama["id"], decisiones, ahora, ahora)
            abiertas = repo.alertas_abiertas(self.conn, cama["id"])

        estado = calcular_estado(
            rango.configurado, primera is not None, sin_datos,
            [AlertaResumen(a["tipo"], a["variable"],
                           None if a["valor_actual"] is None else float(a["valor_actual"]))
             for a in abiertas],
            rango)

        anterior = self.estados.get(cama["id"])
        cambio = anterior is None or (anterior[0], anterior[1]) != (estado.color, estado.mensaje)
        desde = anterior[2] if anterior and not cambio else ahora
        if cambio:
            ultima_valida = None
            if sin_datos:
                ultima_valida = min((ultimas.get(s) or primera) for s in sin_datos)
            repo.registrar_cambio_estado(self.conn, cama["id"], anterior[0] if anterior else None,
                                         estado.color, estado.mensaje, ahora, ultima_valida)
            log.info("[%s] estado: %s — %s", cama["nodo_id"], estado.color, estado.mensaje)
        self.conn.commit()

        if cambio or forzar_publicacion:
            self.estados[cama["id"]] = (estado.color, estado.mensaje, desde)
            # Retenido: el LED del nodo lo recibe apenas se conecta
            self.publicador.publicar(topico_estado(cama["nodo_id"]),
                                     {"color": estado.color, "mensaje": estado.mensaje,
                                      "desde": iso(desde)}, retener=True)
        return estado, cambio, bool(decisiones)

    # ------------------------------------------------------------------
    # Luz (HU-04)
    # ------------------------------------------------------------------

    def _resumen_luz(self, cama_id: int, fecha, hasta: Optional[datetime] = None):
        inicio, fin = limites_dia(fecha, self.zona)
        sol_inicio, sol_fin = limites_sol(fecha, self.zona, self.cfg.hora_inicio_sol,
                                          self.cfg.hora_fin_sol)
        if hasta is not None:
            fin = min(fin, hasta)
        lecturas = repo.lux_asc(self.conn, cama_id, inicio, fin)
        return calcular_luz(lecturas, inicio, fin, sol_inicio, sol_fin,
                            self.cfg.umbral_luz_lux, self.cfg.max_hueco_luz_min)

    def horas_luz_hoy(self, cama_id: int, ahora: datetime) -> Optional[float]:
        """Horas de luz directa acumuladas hoy (None = «Sin datos de luz hoy»)."""
        # +1 s para incluir una lectura medida justo "ahora"
        return self._resumen_luz(cama_id, fecha_local(ahora, self.zona),
                                 ahora + timedelta(seconds=1)).horas_luz

    def cerrar_dias_luz(self, cama: dict, ahora: datetime) -> bool:
        """Guarda en luz_diaria los días terminados y evalúa «poca luz».

        Un día se cierra `gracia_cierre_dia_min` después de la medianoche,
        para esperar las lecturas atrasadas del buffer de los nodos.
        Devuelve True si cambió alguna alerta.
        """
        hoy = fecha_local(ahora, self.zona)
        inicio_hoy, _ = limites_dia(hoy, self.zona)
        dias_atras = 1 if ahora >= inicio_hoy + timedelta(minutes=self.cfg.gracia_cierre_dia_min) else 2
        ultimo_cerrable = hoy - timedelta(days=dias_atras)

        ultima = repo.ultima_fecha_luz(self.conn, cama["id"])
        if ultima is None:
            primera = repo.primera_lectura(self.conn, cama["id"])
            if primera is None:
                return False
            desde = fecha_local(primera, self.zona)
        else:
            desde = ultima + timedelta(days=1)
        desde = max(desde, ultimo_cerrable - timedelta(days=DIAS_MAX_CIERRE))

        dia_cerrado = False
        fecha = desde
        while fecha <= ultimo_cerrable:
            r = self._resumen_luz(cama["id"], fecha)
            repo.guardar_luz_diaria(self.conn, cama["id"], fecha, r.horas_luz,
                                    r.minutos_con_datos, r.minutos_con_datos_sol)
            log.info("[%s] luz del %s: %s", cama["nodo_id"], fecha,
                     "sin datos" if r.horas_luz is None else f"{r.horas_luz} h")
            dia_cerrado = True
            fecha += timedelta(days=1)

        # Se evalúa en cada ciclo (consulta pequeña) para reaccionar también a
        # cambios de cultivo; solo se ACTUALIZA la alerta cuando se cierra un día.
        rango = rango_efectivo(cama)
        abiertas = {a["tipo"] for a in repo.alertas_abiertas(self.conn, cama["id"])}
        filas = repo.dias_luz_desc(self.conn, cama["id"], self.cfg.dias_poca_luz + 1)
        dias = [DiaLuz(f["fecha"], None if f["horas_luz"] is None else float(f["horas_luz"]),
                       float(f["minutos_con_datos_sol"])) for f in filas]
        minutos_sol = (self.cfg.hora_fin_sol - self.cfg.hora_inicio_sol) * 60
        decisiones = [] if not rango.configurado else evaluar_poca_luz(
            cama["nombre"], rango, dias, abiertas, self.cfg.dias_poca_luz, minutos_sol,
            self.cfg.cobertura_minima_luz, repo.cultivos_de_sombra(self.conn))
        if not dia_cerrado:
            decisiones = [d for d in decisiones if d.accion != ACTUALIZAR]
        self._aplicar(cama["id"], decisiones, ahora, ahora)
        self.conn.commit()
        return bool(decisiones)

    # ------------------------------------------------------------------
    # Tarjeta del tablero
    # ------------------------------------------------------------------

    def tarjeta(self, cama: dict, ahora: datetime, alertas_nuevas=()) -> dict:
        actual = repo.lectura_actual(self.conn, cama["id"])
        horas = self.horas_luz_hoy(cama["id"], ahora)
        color, mensaje, desde = self.estados.get(cama["id"], ("gris", mensajes.SIN_LECTURAS, None))
        lectura = None
        if actual:
            lectura = {
                "seq": actual["seq"],
                "medido_en": iso(actual["medido_en"]),
                "suelo_prom": actual["suelo_prom"],
                "suelo": actual["suelo_detalle"],
                "temp": actual["temp"],
                "hum_aire": actual["hum_aire"],
                "lux": actual["lux"],
            }
        self.conn.commit()
        return {
            "cama_id": cama["id"],
            "nodo_id": cama["nodo_id"],
            "nombre": cama["nombre"],
            "cultivo": cama.get("cultivo_nombre"),
            "color": color,
            "mensaje": mensaje,
            "estado_desde": iso(desde),
            "lectura": lectura,
            "texto_lectura": None if actual else mensajes.SIN_LECTURAS,
            "horas_luz_hoy": horas,
            "texto_luz": mensajes.horas_luz(horas),
            "alertas_nuevas": list(alertas_nuevas),
            "procesado_en": iso(ahora),
        }

    def publicar_tarjeta(self, cama: dict, ahora: datetime, alertas_nuevas=()) -> None:
        self.publicador.publicar(topico_tarjeta(cama["nodo_id"]),
                                 self.tarjeta(cama, ahora, alertas_nuevas), retener=True)

    # ------------------------------------------------------------------
    # Ciclo periódico (cada minuto)
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Detecta sensores sin datos (gris), cierra días de luz y sincroniza.

        Es necesario porque un sensor muerto no envía mensajes que gatillen
        la evaluación.
        """
        ahora = self.reloj()
        for cama in repo.camas_activas(self.conn):
            cambio_luz = self.cerrar_dias_luz(cama, ahora)
            _, cambio_estado, cambio_alertas = self.actualizar_estado(cama, ahora)
            if cambio_estado or cambio_luz or cambio_alertas:
                self.publicar_tarjeta(cama, ahora)
            if cambio_luz or cambio_alertas:
                self.publicador.publicar(TOPICO_ALERTAS, {"cama_id": cama["id"],
                                                          "actualizado_en": iso(ahora)})
        self.conn.commit()
        self.sincronizador.sincronizar(self.conn)
