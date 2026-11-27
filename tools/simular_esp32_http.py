#!/usr/bin/env python3
"""
Simula al ESP32 enviando lecturas por HTTP a la API (POST /api/lecturas).

Sirve para probar la API ANTES de subir el firmware a la placa. Solo usa la
biblioteca estándar de Python (no hay que instalar nada).

    python tools/simular_esp32_http.py --token TU_TOKEN
    python tools/simular_esp32_http.py --token TU_TOKEN --url http://192.168.1.50:8080
    python tools/simular_esp32_http.py --token TU_TOKEN --solo-una

El token también se puede dar en la variable HUERTO_TOKEN.

Pruebas que hace, en orden (y qué respuesta espera):
    1. lectura normal                          -> 201
    2. la misma lectura otra vez (buffer)      -> 200 (duplicada, no se guarda dos veces)
    3. lectura atrasada (medida hace 10 min)   -> 201, pero NO cambia la "última"
    4. temperatura imposible (85 °C)           -> 201, guardada como inválida
    5. token malo                              -> 401
    6. JSON mal formado                        -> 400
    7. GET /api/camas/<nodo>/ultima            -> la lectura 1 (mayor medido_en)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def pedir(metodo: str, url: str, token: str | None = None, cuerpo: bytes | None = None):
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        texto = e.read()
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, texto.decode("utf-8", "replace")
    except urllib.error.URLError as e:
        sys.exit(f"No se pudo conectar a {url}: {e.reason}\n"
                 "¿Está corriendo el equipo central (docker compose up -d)?")


def main() -> int:
    # La consola de Windows no siempre usa UTF-8: así los acentos se ven bien
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8080", help="dirección del equipo central")
    p.add_argument("--token", default=os.environ.get("HUERTO_TOKEN"), help="token del nodo")
    p.add_argument("--nodo", default="cama-a")
    p.add_argument("--solo-una", action="store_true", help="envía una sola lectura normal")
    args = p.parse_args()
    if not args.token:
        p.error("falta --token (o la variable HUERTO_TOKEN)")

    api = args.url.rstrip("/") + "/api/lecturas"
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    seq_base = int(time.time())          # único y creciente, como el contador del nodo

    def lectura(seq: int, medido: datetime, **cambios) -> bytes:
        datos = {"nodo_id": args.nodo, "seq": seq, "medido_en": iso(medido),
                 "temp": 23, "hum_aire": 61, "suelo_pct": 42, "suelo_mv": 2350, "luz": None}
        datos.update(cambios)
        return json.dumps(datos).encode()

    pruebas = [
        ("1. lectura normal", 201, dict(token=args.token, cuerpo=lectura(seq_base, ahora))),
        ("2. misma lectura otra vez (reenvío del buffer)", 200,
         dict(token=args.token, cuerpo=lectura(seq_base, ahora))),
        ("3. lectura atrasada (medida hace 10 min)", 201,
         dict(token=args.token, cuerpo=lectura(seq_base - 20, ahora - timedelta(minutes=10),
                                                suelo_pct=65))),
        ("4. temperatura imposible para el DHT11 (85 °C)", 201,
         dict(token=args.token, cuerpo=lectura(seq_base + 1, ahora - timedelta(minutes=1), temp=85))),
        ("5. token malo", 401, dict(token="token-falso", cuerpo=lectura(seq_base + 2, ahora))),
        ("6. JSON mal formado", 400, dict(token=args.token, cuerpo=b"{esto no es json")),
    ]
    if args.solo_una:
        pruebas = pruebas[:1]

    fallas = 0
    for nombre, esperado, kw in pruebas:
        codigo, respuesta = pedir("POST", api, **kw)
        ok = codigo == esperado
        fallas += not ok
        print(f"{'OK  ' if ok else 'FALLA'} {nombre}: HTTP {codigo} (esperado {esperado})")
        print(f"      {respuesta}")

    if not args.solo_una:
        codigo, ultima = pedir("GET", f"{args.url.rstrip('/')}/api/camas/{args.nodo}/ultima")
        lect = (ultima or {}).get("lectura") or {}
        ok = codigo == 200 and lect.get("seq") == seq_base
        fallas += not ok
        print(f"{'OK  ' if ok else 'FALLA'} 7. última lectura = la de mayor medido_en "
              f"(seq {seq_base}, no la atrasada): HTTP {codigo}")
        print(f"      {ultima}")

    print("\nTodo bien." if not fallas else f"\n{fallas} prueba(s) fallaron.")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
