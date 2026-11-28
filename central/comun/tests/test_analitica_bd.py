"""Capa de análisis con la BD de test: idempotencia, lecturas crudas intactas,
lecturas atrasadas y migración reversible."""

import hashlib
import json
from datetime import date, datetime, timedelta

import pytest

from comun import migrar
from comun.analitica.proceso import recalcular
from comun.analitica.recalcular import main as comando_recalcular
from procesador.analitica import TareaAnalitica
from pruebas.bd import CFG

pytestmark = pytest.mark.bd

FECHA = date(2026, 11, 26)
INICIO_DIA = datetime(2026, 11, 26, 3, 0)       # 00:00 en Chile (UTC-3)


def ejecutar(bd, sql, args=()):
    with bd.cursor() as cur:
        cur.execute(sql, args)
        filas = cur.fetchall()
        ultimo = cur.lastrowid
    bd.commit()
    return filas, ultimo


def crear_cama(bd):
    _, cama_id = ejecutar(bd, """INSERT INTO camas (nombre, nodo_id, cultivo_id)
                                 VALUES ('Cama A', 'cama-a', (SELECT id FROM cultivos WHERE nombre = 'tomate'))""")
    return cama_id


def insertar(bd, cama_id, lecturas, recibido_en=None):
    """lecturas: lista de (medido_en, suelo, temp, hum, campos_invalidos)."""
    with bd.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM lecturas WHERE cama_id = %s", (cama_id,))
        seq = cur.fetchone()["s"]
        for medido, suelo, temp, hum, invalidos in lecturas:
            seq += 1
            cur.execute("""INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom,
                                                 temp, hum_aire, campos_invalidos)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (cama_id, seq, medido, recibido_en or medido, suelo, temp, hum,
                         json.dumps(invalidos) if invalidos else None))
    bd.commit()


def huella_lecturas(bd):
    filas, _ = ejecutar(bd, "SELECT * FROM lecturas ORDER BY id")
    return hashlib.sha256(repr(filas).encode()).hexdigest()


def contar(bd, tabla):
    filas, _ = ejecutar(bd, f"SELECT COUNT(*) AS n FROM {tabla}")
    return filas[0]["n"]


def dia_tipico(bd, cama_id):
    lecturas = []
    for i in range(0, 24 * 120, 2):                      # cada 1 min (cobertura 50 %, sin huecos)
        t = INICIO_DIA + timedelta(seconds=30 * i)
        lecturas.append((t, 60 - i / 200, 15 + (i // 120) % 12, 50.0 + (i // 4) % 9, None))
    lecturas[10] = (lecturas[10][0], None, 20.0, 55.0,
                    {"suelo_sonda_1": {"valor": 150, "tipo": "rango", "detalle": "fuera de rango"}})
    insertar(bd, cama_id, lecturas)


def test_recalcular_es_idempotente_y_no_toca_las_lecturas(bd):
    cama = crear_cama(bd)
    dia_tipico(bd, cama)
    antes = huella_lecturas(bd)
    ahora = INICIO_DIA + timedelta(days=2)

    r1 = recalcular(bd, CFG, FECHA, FECHA, ahora)
    conteos = [contar(bd, t) for t in ("calidad_lecturas", "agregados_hora", "agregados_dia")]
    r2 = recalcular(bd, CFG, FECHA, FECHA, ahora)
    assert [contar(bd, t) for t in ("calidad_lecturas", "agregados_hora", "agregados_dia")] == conteos
    assert (r1.filas_hora, r1.filas_dia, r1.marcas) == (r2.filas_hora, r2.filas_dia, r2.marcas)
    assert conteos[1] == 24 * 3 and conteos[2] == 3
    assert huella_lecturas(bd) == antes                    # la fuente de verdad sigue igual

    filas, _ = ejecutar(bd, "SELECT * FROM agregados_dia WHERE variable = 'suelo'")
    suelo = filas[0]
    assert suelo["n_lecturas"] == 1439 and suelo["n_excluidas"] == 1
    assert suelo["n_esperadas"] == 2880 and suelo["cobertura"] == pytest.approx(1439 / 2880, abs=1e-4)
    assert suelo["horas_fuera_rango"] is not None          # tomate: 30 a 70 %
    filas, _ = ejecutar(bd, "SELECT * FROM calidad_lecturas")
    assert {(f["variable"], f["marca"]) for f in filas} == {("suelo", "rango")}


def test_pegado_que_cruza_la_medianoche_se_detecta(bd):
    cama = crear_cama(bd)
    # 2 h antes y 2 h después de la medianoche con el mismo valor (4 h > 3 h)
    medianoche = INICIO_DIA + timedelta(days=1)
    insertar(bd, cama, [(medianoche + timedelta(minutes=m), 42.0, 20.0 + (m % 3), 50.0 + (m % 4), None)
                        for m in range(-120, 120)])
    recalcular(bd, CFG, FECHA + timedelta(days=1), FECHA + timedelta(days=1), medianoche + timedelta(days=1))
    filas, _ = ejecutar(bd, "SELECT COUNT(*) AS n FROM calidad_lecturas WHERE marca = 'pegado'")
    assert filas[0]["n"] == 120                            # solo se escriben las del día pedido


def test_recalcular_un_rango_y_una_cama(bd):
    cama = crear_cama(bd)
    dia_tipico(bd, cama)
    r = recalcular(bd, CFG, FECHA - timedelta(days=1), FECHA + timedelta(days=1),
                   INICIO_DIA + timedelta(days=3), cama_id=cama)
    assert r.dias == 3 and r.filas_dia == 3                # días sin datos no dejan filas
    with pytest.raises(ValueError):
        recalcular(bd, CFG, FECHA, FECHA - timedelta(days=1), INICIO_DIA)


def test_comando_recalcular(bd, monkeypatch, capsys):
    cama = crear_cama(bd)
    dia_tipico(bd, cama)
    for clave, valor in {"DB_HOST": CFG.db_host, "DB_PORT": str(CFG.db_puerto), "MARIADB_USER": CFG.db_usuario,
                         "MARIADB_PASSWORD": CFG.db_clave, "MARIADB_DATABASE": CFG.db_nombre}.items():
        monkeypatch.setenv(clave, valor)
    assert comando_recalcular(["--desde", "2026-11-26", "--hasta", "2026-11-26"]) == 0
    assert "1 cama(s), 1 día(s)" in capsys.readouterr().out
    assert contar(bd, "agregados_dia") == 3


def test_tarea_recalcula_los_dias_de_las_lecturas_atrasadas(bd):
    cama = crear_cama(bd)
    ahora = INICIO_DIA + timedelta(days=1, hours=15)
    insertar(bd, cama, [(ahora - timedelta(minutes=m), 50.0, 20.0, 50.0, None) for m in range(10)])
    tarea = TareaAnalitica(CFG, cada_min=5)
    tarea.ejecutar(bd, ahora)
    assert contar(bd, "agregados_dia") == 3                # hoy

    # Llega el buffer del nodo con lecturas medidas AYER
    insertar(bd, cama, [(INICIO_DIA + timedelta(hours=10, minutes=m), 55.0, 18.0, 60.0, None)
                        for m in range(30)], recibido_en=ahora + timedelta(minutes=2))
    assert tarea.ejecutar(bd, ahora + timedelta(minutes=3)).dias == 0     # todavía no le toca
    r = tarea.ejecutar(bd, ahora + timedelta(minutes=6))
    # Ayer (por las atrasadas) y hoy (margen de 1 min para no perder lecturas en el borde)
    assert r.dias == 2
    filas, _ = ejecutar(bd, "SELECT fecha FROM agregados_dia GROUP BY fecha ORDER BY fecha")
    assert [f["fecha"] for f in filas] == [FECHA, FECHA + timedelta(days=1)]


def test_tarea_sin_lecturas_no_hace_nada(bd):
    assert TareaAnalitica(CFG).ejecutar(bd, INICIO_DIA).dias == 0


def test_vista_de_clima_por_hora(bd):
    for minuto in (5, 35):
        ejecutar(bd, """INSERT INTO clima_referencia (fuente, observado_en, obtenido_en, lat, lon,
                                                      temp_aire_c, precipitacion_mm)
                        VALUES ('open-meteo', %s, %s, -33.54, -70.64, %s, 0.5)""",
                 (INICIO_DIA + timedelta(minutes=minuto), INICIO_DIA, 20 + minuto / 5))
    filas, _ = ejecutar(bd, "SELECT * FROM v_clima_hora")
    assert len(filas) == 1
    assert filas[0]["hora_inicio"] == INICIO_DIA and filas[0]["n_instantaneas"] == 2
    assert filas[0]["temp_aire_c"] == pytest.approx(24.0) and filas[0]["precipitacion_mm"] == 1.0


def test_migracion_004_se_revierte_sin_tocar_las_lecturas(bd):
    cama = crear_cama(bd)
    dia_tipico(bd, cama)
    antes = huella_lecturas(bd)
    migrar.revertir(bd, "004_calidad_agregados.sql")
    assert huella_lecturas(bd) == antes
    assert "004_calidad_agregados.sql" in migrar.migrar(bd)
    assert contar(bd, "agregados_hora") == 0


# ------------------------------------------------------------------- riegos

def dia_con_riegos(bd, cama_id):
    """Secado lento, riego a las 08:00 y a las 18:00 (hora de Chile), una lectura por minuto."""
    lecturas, humedad = [], 35.0
    for m in range(24 * 60):
        t = INICIO_DIA + timedelta(minutes=m)
        if m in (8 * 60, 18 * 60):
            humedad += 8
        elif m in (8 * 60 + 1, 18 * 60 + 1):
            humedad += 7
        else:
            humedad -= 0.02
        lecturas.append((t, round(humedad, 2), 20.0 + (m % 5), 50.0 + (m % 7), None))
    insertar(bd, cama_id, lecturas)


def riegos_en_bd(bd):
    filas, _ = ejecutar(bd, "SELECT * FROM eventos_riego ORDER BY inicio")
    return filas


def test_riegos_detectados_sin_duplicar_y_con_id_estable(bd):
    cama = crear_cama(bd)
    dia_con_riegos(bd, cama)
    ahora = INICIO_DIA + timedelta(days=2)
    r = recalcular(bd, CFG, FECHA, FECHA, ahora)
    primero = riegos_en_bd(bd)
    assert r.riegos == 2 and len(primero) == 2
    assert [f["inicio"] for f in primero] == [INICIO_DIA + timedelta(hours=8, minutes=-1),
                                              INICIO_DIA + timedelta(hours=18, minutes=-1)]
    assert all(f["origen"] == "detectado" and f["humedad_despues"] - f["humedad_antes"] >= 10
               for f in primero)

    recalcular(bd, CFG, FECHA, FECHA, ahora + timedelta(hours=1))
    segundo = riegos_en_bd(bd)
    assert [f["id"] for f in segundo] == [f["id"] for f in primero]      # mismos id, sin duplicar


def test_recalcular_no_borra_riegos_manuales(bd):
    cama = crear_cama(bd)
    dia_con_riegos(bd, cama)
    ejecutar(bd, """INSERT INTO eventos_riego (cama_id, origen, inicio, fin, notas, calculado_en)
                    VALUES (%s, 'manual', %s, %s, 'regado con manguera', %s)""",
             (cama, INICIO_DIA + timedelta(hours=12), INICIO_DIA + timedelta(hours=12), INICIO_DIA))
    recalcular(bd, CFG, FECHA, FECHA, INICIO_DIA + timedelta(days=2))
    assert sorted(f["origen"] for f in riegos_en_bd(bd)) == ["detectado", "detectado", "manual"]


def test_un_riego_que_ya_no_se_detecta_se_borra(bd):
    cama = crear_cama(bd)
    dia_con_riegos(bd, cama)
    recalcular(bd, CFG, FECHA, FECHA, INICIO_DIA + timedelta(days=2))
    assert len(riegos_en_bd(bd)) == 2
    con_umbral_alto = type(CFG)(**{**CFG.__dict__, "riego_umbral_pts": 20.0})
    recalcular(bd, con_umbral_alto, FECHA, FECHA, INICIO_DIA + timedelta(days=2))
    assert len(riegos_en_bd(bd)) == 0


def test_vista_de_tramos_de_secado(bd):
    cama = crear_cama(bd)
    dia_con_riegos(bd, cama)
    recalcular(bd, CFG, FECHA, FECHA, INICIO_DIA + timedelta(days=2))
    filas, _ = ejecutar(bd, "SELECT * FROM v_tramos_secado ORDER BY inicio_tramo")
    assert len(filas) == 2
    assert filas[0]["fin_tramo"] == filas[1]["inicio_tramo"] - timedelta(minutes=1) or \
        filas[0]["fin_tramo"] < filas[1]["inicio_tramo"]
    assert filas[1]["fin_tramo"] is None                                   # tramo en curso


def test_migracion_005_se_revierte(bd):
    migrar.revertir(bd, "005_eventos_riego.sql")
    assert "005_eventos_riego.sql" in migrar.migrar(bd)


# ------------------------------------------------- predicción y alerta preventiva

def preparar_secado(bd, ahora):
    """Cama A (tomate, mínimo 30 %) que se seca 1 punto por hora y hoy está en 34 %."""
    cama = crear_cama(bd)
    insertar(bd, cama, [(ahora - timedelta(minutes=m), round(34 + m / 60, 3), 20.0 + m % 3, 50.0 + m % 5, None)
                        for m in range(6 * 60, -1, -1)])
    return cama


def procesador_con_tendencia(bd, ahora):
    from procesador.publicador import PublicadorMemoria
    from procesador.servicio import Procesador
    from procesador.tendencia import TareaTendencia
    from pruebas.bd import Reloj
    pub = PublicadorMemoria()
    return Procesador(bd, CFG, pub, Reloj(ahora), tarea_tendencia=TareaTendencia(CFG)), pub


def test_alerta_preventiva_desactivada_por_defecto_pero_mide_cq13(bd):
    ahora = INICIO_DIA + timedelta(hours=20)
    cama = preparar_secado(bd, ahora)
    proc, _ = procesador_con_tendencia(bd, ahora)
    proc.tick()
    assert contar(bd, "alertas") == 0
    filas, _ = ejecutar(bd, "SELECT * FROM tiempos_tendencia")
    assert len(filas) == 1 and filas[0]["cama_id"] == cama
    assert filas[0]["estado"] == "estimacion" and filas[0]["horas"] == pytest.approx(4, abs=0.05)
    assert filas[0]["duracion_ms"] < 1000                                  # CQ-13


def test_alerta_preventiva_activada_abre_sin_duplicar_y_no_pone_rojo(bd):
    from comun import ajustes
    ahora = INICIO_DIA + timedelta(hours=20)
    cama = preparar_secado(bd, ahora)
    ajustes.guardar(bd, {"tendencia_activa": "sí"})
    bd.commit()
    proc, pub = procesador_con_tendencia(bd, ahora)
    proc.tick()
    proc.tarea_tendencia._ultima = None          # forzar otra pasada
    proc.tick()
    filas, _ = ejecutar(bd, "SELECT * FROM alertas")
    assert len(filas) == 1 and filas[0]["tipo"] == "tendencia_secado" and filas[0]["estado"] == "abierta"
    assert filas[0]["mensaje"].startswith("Al ritmo actual, la Cama A llegaría a 30 % en unas 4 h")
    assert proc.estados[cama][0] == "verde"                                # preventiva: no es rojo
    assert pub.ultimo("huerto/tablero/cama/cama-a") is not None          # el tablero se actualizó


def test_endpoint_de_tendencia_incluye_la_prediccion(bd):
    from comun.analitica.servicio_tendencia import parametros, predecir_cama, prediccion_json
    from comun.analitica import repositorio as repo
    ahora = INICIO_DIA + timedelta(hours=20)
    cama = preparar_secado(bd, ahora)
    pred, ms = predecir_cama(bd, repo.camas(bd, cama)[0], ahora, parametros(CFG))
    j = prediccion_json(pred, "Cama A", ms)
    assert j["texto"] == "Al ritmo actual, la Cama A llegaría a 30 % en unas 4 h (estimación)"
    assert j["recta"][1]["valor"] == pytest.approx(30, abs=0.1) and ms < 1000


def test_migracion_006_se_revierte(bd):
    migrar.revertir(bd, "006_tendencias.sql")
    assert "006_tendencias.sql" in migrar.migrar(bd)
