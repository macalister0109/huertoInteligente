"""Aplica las migraciones de db/migraciones/ que falten, en orden.

    cd central
    python -m comun.migrar               # con la BD de central/.env
    docker compose exec web python -m comun.migrar

    python -m comun.migrar --revertir 003_clima_referencia.sql

db/schema.sql solo se ejecuta cuando la BD está vacía (primera vez). Las
migraciones cambian una BD que YA tiene datos sin borrarlos. Cada archivo
se registra en la tabla `migraciones` para no aplicarlo dos veces.

Reversión: cada migración NNN_x.sql puede tener su NNN_x.down.sql. Revertir
ejecuta ese archivo y borra el registro, así se puede volver a aplicar. Una
migración sin .down.sql no se puede revertir (ej. 001, porque tocaría las
lecturas crudas). Ninguna reversión toca la tabla `lecturas`.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import Config, cargar_env
from .db import conectar

log = logging.getLogger(__name__)

CARPETA = Path(__file__).resolve().parent.parent / "db" / "migraciones"


def sentencias(texto: str) -> list[str]:
    """Separa un archivo SQL simple (sin procedimientos) en sentencias."""
    sin_comentarios = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


def pendientes(conn, carpeta: Path = CARPETA) -> list[Path]:
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS migraciones (
                           nombre VARCHAR(100) NOT NULL,
                           aplicada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                           PRIMARY KEY (nombre))
                       ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        cur.execute("SELECT nombre FROM migraciones")
        aplicadas = {f["nombre"] for f in cur.fetchall()}
    conn.commit()
    return [a for a in sorted(carpeta.glob("*.sql"))
            if not es_reversion(a) and a.name not in aplicadas]


def es_reversion(archivo: Path) -> bool:
    return archivo.name.endswith(".down.sql")


def archivo_reversion(nombre: str, carpeta: Path = CARPETA) -> Path:
    return carpeta / (nombre[:-len(".sql")] + ".down.sql")


def migrar(conn, carpeta: Path = CARPETA) -> list[str]:
    """Aplica las pendientes y devuelve sus nombres."""
    hechas = []
    for archivo in pendientes(conn, carpeta):
        with conn.cursor() as cur:
            # Los ALTER de MariaDB hacen commit solos: por eso cada migración
            # debe ser idempotente (IF NOT EXISTS) por si se corta a la mitad.
            for sql in sentencias(archivo.read_text(encoding="utf-8")):
                cur.execute(sql)
            cur.execute("INSERT INTO migraciones (nombre) VALUES (%s)", (archivo.name,))
        conn.commit()
        log.info("Migración aplicada: %s", archivo.name)
        hechas.append(archivo.name)
    return hechas


def revertir(conn, nombre: str, carpeta: Path = CARPETA) -> None:
    """Ejecuta NNN_x.down.sql y borra el registro de la migración."""
    if not nombre.endswith(".sql"):
        nombre += ".sql"
    abajo = archivo_reversion(nombre, carpeta)
    if not abajo.is_file():
        raise ValueError(f"{nombre} no tiene archivo de reversión ({abajo.name})")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM migraciones WHERE nombre = %s", (nombre,))
        if cur.fetchone() is None:
            raise ValueError(f"{nombre} no está aplicada")
        for sql in sentencias(abajo.read_text(encoding="utf-8")):
            cur.execute(sql)
        cur.execute("DELETE FROM migraciones WHERE nombre = %s", (nombre,))
    conn.commit()
    log.info("Migración revertida: %s", nombre)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    argv = sys.argv[1:] if argv is None else argv
    cargar_env()
    conn = conectar(Config.desde_entorno())
    try:
        if argv[:1] == ["--revertir"] and len(argv) == 2:
            try:
                revertir(conn, argv[1])
            except ValueError as e:
                print(f"No se revirtió: {e}")
                return 1
            print(f"Migración revertida: {argv[1]}")
            return 0
        if argv:
            print("Uso: python -m comun.migrar [--revertir NNN_nombre.sql]")
            return 2
        hechas = migrar(conn)
    finally:
        conn.close()
    print("Migraciones aplicadas: " + ", ".join(hechas) if hechas else "La BD ya está al día.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
