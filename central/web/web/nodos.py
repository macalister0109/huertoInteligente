"""Tokens de los nodos que envían lecturas por HTTP.

Crear el nodo de una cama y mostrar su token (UNA sola vez):

    cd central
    python -m web.nodos crear cama-a
    python -m web.nodos crear cama-a --regenerar     # token nuevo (el anterior deja de servir)
    python -m web.nodos listar

Con Docker:  docker compose exec web python -m web.nodos crear cama-a

En la BD solo queda el hash SHA-256 del token. Si se pierde, no se puede
recuperar: se genera uno nuevo con --regenerar y se carga en el config.h del nodo.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sys
from datetime import datetime
from typing import Optional

from comun.config import Config, cargar_env
from comun.db import conectar
from procesador import repositorio as repo

# Igual que en los tópicos MQTT: minúsculas, números y guiones
FORMATO_NODO_ID = re.compile(r"^[a-z0-9-]{1,40}$")


class NodoYaExiste(Exception):
    pass


def generar_token() -> str:
    """256 bits aleatorios en base64 URL (43 caracteres, sin símbolos raros)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_nodo(conn, nodo_id: str, regenerar: bool = False) -> str:
    """Crea (o regenera) el token del nodo y lo devuelve en texto plano.

    Si la cama del nodo no existe, se crea sin cultivo (igual que cuando
    llega la primera lectura de un nodo desconocido).
    """
    if not FORMATO_NODO_ID.match(nodo_id):
        raise ValueError("nodo_id: solo minúsculas, números y guiones (máx. 40), ej. cama-a")
    token = generar_token()
    cama = repo.obtener_o_crear_cama(conn, nodo_id)
    with conn.cursor() as cur:
        cur.execute("SELECT nodo_id FROM nodos WHERE nodo_id = %s FOR UPDATE", (nodo_id,))
        existe = cur.fetchone() is not None
        if existe and not regenerar:
            conn.rollback()
            raise NodoYaExiste(f"El nodo {nodo_id} ya tiene token. Usa --regenerar para cambiarlo.")
        if existe:
            cur.execute("UPDATE nodos SET token_hash = %s, activo = 1, ultimo_uso_en = NULL "
                        "WHERE nodo_id = %s", (hash_token(token), nodo_id))
        else:
            cur.execute("INSERT INTO nodos (nodo_id, cama_id, token_hash) VALUES (%s, %s, %s)",
                        (nodo_id, cama["id"], hash_token(token)))
    conn.commit()
    return token


def nodo_por_token(conn, token: str, ahora: Optional[datetime] = None) -> Optional[str]:
    """nodo_id dueño del token, o None si el token no existe o está desactivado.

    La búsqueda es por hash (índice único): el token en texto plano nunca
    se compara ni se guarda.
    """
    if not token:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT nodo_id FROM nodos WHERE token_hash = %s AND activo = 1",
                    (hash_token(token),))
        fila = cur.fetchone()
        if fila is None:
            return None
        if ahora is not None:
            cur.execute("UPDATE nodos SET ultimo_uso_en = %s WHERE nodo_id = %s",
                        (ahora.replace(microsecond=0), fila["nodo_id"]))
    return fila["nodo_id"]


def listar(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT n.nodo_id, c.nombre AS cama, n.activo, n.creado_en, n.ultimo_uso_en
                         FROM nodos n JOIN camas c ON c.id = n.cama_id ORDER BY n.nodo_id""")
        return list(cur.fetchall())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m web.nodos",
                                     description="Tokens de los nodos ESP32 (API HTTP).")
    sub = parser.add_subparsers(dest="accion", required=True)
    p_crear = sub.add_parser("crear", help="crea el nodo y muestra su token una sola vez")
    p_crear.add_argument("nodo_id", help="ej. cama-a (igual a NODO_ID del config.h)")
    p_crear.add_argument("--regenerar", action="store_true",
                         help="reemplaza el token actual (el anterior deja de funcionar)")
    sub.add_parser("listar", help="muestra los nodos registrados (sin tokens)")
    args = parser.parse_args(argv)

    cargar_env()
    conn = conectar(Config.desde_entorno())
    try:
        if args.accion == "listar":
            for n in listar(conn):
                print(f"{n['nodo_id']:<12} {n['cama']:<15} "
                      f"{'activo' if n['activo'] else 'inactivo':<9} "
                      f"último uso: {n['ultimo_uso_en'] or 'nunca'}")
            return 0
        try:
            token = crear_nodo(conn, args.nodo_id, regenerar=args.regenerar)
        except (NodoYaExiste, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
    finally:
        conn.close()

    print(f"Nodo {args.nodo_id} listo. Copia esta línea en firmware/nodo/config.h:\n")
    print(f'  #define API_TOKEN "{token}"\n')
    print("Este token se muestra UNA sola vez y no se guarda en ningún lado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
