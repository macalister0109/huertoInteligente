"""Genera datos SINTÉTICOS con el mismo formato que la exportación real.

    python tools/generar_sinteticos.py                    # 28 días, 2 camas, semilla 2026
    python tools/generar_sinteticos.py --dias 60 --semilla 7 --parquet

Sirven para desarrollar y probar el notebook (analisis/exploratorio.ipynb)
mientras se juntan datos reales. Reglas:
* Cada fila lleva origen = «sintetico».
* Se escriben SOLO en analisis/datos_sinteticos/ (archivos aparte): nunca en
  la base de datos y nunca junto a una exportación real.
* Reproducible: la misma semilla produce exactamente los mismos archivos.

Qué simula:
* Clima de la zona (una instantánea por hora): ciclo diario de temperatura,
  humedad, radiación, algunos días con lluvia y ET0.
* Cama A (tomate, a pleno sol) y Cama B (lechuga, con sombra parcial).
  Temperatura y humedad del aire con la resolución del DHT11 (enteros).
* Secado del suelo más rápido con sol y calor; riegos en la mañana de los
  días de clases cuando el suelo está bajo, y riegos de emergencia.
* Fallas a propósito, para que el análisis de calidad tenga qué encontrar:
  un hueco de 3 h, un sensor de suelo pegado 5 h, temperaturas fuera de rango
  y un salto imposible de humedad del aire.
Las marcas de calidad, los agregados y los riegos se calculan con las MISMAS
funciones que usa el equipo central (central/comun/analitica).
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "central"))

from comun.analitica import exportacion  # noqa: E402
from comun.analitica.agregados import agregar_dia, agregar_horas, limites_dia_local  # noqa: E402
from comun.analitica.calidad import LecturaCruda, calcular_marcas, excluidas  # noqa: E402
from comun.analitica.riego import detectar_riegos, puntos_suelo  # noqa: E402
from comun.config import Config  # noqa: E402
from comun.rangos import Rango  # noqa: E402

ORIGEN = "sintetico"
CARPETA = RAIZ / "analisis" / "datos_sinteticos"
ZONA = ZoneInfo("America/Santiago")


@dataclass(frozen=True)
class Cama:
    id: int
    nombre: str
    nodo_id: str
    rango: Rango
    sol: float              # 1 = pleno sol, 0 = sombra
    secado: float           # multiplicador de la tasa de secado


CAMAS = (
    Cama(1, "Cama A", "cama-a", Rango(30, 70, 15, 30, 6, "tomate"), 1.0, 1.0),
    Cama(2, "Cama B", "cama-b", Rango(40, 80, 7, 24, 3, "lechuga"), 0.45, 0.7),
)


def local(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc).astimezone(ZONA)


def utc(fecha: date, hora: float) -> datetime:
    h, m = int(hora), int(round((hora % 1) * 60))
    return datetime.combine(fecha, time(h, m), tzinfo=ZONA).astimezone(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ clima

def clima_horario(inicio: date, dias: int, rnd: random.Random) -> list[dict]:
    filas, et0_hoy, dia_actual = [], 0.0, None
    lluvia_dias = {inicio + timedelta(days=d) for d in rnd.sample(range(dias), k=max(1, dias // 10))}
    for d in range(dias):
        fecha = inicio + timedelta(days=d)
        media = 18 + rnd.uniform(-3, 3)
        amplitud = 8 + rnd.uniform(-2, 3) - (4 if fecha in lluvia_dias else 0)
        nubes = 0.35 if fecha in lluvia_dias else rnd.uniform(0.85, 1.0)
        for h in range(24):
            t = utc(fecha, h)
            temp = media + amplitud * math.sin(2 * math.pi * (h - 9) / 24)
            rad = max(0.0, 950 * nubes * math.sin(math.pi * (h - 6.5) / 14)) if 6.5 < h < 20.5 else 0.0
            lluvia = round(rnd.uniform(0.2, 2.5), 1) if fecha in lluvia_dias and 4 <= h <= 14 else 0.0
            hum = min(98.0, max(18.0, 72 - 2.2 * (temp - 15) + (20 if lluvia else 0)))
            et0 = round(rad * 0.00075 * (1 + max(0.0, temp - 15) / 30), 2)
            if dia_actual != fecha:
                et0_hoy, dia_actual = 0.0, fecha
            et0_hoy += et0
            filas.append({"origen": ORIGEN, "fuente": "open-meteo", "observado_en_utc": t,
                          "lat": -33.54, "lon": -70.64, "temp_aire_c": round(temp, 1),
                          "hum_rel_pct": round(hum), "precipitacion_mm": lluvia,
                          "radiacion_wm2": round(rad, 1), "temp_suelo_c": round(temp + rad / 120, 1),
                          "hum_suelo_vwc_pct": round(17 + (6 if fecha in lluvia_dias else 0), 1),
                          "et0_mm": et0, "et0_hoy_mm": round(et0_hoy, 2)})
    return filas


def interpolar_clima(clima: list[dict], t: datetime) -> dict:
    """Clima de la hora de `t` (las instantáneas son horarias)."""
    i = int((t - clima[0]["observado_en_utc"]).total_seconds() // 3600)
    return clima[max(0, min(i, len(clima) - 1))]


# ------------------------------------------------------------------ camas

def simular_cama(cama: Cama, inicio: date, dias: int, intervalo_s: int, clima: list[dict],
                 rnd: random.Random, id0: int) -> list[LecturaCruda]:
    t = utc(inicio, 0)
    fin = utc(inicio + timedelta(days=dias), 0)
    suelo = cama.rango.humedad_min + 25
    riego_pendiente = 0.0
    lecturas, i = [], 0
    # Fallas a propósito
    hueco = (utc(inicio + timedelta(days=4), 12), utc(inicio + timedelta(days=4), 15)) if cama.id == 1 else None
    pegado = (utc(inicio + timedelta(days=11), 3), utc(inicio + timedelta(days=11), 8)) if cama.id == 2 else None
    total = int(dias * 86400 / intervalo_s)                 # lecturas esperadas
    fuera_rango = {rnd.randrange(total // 10, total * 9 // 10) for _ in range(3)} if cama.id == 1 else set()
    salto_hum = rnd.randrange(total // 5, total * 4 // 5) if cama.id == 2 else -1
    valor_pegado = None
    regado_hoy = None

    while t < fin:
        c = interpolar_clima(clima, t)
        hora_local = local(t)
        dh = intervalo_s / 3600
        # Secado: más rápido con sol y calor; la lluvia moja
        tasa = (0.18 + 1.1 * cama.sol * c["radiacion_wm2"] / 950
                + 0.04 * max(0.0, c["temp_aire_c"] - 18)) * cama.secado
        suelo -= tasa * dh
        suelo += 0.9 * c["precipitacion_mm"] * dh
        # Riego: mañana de días de clases si está bajo; emergencia si pasa el mínimo
        clases = hora_local.weekday() < 5
        if regado_hoy != hora_local.date() and riego_pendiente <= 0:
            manana = clases and abs(hora_local.hour + hora_local.minute / 60 - 8.75) < dh / 2 + 1e-9
            emergencia = 9 <= hora_local.hour <= 17 and suelo < cama.rango.humedad_min - 2 and clases
            if (manana and suelo < cama.rango.humedad_min + 10) or emergencia:
                riego_pendiente = rnd.uniform(18, 26)
                regado_hoy = hora_local.date()
        if riego_pendiente > 0:
            paso = min(riego_pendiente, 1.6 * intervalo_s / 60)     # ~15 min de riego
            suelo += paso
            riego_pendiente -= paso
        suelo = max(3.0, min(96.0, suelo))

        if hueco and hueco[0] <= t < hueco[1]:
            t += timedelta(seconds=intervalo_s)
            continue
        temp_cama = c["temp_aire_c"] + 3.5 * cama.sol * c["radiacion_wm2"] / 950 + rnd.gauss(0, 0.4)
        hum_cama = c["hum_rel_pct"] + (6 if cama.sol < 0.5 else -2) + rnd.gauss(0, 1.5)
        valor_suelo = round(suelo + rnd.gauss(0, 0.25), 1)
        if pegado and pegado[0] <= t < pegado[1]:
            valor_pegado = valor_pegado if valor_pegado is not None else valor_suelo
            valor_suelo = valor_pegado
        invalidos = {}
        temp = float(round(temp_cama))                       # DHT11: enteros
        hum = float(min(100, max(0, round(hum_cama))))
        if i in fuera_rango:
            invalidos["temp"] = {"valor": 85, "tipo": "rango", "detalle": "temp fuera de rango físico (85)"}
            temp = None
        if i == salto_hum:
            invalidos["hum_aire"] = {"valor": hum + 40, "tipo": "salto",
                                     "detalle": "hum_aire cambió 40 puntos en 1 min"}
            hum = None
        lecturas.append(LecturaCruda(id0 + i, t, valor_suelo, temp, hum, invalidos))
        i += 1
        t += timedelta(seconds=intervalo_s)
    return lecturas


def alertas_simples(cama: Cama, lecturas: list[LecturaCruda], id0: int) -> list[dict]:
    """Alertas de suelo y temperatura con la misma idea que el procesador
    (una abierta por tipo, se resuelve con histéresis). Simplificado."""
    reglas = {
        "suelo_seco": ("suelo", lambda l: l.suelo is not None and l.suelo < cama.rango.humedad_min,
                       lambda l: l.suelo is not None and l.suelo >= cama.rango.humedad_min + 2),
        "suelo_encharcado": ("suelo", lambda l: l.suelo is not None and l.suelo > cama.rango.humedad_max,
                             lambda l: l.suelo is not None and l.suelo <= cama.rango.humedad_max - 2),
        "helada": ("temperatura", lambda l: l.temp is not None and l.temp < cama.rango.temp_min,
                   lambda l: l.temp is not None and l.temp >= cama.rango.temp_min + 1),
        "calor": ("temperatura", lambda l: l.temp is not None and l.temp > cama.rango.temp_max,
                  lambda l: l.temp is not None and l.temp <= cama.rango.temp_max - 1),
    }
    abiertas: dict[str, dict] = {}
    filas = []
    for l in lecturas:
        for tipo, (variable, abre, cierra) in reglas.items():
            valor = l.suelo if variable == "suelo" else l.temp
            if tipo not in abiertas and abre(l):
                abiertas[tipo] = {"origen": ORIGEN, "alerta_id": id0 + len(filas) + len(abiertas),
                                  "cama_id": cama.id, "cama": cama.nombre, "tipo": tipo,
                                  "variable": variable, "estado": "abierta",
                                  "mensaje": f"{cama.nombre}: {tipo.replace('_', ' ')} ({valor:g})",
                                  "valor_inicial": valor, "valor_actual": valor,
                                  "iniciada_en_utc": l.medido_en, "actualizada_en_utc": l.medido_en,
                                  "resuelta_en_utc": None}
            elif tipo in abiertas:
                a = abiertas[tipo]
                if valor is not None:
                    a["valor_actual"], a["actualizada_en_utc"] = valor, l.medido_en
                if cierra(l):
                    a["estado"], a["resuelta_en_utc"] = "resuelta", l.medido_en
                    filas.append(abiertas.pop(tipo))
    filas += list(abiertas.values())
    for n, f in enumerate(sorted(filas, key=lambda f: f["iniciada_en_utc"])):
        f["alerta_id"] = id0 + n
    return filas


# ------------------------------------------------------------- generación

def generar(inicio: date, dias: int, semilla: int, intervalo_s: int) -> dict[str, list[dict]]:
    rnd = random.Random(semilla)
    cfg = Config(intervalo_lectura_s=intervalo_s)
    clima = clima_horario(inicio, dias, rnd)
    fin_utc = utc(inicio + timedelta(days=dias), 0)
    datos = {c: [] for c in exportacion.CONJUNTOS}
    datos["clima"] = clima
    for cama in CAMAS:
        lecturas = simular_cama(cama, inicio, dias, intervalo_s, clima, rnd, id0=cama.id * 1_000_000)
        marcas = calcular_marcas(lecturas, cfg)
        por_lectura: dict[int, list[str]] = {}
        for m in marcas:
            por_lectura.setdefault(m.lectura_id, []).append(f"{m.variable}:{m.marca}")
        fuera = excluidas(marcas)
        for seq, l in enumerate(lecturas, start=1):
            lista = sorted(por_lectura.get(l.id, []))
            datos["lecturas"].append({
                "origen": ORIGEN, "lectura_id": l.id, "cama_id": cama.id, "cama": cama.nombre,
                "nodo_id": cama.nodo_id, "seq": seq, "medido_en_utc": l.medido_en,
                "recibido_en_utc": l.medido_en + timedelta(seconds=1), "suelo_pct": l.suelo,
                "suelo_mv": None, "temp_c": l.temp, "hum_aire_pct": l.hum_aire, "luz_lux": None,
                "valida": 1, "motivo_invalida": None, "marcas": ";".join(lista) or None,
                **{f"excluir_{v}": int((l.id, v) in fuera) for v in ("suelo", "temp", "hum_aire")},
                "hueco_antes": int("lectura:hueco" in lista)})
        for a in agregar_horas(cama.id, lecturas, marcas, intervalo_s, fin_utc):
            e = a.estadisticas
            datos["agregados_hora"].append({
                "origen": ORIGEN, "cama_id": cama.id, "cama": cama.nombre, "hora_inicio_utc": a.periodo,
                "variable": a.variable, "media": e.media, "minimo": e.minimo, "maximo": e.maximo,
                "desviacion": e.desviacion, "n_lecturas": e.n, "n_excluidas": a.n_excluidas,
                "n_esperadas": a.n_esperadas, "cobertura": a.cobertura})
        for d in range(dias):
            fecha = inicio + timedelta(days=d)
            ini, fin = limites_dia_local(fecha, ZONA)
            del_dia = [l for l in lecturas if ini <= l.medido_en < fin]
            for a in agregar_dia(cama.id, fecha, del_dia, marcas, intervalo_s, fin_utc, ZONA, cama.rango):
                e = a.estadisticas
                datos["agregados_dia"].append({
                    "origen": ORIGEN, "cama_id": cama.id, "cama": cama.nombre, "fecha": fecha,
                    "variable": a.variable, "media": e.media, "minimo": e.minimo, "maximo": e.maximo,
                    "desviacion": e.desviacion, "amplitud": a.amplitud,
                    "horas_fuera_rango": a.horas_fuera_rango, "n_lecturas": e.n,
                    "n_excluidas": a.n_excluidas, "n_esperadas": a.n_esperadas, "cobertura": a.cobertura})
        for n, e in enumerate(detectar_riegos(puntos_suelo(lecturas, marcas), cfg.riego_umbral_pts,
                                              cfg.riego_ventana_min), start=1):
            datos["eventos_riego"].append({
                "origen": ORIGEN, "evento_id": cama.id * 10_000 + n, "cama_id": cama.id, "cama": cama.nombre,
                "tipo_registro": "detectado", "inicio_utc": e.inicio, "fin_utc": e.fin,
                "humedad_antes": e.humedad_antes, "humedad_despues": e.humedad_despues, "subida": e.subida})
        datos["alertas"] += alertas_simples(cama, lecturas, id0=cama.id * 10_000)
    return datos


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--inicio", type=date.fromisoformat, default=date(2026, 10, 1))
    a.add_argument("--dias", type=int, default=28)
    a.add_argument("--semilla", type=int, default=2026)
    a.add_argument("--intervalo", type=int, default=60, help="segundos entre lecturas (el nodo real: 30)")
    a.add_argument("--parquet", action="store_true", help="además escribe Parquet (necesita pandas y pyarrow)")
    a.add_argument("--salida", type=Path, default=CARPETA)
    args = a.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)
    datos = generar(args.inicio, args.dias, args.semilla, args.intervalo)
    for conjunto, filas in datos.items():
        exportacion.escribir_csv(conjunto, filas, args.salida / f"{conjunto}.csv")
        if args.parquet:
            sys.path.insert(0, str(RAIZ / "tools"))
            from exportar import escribir_parquet
            escribir_parquet(conjunto, filas, args.salida / f"{conjunto}.parquet")
        print(f"{conjunto:15} {len(filas):>8} filas")
    (args.salida / "LEEME.txt").write_text(
        "DATOS SINTÉTICOS (origen = sintetico). No son mediciones reales.\n"
        f"Generados con: python tools/generar_sinteticos.py --inicio {args.inicio} --dias {args.dias} "
        f"--semilla {args.semilla} --intervalo {args.intervalo}\n", encoding="utf-8")
    print(f"Listo (semilla {args.semilla}): {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
