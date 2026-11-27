#!/usr/bin/env python3
"""
Simulador de nodos ESP32 del Huerto Inteligente (iteración 1, MQTT).

Publica lecturas con el mismo tópico, JSON y QoS que el firmware, para probar
el procesador y el tablero SIN placa. Incluye los escenarios de la
especificación: suelo seco, encharcado, helada, calor sostenido y breve,
poca luz por 3 días, sensor que deja de enviar, lecturas atrasadas y reenvío
del buffer con duplicados.

Instalación:   pip install -r tools/requirements.txt
Credenciales:  usa el usuario "simulador" de central/.env (se lee solo).

Ejemplos:
    python tools/simular_nodos.py --listar
    python tools/simular_nodos.py --escenario seco --seco          # solo muestra el JSON
    python tools/simular_nodos.py --escenario poca_luz --nodos cama-b
    python tools/simular_nodos.py --nodos cama-a,cama-b --tiempo-real

Nota: en el simulador `seq` = segundos Unix de `medido_en` (único y creciente).
El nodo real usa un contador persistente en su memoria flash.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo
    ZONA_LOCAL = ZoneInfo("America/Santiago")
except Exception:  # sin base de zonas horarias (Windows sin tzdata)
    ZONA_LOCAL = timezone(timedelta(hours=-3))

RAIZ = Path(__file__).resolve().parent.parent
ENV_CENTRAL = RAIZ / "central" / ".env"


# ---------------------------------------------------------------------------
# Curvas base
# ---------------------------------------------------------------------------

def hora_local(t: datetime) -> float:
    """Hora del día en Chile (0–24 con decimales)."""
    local = t.astimezone(ZONA_LOCAL)
    return local.hour + local.minute / 60 + local.second / 3600


def curva_luz(t: datetime, pico_lux: float) -> float:
    """Campana de luz entre las 06:30 y las 20:30 locales."""
    h = hora_local(t)
    if 6.5 <= h <= 20.5:
        return max(0.0, math.sin(math.pi * (h - 6.5) / 14.0)) * pico_lux
    return 0.0


def curva_temp(t: datetime, minima: float, maxima: float) -> float:
    """Mínima cerca de las 06:00 y máxima cerca de las 15:00 locales."""
    h = hora_local(t)
    media, amplitud = (minima + maxima) / 2, (maxima - minima) / 2
    return media + amplitud * math.sin(2 * math.pi * (h - 10.5) / 24.0)


def ruido(desviacion: float) -> float:
    return random.gauss(0, desviacion)


# ---------------------------------------------------------------------------
# Escenarios
#   suelo(h)      -> humedad base en % (h = horas desde el inicio)
#   temp(t, h)    -> °C o None (sensor caído)
#   luz(t, h)     -> lux o None
# ---------------------------------------------------------------------------

def temp_normal(t: datetime, h: float) -> float:
    return curva_temp(t, 17, 27)


def luz_normal(t: datetime, h: float) -> float:
    return curva_luz(t, 55000)


def _secado_con_riego(h: float) -> float:
    """Baja de 45 % a ~20 % en 6 h; luego se riega y sube a ~58 %."""
    if h < 6:
        return 45 - h * 4.2
    return min(58.0, 25 + (h - 6) * 30)


def _calor(duracion_min: float) -> Callable[[datetime, float], float]:
    """24 °C estable, y desde la hora 1 un tramo a ~35 °C de la duración dada."""
    def temp(t: datetime, h: float) -> float:
        if 1.0 <= h < 1.0 + duracion_min / 60:
            return 35.0
        return 24.0
    return temp


def _temp_sensor_caido(t: datetime, h: float) -> Optional[float]:
    """El BME280 deja de responder a la hora 1,5."""
    return None if h >= 1.5 else temp_normal(t, h)


@dataclass
class Escenario:
    descripcion: str
    suelo: Callable[[float], float] = lambda h: 52 - 0.3 * (h % 24)
    temp: Callable[[datetime, float], Optional[float]] = temp_normal
    luz: Callable[[datetime, float], Optional[float]] = luz_normal
    horas: float = 6.0
    # normal | atrasadas | reenvio | invalidos
    orden: str = "normal"
    # La serie termina N horas antes de "ahora" (nodo que dejó de enviar)
    termina_hace_horas: float = 0.0
    sin_ruido_temp: bool = False
    esperado: str = ""


ESCENARIOS: dict[str, Escenario] = {
    "normal": Escenario(
        "Todo en rango: suelo ~50 %, 17–27 °C, buen sol.",
        esperado="Con tomate: «Todo bien» (verde).",
    ),
    "seco": Escenario(
        "El suelo se seca bajo el mínimo, sigue seco un rato y luego se riega.",
        suelo=_secado_con_riego, horas=8,
        esperado="Con tomate (30–70 %): se abre «… seca: X % (ideal 30 % a 70 %)» cerca de la "
                 "hora 3,6, se ACTUALIZA sin duplicarse y se resuelve tras el riego.",
    ),
    "encharcado": Escenario(
        "Exceso de riego: el suelo sube sobre el máximo.",
        suelo=lambda h: min(90.0, 55 + h * 8), horas=4,
        esperado="Con tomate (máx. 70 %): «… con exceso de agua: X %. No riegues hoy».",
    ),
    "helada": Escenario(
        "Noche fría: la temperatura baja hasta -3 °C.",
        suelo=lambda h: 50.0, temp=lambda t, h: curva_temp(t, -3, 14), horas=24,
        esperado="Con tomate (mín. 15 °C): «Riesgo de helada …» inmediato; se resuelve de día.",
    ),
    "calor_sostenido": Escenario(
        "35 °C durante 45 minutos seguidos.",
        suelo=lambda h: 50.0, temp=_calor(45), horas=3, sin_ruido_temp=True,
        esperado="Con tomate (máx. 30 °C): «Calor excesivo …» a los 30 min sobre el máximo.",
    ),
    "calor_breve": Escenario(
        "35 °C durante solo 20 minutos.",
        suelo=lambda h: 50.0, temp=_calor(20), horas=3, sin_ruido_temp=True,
        esperado="NO debe abrir alerta de calor (menos de 30 min).",
    ),
    "poca_luz": Escenario(
        "Cama a la sombra durante 4 días (pico de 30 000 lux, ~5 h sobre el umbral).",
        suelo=lambda h: 50.0, luz=lambda t, h: curva_luz(t, 30000), horas=96,
        esperado="Con tomate (6 h): «… recibe poca luz para tomate. Considera moverla o "
                 "elegir un cultivo de sombra, como lechuga» al 3.er día completo.",
    ),
    "sensor_caido": Escenario(
        "El sensor de temperatura (BME280) deja de enviar datos a la hora 1,5.",
        temp=_temp_sensor_caido, horas=4,
        esperado="A las 2 h sin datos: gris «Sensor de temperatura sin conexión», con prioridad.",
    ),
    "nodo_caido": Escenario(
        "El nodo completo dejó de enviar hace 3 horas.",
        horas=3, termina_hace_horas=3,
        esperado="Cama en gris; el LWT queda en 'offline'.",
    ),
    "atrasadas": Escenario(
        "La lectura más nueva llega primero y luego las antiguas (caso 09:00 / 08:55).",
        horas=0.5, orden="atrasadas",
        esperado="La lectura actual sigue siendo la de mayor medido_en.",
    ),
    "reenvio_duplicados": Escenario(
        "Corte de 1 h: el buffer se reenvía en orden y además se repiten 10 lecturas "
        "(PUBACK perdido).",
        horas=3, orden="reenvio",
        esperado="0 lecturas perdidas y 0 duplicadas (UNIQUE cama_id + seq).",
    ),
    "invalidos": Escenario(
        "Valores fuera de rango físico y un salto imposible del suelo.",
        horas=1, orden="invalidos",
        esperado="Se guardan, pero se marcan inválidos y no generan alertas.",
    ),
}


# ---------------------------------------------------------------------------
# Generación de lecturas
# ---------------------------------------------------------------------------

def a_iso_utc(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def acotar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def redondear(valor: Optional[float], decimales: int = 1) -> Optional[float]:
    return None if valor is None else round(valor, decimales)


def generar_lectura(nodo_id: str, esc: Escenario, t: datetime, h: float,
                    sondas: int) -> dict:
    """Arma el JSON tal como lo publica el firmware."""
    base = esc.suelo(h)
    # Cada sonda difiere un poco de las demás (posición en la cama)
    desfases = [0.0, 2.3, -1.8, 1.1][:sondas]
    suelo = [round(acotar(base + d + ruido(0.4), 0, 100), 1) for d in desfases]

    temp = esc.temp(t, h)
    if temp is not None and not esc.sin_ruido_temp:
        temp += ruido(0.3)
    hum_aire = None if temp is None else acotar(85 - (temp - 10) * 1.8 + ruido(1.5), 5, 100)
    lux = esc.luz(t, h)
    if lux is not None:
        lux = max(0.0, lux * (1 + ruido(0.03)))

    return {
        "nodo_id": nodo_id,
        "medido_en": a_iso_utc(t),
        "seq": int(t.timestamp()),
        "suelo": suelo,
        "suelo_prom": round(sum(suelo) / len(suelo), 1),
        "temp": redondear(temp),
        "hum_aire": redondear(hum_aire),
        "lux": None if lux is None else round(lux),
    }


def generar_serie(nodo_id: str, esc: Escenario, horas: float, intervalo_s: int,
                  sondas: int, ahora: datetime) -> list[dict]:
    """Serie en el orden en que llegaría al broker."""
    fin = ahora - timedelta(hours=esc.termina_hace_horas)
    inicio = fin - timedelta(hours=horas)
    serie, t = [], inicio
    while t <= fin:
        serie.append(generar_lectura(nodo_id, esc, t, (t - inicio).total_seconds() / 3600, sondas))
        t += timedelta(seconds=intervalo_s)

    if esc.orden == "atrasadas" and len(serie) > 1:
        # HU-01: la de 09:00 llega antes que la de 08:55
        serie = [serie[-1]] + serie[:-1]

    elif esc.orden == "reenvio" and len(serie) > 20:
        # Corte de 1 h en la mitad: durante el corte el nodo guarda en su buffer
        # y al reconectar envía todo en orden (llega tarde, pero en orden).
        # Además, 10 lecturas se reenvían dos veces porque se perdió el PUBACK.
        mitad = len(serie) // 2
        n_corte = max(1, int(3600 / intervalo_s))
        corte = serie[mitad:mitad + n_corte]
        duplicadas = corte[-10:]
        serie = serie[:mitad] + corte + duplicadas + serie[mitad + n_corte:]

    elif esc.orden == "invalidos" and len(serie) > 6:
        serie[2]["temp"] = 150.0                 # fuera de rango físico
        serie[3]["suelo"] = [-5.0] * len(serie[3]["suelo"])
        serie[3]["suelo_prom"] = -5.0
        serie[4]["lux"] = 200000                 # sobre 120 000 lux
        # Salto imposible: el suelo baja ~30 puntos de una lectura a otra
        serie[5]["suelo"] = [round(v - 30, 1) for v in serie[5]["suelo"]]
        serie[5]["suelo_prom"] = round(serie[5]["suelo_prom"] - 30, 1)
    return serie


def heartbeat(inicio_mono: float) -> dict:
    return {
        "uptime_s": int(time.monotonic() - inicio_mono),
        "rssi": random.randint(-72, -55),
        "motivo_reinicio": "POWERON",
        "buffer_pendiente": 0,
        "heap_libre": random.randint(170000, 190000),
    }


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

def topico_lectura(nodo: str) -> str:
    return f"huerto/cama/{nodo}/lectura"


def topico_conexion(nodo: str) -> str:
    return f"huerto/nodo/{nodo}/conexion"


def topico_heartbeat(nodo: str) -> str:
    return f"huerto/nodo/{nodo}/heartbeat"


def topico_estado(nodo: str) -> str:
    return f"huerto/cama/{nodo}/estado"


class NodoSimulado:
    """Una conexión MQTT por nodo, con su LWT, como el ESP32 real."""

    def __init__(self, nodo_id: str, args):
        import paho.mqtt.client as mqtt  # import tardío: --seco funciona sin paho

        self.mqtt = mqtt
        self.nodo_id = nodo_id
        self.conectado = threading.Event()
        self.error: Optional[str] = None
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=f"sim-{nodo_id}", clean_session=True)
        self.cliente.username_pw_set(args.usuario, args.clave)
        self.cliente.will_set(topico_conexion(nodo_id), "offline", qos=1, retain=True)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_message = self._al_recibir
        self.mostrar_estado = args.tiempo_real

    def _al_conectar(self, cliente, userdata, flags, codigo, propiedades=None):
        if codigo.is_failure:
            self.error = str(codigo)
        else:
            cliente.publish(topico_conexion(self.nodo_id), "online", qos=1, retain=True)
            if self.mostrar_estado:
                cliente.subscribe(topico_estado(self.nodo_id), qos=1)
        self.conectado.set()

    def _al_recibir(self, cliente, userdata, mensaje):
        try:
            estado = json.loads(mensaje.payload)
            print(f"  LED {self.nodo_id} → {estado.get('color')}: {estado.get('mensaje')}")
        except ValueError:
            print(f"  Estado no válido en {mensaje.topic}: {mensaje.payload[:80]!r}")

    def conectar(self, host: str, puerto: int) -> None:
        try:
            self.cliente.connect(host, puerto, keepalive=30)
        except OSError as e:
            raise SystemExit(f"No se pudo conectar al broker {host}:{puerto} ({e}). "
                             "¿Está corriendo 'docker compose up -d' en central/?")
        self.cliente.loop_start()
        if not self.conectado.wait(10):
            raise SystemExit("El broker no respondió a la conexión.")
        if self.error:
            raise SystemExit(f"El broker rechazó la conexión: {self.error}. "
                             "Revisa el usuario y la clave del simulador.")

    def publicar(self, topico: str, datos, retener: bool = False) -> bool:
        texto = datos if isinstance(datos, str) else json.dumps(datos)
        info = self.cliente.publish(topico, texto, qos=1, retain=retener)
        info.wait_for_publish(timeout=10)
        return info.is_published()

    def cerrar(self) -> None:
        # Una desconexión limpia no dispara el LWT: se publica "offline" a mano.
        self.publicar(topico_conexion(self.nodo_id), "offline", retener=True)
        self.cliente.loop_stop()
        self.cliente.disconnect()


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------

def resumen(lectura: dict) -> str:
    return (f"{lectura['nodo_id']} seq={lectura['seq']} {lectura['medido_en']} "
            f"suelo={lectura['suelo']} prom={lectura['suelo_prom']}% "
            f"temp={lectura['temp']}°C aire={lectura['hum_aire']}% luz={lectura['lux']}lx")


def modo_historico(args, nodos: list[str], esc: Escenario) -> int:
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    horas = args.horas if args.horas is not None else esc.horas
    fallidas = 0
    for nodo_id in nodos:
        serie = generar_serie(nodo_id, esc, horas, args.intervalo, args.sondas, ahora)
        if args.seco:
            for lectura in serie:
                print(topico_lectura(nodo_id), json.dumps(lectura, ensure_ascii=False))
            continue

        nodo = NodoSimulado(nodo_id, args)
        nodo.conectar(args.host, args.puerto)
        for i, lectura in enumerate(serie, 1):
            if not nodo.publicar(topico_lectura(nodo_id), lectura):
                fallidas += 1
                print(f"[FALLÓ] {resumen(lectura)}")
            elif args.detalle:
                print(f"[OK] {resumen(lectura)}")
            if args.pausa:
                time.sleep(args.pausa)
        nodo.cerrar()
        print(f"{nodo_id}: {len(serie)} lecturas publicadas ({fallidas} fallidas).")
    return 1 if fallidas else 0


def modo_tiempo_real(args, nodos: list[str], esc: Escenario) -> int:
    """Una lectura por nodo cada --intervalo s y un heartbeat cada 60 s."""
    simulados = []
    for nodo_id in nodos:
        if not args.seco:
            nodo = NodoSimulado(nodo_id, args)
            nodo.conectar(args.host, args.puerto)
            simulados.append(nodo)
    # Sin microsegundos, igual que "ahora": si no, h sale levemente negativa
    # en la primera lectura y las curvas cíclicas dan un salto.
    inicio = datetime.now(timezone.utc).replace(microsecond=0)
    inicio_mono = time.monotonic()
    ultimo_hb = -1e9
    print(f"Tiempo real: una lectura cada {args.intervalo} s. Ctrl+C para salir.")
    try:
        while True:
            ahora = datetime.now(timezone.utc).replace(microsecond=0)
            h = (ahora - inicio).total_seconds() / 3600
            enviar_hb = time.monotonic() - ultimo_hb >= 60
            for i, nodo_id in enumerate(nodos):
                lectura = generar_lectura(nodo_id, esc, ahora, h, args.sondas)
                if args.seco:
                    print(topico_lectura(nodo_id), json.dumps(lectura, ensure_ascii=False))
                    continue
                ok = simulados[i].publicar(topico_lectura(nodo_id), lectura)
                print(f"[{'OK' if ok else 'FALLÓ'}] {resumen(lectura)}")
                if enviar_hb:
                    simulados[i].publicar(topico_heartbeat(nodo_id), heartbeat(inicio_mono))
            if enviar_hb:
                ultimo_hb = time.monotonic()
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        for nodo in simulados:
            nodo.cerrar()
    return 0


# ---------------------------------------------------------------------------

def leer_env(ruta: Path) -> dict[str, str]:
    """Lector mínimo de .env (CLAVE=valor, ignora comentarios)."""
    valores: dict[str, str] = {}
    if ruta.is_file():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def main() -> int:
    # La consola de Windows usa cp1252 por defecto y no imprime "→" ni "°".
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    env = leer_env(ENV_CENTRAL)
    p = argparse.ArgumentParser(
        description="Simula nodos ESP32 que publican lecturas por MQTT.")
    p.add_argument("--host", default=os.environ.get("MQTT_HOST_SIM", "localhost"),
                   help="Broker MQTT (por defecto localhost)")
    p.add_argument("--puerto", type=int, default=1883)
    p.add_argument("--usuario", default=env.get("MQTT_USER_SIMULADOR", "simulador"))
    p.add_argument("--clave", default=env.get("MQTT_PASS_SIMULADOR", ""),
                   help="Por defecto se lee de central/.env")
    p.add_argument("--nodos", default="cama-a", help="NODO_ID separados por coma")
    p.add_argument("--escenario", default="normal", choices=list(ESCENARIOS))
    p.add_argument("--horas", type=float, help="Horas de historial (cada escenario trae su valor)")
    p.add_argument("--intervalo", type=int, default=60,
                   help="Segundos entre lecturas (por defecto 60; el nodo real usa 30)")
    p.add_argument("--sondas", type=int, default=2, choices=[1, 2, 3, 4],
                   help="Sondas de suelo por nodo")
    p.add_argument("--tiempo-real", action="store_true",
                   help="Publica con la hora actual cada --intervalo segundos")
    p.add_argument("--pausa", type=float, default=0.0,
                   help="Segundos de espera entre publicaciones en modo histórico")
    p.add_argument("--seco", action="store_true", help="No publica: imprime tópico y JSON")
    p.add_argument("--detalle", action="store_true", help="Muestra cada publicación")
    p.add_argument("--semilla", type=int, help="Semilla aleatoria (resultados repetibles)")
    p.add_argument("--listar", action="store_true", help="Lista los escenarios y sale")
    args = p.parse_args()

    if args.listar:
        for nombre, esc in ESCENARIOS.items():
            print(f"{nombre:19} {esc.descripcion}")
            print(f"{'':19} esperado: {esc.esperado}")
        return 0
    if args.intervalo <= 0 or (args.horas is not None and args.horas < 0):
        p.error("--intervalo debe ser > 0 y --horas >= 0")
    if not args.seco and not args.clave:
        p.error("Falta la clave MQTT: usa --clave o define MQTT_PASS_SIMULADOR en central/.env")
    if args.semilla is not None:
        random.seed(args.semilla)

    nodos = [n.strip() for n in args.nodos.split(",") if n.strip()]
    esc = ESCENARIOS[args.escenario]
    if not args.seco:
        print(f"Escenario '{args.escenario}': {esc.descripcion}")
        print(f"  esperado: {esc.esperado}")
    if args.tiempo_real:
        return modo_tiempo_real(args, nodos, esc)
    return modo_historico(args, nodos, esc)


if __name__ == "__main__":
    sys.exit(main())
