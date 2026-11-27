"""Punto de entrada del procesador:  python -m procesador.main

* Sesión MQTT persistente (clean_session=False): si el procesador se
  reinicia, el broker guarda los mensajes QoS 1 que lleguen mientras tanto.
* ACK manual: el mensaje se confirma al broker SOLO después de guardarlo en
  la BD. Si el procesador se cae a mitad de camino, el broker lo reenvía
  (CQ-07: 0 lecturas perdidas). Los reenvíos no duplican gracias a UNIQUE(cama_id, seq).
* Un solo hilo procesa los mensajes en orden (cola), así no hay carreras
  entre la recepción y el ciclo periódico.
"""

from __future__ import annotations

import logging
import queue
import signal
import sys
import time

import paho.mqtt.client as mqtt

from comun.config import Config, cargar_env
from comun.db import ERRORES_CONEXION, conectar_con_reintentos

from .publicador import PublicadorMqtt
from .servicio import Procesador

log = logging.getLogger("procesador")

SUSCRIPCIONES = [
    ("huerto/cama/+/lectura", 1),
    ("huerto/nodo/+/heartbeat", 1),
    ("huerto/nodo/+/conexion", 1),
    ("huerto/central/configuracion", 1),
]
INTERVALO_TICK_S = 60


def crear_cliente(cfg: Config, cola: "queue.Queue[mqtt.MQTTMessage]") -> mqtt.Client:
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="procesador-huerto",
                          clean_session=False, manual_ack=True)
    cliente.username_pw_set(cfg.mqtt_usuario, cfg.mqtt_clave)
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    def al_conectar(c, userdata, flags, codigo, propiedades=None):
        if codigo.is_failure:
            log.error("El broker rechazó la conexión: %s (revisa usuario y clave)", codigo)
            return
        log.info("Conectado al broker %s:%s", cfg.mqtt_host, cfg.mqtt_puerto)
        c.subscribe(SUSCRIPCIONES)

    def al_desconectar(c, userdata, flags, codigo, propiedades=None):
        log.warning("Desconectado del broker (%s). Reintentando…", codigo)

    def al_recibir(c, userdata, mensaje):
        cola.put(mensaje)

    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar
    cliente.on_message = al_recibir
    return cliente


class Servicio:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cola: "queue.Queue[mqtt.MQTTMessage]" = queue.Queue()
        self.detener = False
        self.cliente = crear_cliente(cfg, self.cola)
        self.procesador: Procesador | None = None

    def _reconectar_bd(self) -> None:
        try:
            self.procesador.conn.close()
        except Exception:
            pass
        self.procesador.conn = conectar_con_reintentos(self.cfg)

    def _con_reintentos(self, accion, descripcion: str) -> bool:
        """Ejecuta `accion`. Si se cae la BD, reconecta y reintenta (sin perder
        el mensaje). Si es un error del programa, lo registra y sigue."""
        espera = 1.0
        while not self.detener:
            try:
                accion()
                return True
            except ERRORES_CONEXION as e:
                log.warning("BD no disponible (%s) en %s. Reintento en %.0f s.", e, descripcion, espera)
                time.sleep(espera)
                espera = min(espera * 2, 30)
                self._reconectar_bd()
            except Exception:
                log.exception("Error inesperado en %s; se descarta.", descripcion)
                try:
                    self.procesador.conn.rollback()
                except Exception:
                    self._reconectar_bd()
                return False
        return False

    def ejecutar(self) -> None:
        conn = conectar_con_reintentos(self.cfg)
        self.procesador = Procesador(conn, self.cfg, PublicadorMqtt(self.cliente))

        self.cliente.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_puerto, keepalive=30)
        self.cliente.loop_start()
        self._con_reintentos(self.procesador.inicializar, "inicialización")
        log.info("Procesador listo.")

        proximo_tick = time.monotonic() + INTERVALO_TICK_S
        while not self.detener:
            try:
                mensaje = self.cola.get(timeout=1)
            except queue.Empty:
                mensaje = None
            if mensaje is not None:
                self._con_reintentos(
                    lambda: self.procesador.procesar_mensaje(mensaje.topic, mensaje.payload,
                                                             bool(mensaje.retain)),
                    f"mensaje {mensaje.topic}")
                if mensaje.qos > 0:
                    self.cliente.ack(mensaje.mid, mensaje.qos)
            if time.monotonic() >= proximo_tick:
                self._con_reintentos(self.procesador.tick, "ciclo periódico")
                proximo_tick = time.monotonic() + INTERVALO_TICK_S

        self.cliente.loop_stop()
        self.cliente.disconnect()
        log.info("Procesador detenido.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cargar_env()
    servicio = Servicio(Config.desde_entorno())

    def detener(*_):
        log.info("Señal de término recibida.")
        servicio.detener = True

    signal.signal(signal.SIGTERM, detener)
    signal.signal(signal.SIGINT, detener)
    servicio.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
