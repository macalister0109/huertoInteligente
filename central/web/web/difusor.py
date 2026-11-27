"""Puente MQTT -> navegadores (Server-Sent Events).

Un solo cliente MQTT por proceso recibe las tarjetas que publica el
procesador y las reparte a todos los navegadores conectados. Guarda la
última tarjeta de cada cama (vienen retenidas), así una pantalla recién
abierta se dibuja al instante.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from typing import Optional

log = logging.getLogger(__name__)

PREFIJO_TARJETA = "huerto/tablero/cama/"
TOPICO_ALERTAS = "huerto/tablero/alertas"
TOPICO_CONFIGURACION = "huerto/central/configuracion"
TOPICO_LECTURA_API = "huerto/central/lectura"
MAX_EVENTOS_EN_COLA = 200


class Difusor:
    def __init__(self):
        self._lock = threading.Lock()
        self._colas: set[queue.Queue] = set()
        self.tarjetas: dict[str, dict] = {}       # nodo_id -> última tarjeta
        self.conexiones: dict[str, str] = {}      # nodo_id -> online | offline
        self.conectado = False                    # ¿conectado al broker?

    # --- Navegadores ---
    def suscribir(self) -> queue.Queue:
        cola: queue.Queue = queue.Queue(maxsize=MAX_EVENTOS_EN_COLA)
        with self._lock:
            self._colas.add(cola)
        return cola

    def desuscribir(self, cola: queue.Queue) -> None:
        with self._lock:
            self._colas.discard(cola)

    @property
    def clientes(self) -> int:
        with self._lock:
            return len(self._colas)

    def emitir(self, tipo: str, datos: dict) -> None:
        texto = json.dumps(datos, ensure_ascii=False)
        with self._lock:
            colas = list(self._colas)
        for cola in colas:
            try:
                cola.put_nowait((tipo, texto))
            except queue.Full:
                # Navegador demasiado lento: pierde eventos, pero se resincroniza
                # solo con su recarga periódica de 60 s.
                pass

    # --- Mensajes MQTT ---
    def recibir(self, topico: str, payload: bytes) -> None:
        if topico.startswith(PREFIJO_TARJETA):
            nodo_id = topico[len(PREFIJO_TARJETA):]
            if not payload:
                self.tarjetas.pop(nodo_id, None)     # retenido borrado
                return
            try:
                tarjeta = json.loads(payload)
            except ValueError:
                log.warning("Tarjeta no válida en %s", topico)
                return
            self.tarjetas[nodo_id] = tarjeta
            self.emitir("tarjeta", tarjeta)
        elif topico == TOPICO_ALERTAS:
            self.emitir("alertas", {})
        elif topico.startswith("huerto/nodo/") and topico.endswith("/conexion"):
            nodo_id = topico.split("/")[2]
            estado = payload.decode("utf-8", "replace").strip()
            self.conexiones[nodo_id] = estado
            self.emitir("conexion", {"nodo_id": nodo_id, "estado": estado})

    def _cambiar_conexion(self, conectado: bool) -> None:
        self.conectado = conectado
        self.emitir("central", {"conectado": conectado})

    # --- Hacia el procesador ---
    def avisar_configuracion(self, cama_id: int) -> None:
        raise NotImplementedError

    def avisar_lectura(self, lectura_id: int) -> None:
        """La API guardó una lectura: el procesador evalúa alertas y estado."""
        raise NotImplementedError


class DifusorMqtt(Difusor):
    def __init__(self, host: str, puerto: int, usuario: str, clave: str):
        super().__init__()
        import paho.mqtt.client as mqtt

        self.host, self.puerto = host, puerto
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=f"web-{uuid.uuid4().hex[:8]}", clean_session=True)
        self.cliente.username_pw_set(usuario, clave)
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=30)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_disconnect = self._al_desconectar
        self.cliente.on_message = lambda c, u, m: self.recibir(m.topic, m.payload)

    def iniciar(self) -> "DifusorMqtt":
        self.cliente.connect_async(self.host, self.puerto, keepalive=30)
        self.cliente.loop_start()
        return self

    def _al_conectar(self, cliente, userdata, flags, codigo, propiedades=None):
        if codigo.is_failure:
            log.error("El broker rechazó a la web: %s (revisa MQTT_USER_WEB / MQTT_PASS_WEB)", codigo)
            return
        cliente.subscribe([("huerto/tablero/#", 1), ("huerto/nodo/+/conexion", 1)])
        log.info("Web conectada al broker %s:%s", self.host, self.puerto)
        self._cambiar_conexion(True)

    def _al_desconectar(self, cliente, userdata, flags, codigo, propiedades=None):
        log.warning("Web desconectada del broker (%s)", codigo)
        self._cambiar_conexion(False)

    def avisar_configuracion(self, cama_id: int) -> None:
        self.cliente.publish(TOPICO_CONFIGURACION, json.dumps({"cama_id": cama_id}), qos=1)

    def avisar_lectura(self, lectura_id: int) -> None:
        # QoS 1: si el broker está caído, paho lo reintenta al reconectar.
        # Aunque se perdiera, la lectura ya quedó guardada en la BD.
        self.cliente.publish(TOPICO_LECTURA_API, json.dumps({"lectura_id": lectura_id}), qos=1)


class DifusorMemoria(Difusor):
    """Para los tests: sin broker."""

    def __init__(self):
        super().__init__()
        self.conectado = True
        self.avisos_configuracion: list[int] = []
        self.avisos_lectura: list[int] = []

    def avisar_configuracion(self, cama_id: int) -> None:
        self.avisos_configuracion.append(cama_id)

    def avisar_lectura(self, lectura_id: int) -> None:
        self.avisos_lectura.append(lectura_id)
