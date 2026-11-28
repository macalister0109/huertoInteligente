"""Recalcula las marcas de calidad y los agregados de un rango de fechas.

    cd central
    python -m comun.analitica.recalcular --desde 2026-11-01 --hasta 2026-11-30
    python -m comun.analitica.recalcular --desde 2026-11-27 --hasta 2026-11-27 --cama 1
    docker compose exec web python -m comun.analitica.recalcular --desde ... --hasta ...

Las fechas son días en hora de Chile, ambos incluidos. Es seguro repetirlo:
reemplaza lo calculado sin duplicar y nunca modifica las lecturas crudas.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from ..config import Config, cargar_env
from ..db import ahora_utc, conectar
from .proceso import recalcular


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", required=True, type=date.fromisoformat, help="AAAA-MM-DD")
    p.add_argument("--hasta", required=True, type=date.fromisoformat, help="AAAA-MM-DD")
    p.add_argument("--cama", type=int, default=None, help="id de la cama (por defecto, todas)")
    args = p.parse_args(argv)
    if args.hasta < args.desde:
        p.error("--hasta debe ser igual o posterior a --desde")

    cargar_env()
    cfg = Config.desde_entorno()
    conn = conectar(cfg)
    try:
        from ..ajustes import config_vigente
        cfg = config_vigente(conn, cfg)          # umbral de riego elegido en /configuracion
        r = recalcular(conn, cfg, args.desde, args.hasta, ahora_utc(), args.cama)
    finally:
        conn.close()
    print(f"Listo: {len(r.camas)} cama(s), {r.dias} día(s) recalculados · {r.marcas} marcas de "
          f"calidad · {r.riegos} riegos detectados · {r.filas_hora} filas por hora · "
          f"{r.filas_dia} filas por día.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
