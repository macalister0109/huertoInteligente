#!/usr/bin/env python3
"""Crea central/.env a partir de .env.example, con claves aleatorias.

    cd central
    python3 despliegue/crear_env.py              # para la casa (puerto 8080 abierto en la red local)
    python3 despliegue/crear_env.py --servidor   # para mjvirtual (solo localhost, detrás de nginx)

No pisa un .env que ya exista (usa --forzar si de verdad quieres reemplazarlo:
las claves de la base de datos cambiarían y MariaDB ya no aceptaría las nuevas).
Al final muestra el PIN del docente: anótalo.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

CENTRAL = Path(__file__).resolve().parent.parent

# Valores del servidor mjvirtual (nginx -> 127.0.0.1:18020)
SERVIDOR = {
    "WEB_ESCUCHA": "127.0.0.1",
    "WEB_PUERTO": "18020",
    "MQTT_ESCUCHA": "127.0.0.1",
    "MQTT_PUERTO_LOCAL": "11883",
    "DB_PUERTO_LOCAL": "13306",
    "PROXY_SALTOS": "1",
    "COOKIE_SEGURA": "true",
}


def poner(texto: str, clave: str, valor: str) -> str:
    patron = re.compile(rf"^{re.escape(clave)}=.*$", re.M)
    if patron.search(texto):
        return patron.sub(f"{clave}={valor}", texto)
    return texto.rstrip("\n") + f"\n{clave}={valor}\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--servidor", action="store_true", help="valores para el servidor detrás de nginx")
    p.add_argument("--forzar", action="store_true", help="reemplaza un .env existente")
    args = p.parse_args()

    destino = CENTRAL / ".env"
    if destino.exists() and destino.stat().st_size > 0 and not args.forzar:
        print(f"Ya existe {destino}. No se tocó (usa --forzar para reemplazarlo).", file=sys.stderr)
        return 1

    texto = (CENTRAL / ".env.example").read_text(encoding="utf-8")
    texto = re.sub(r"cambia_esto\w*", lambda _: secrets.token_urlsafe(18), texto)
    pin = str(secrets.randbelow(900000) + 100000)
    texto = poner(texto, "PIN_DOCENTE", pin)
    texto = poner(texto, "CLAVE_SESION_WEB", secrets.token_hex(32))
    if args.servidor:
        for clave, valor in SERVIDOR.items():
            texto = poner(texto, clave, valor)

    destino.write_text(texto, encoding="utf-8")
    try:
        destino.chmod(0o600)     # solo tu usuario puede leerlo (en Linux)
    except OSError:
        pass
    print(f"Creado {destino} ({'servidor' if args.servidor else 'casa'}).")
    print(f"PIN del docente para /configuracion: {pin}  (anótalo; también está en el .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
