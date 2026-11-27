"""Criterios de aceptación HU-01 a HU-05 de punta a punta:
mensaje MQTT -> procesador -> MariaDB -> estado publicado.

Requieren la BD de test:  docker compose --profile test up -d --wait mariadb_test
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from procesador import repositorio as repo
from procesador.publicador import iso, topico_estado
from procesador.servicio import Procesador
from procesador.validacion import LecturaValidada

from .conftest import CFG, INICIO

pytestmark = pytest.mark.bd
MIN = timedelta(minutes=1)
ZONA = ZoneInfo("America/Santiago")


# =========================================================================
# HU-01 — Última lectura
# =========================================================================

class TestHU01:
    def test_lectura_atrasada_no_reemplaza_a_la_actual(self, huerto, bd):
        """Una lectura medida a las 08:55 que llega a las 09:05 no reemplaza
        a la de las 09:00."""
        cama = huerto.crear_cama("cama-a", "Cama A")
        las_9 = INICIO
        huerto.enviar("cama-a", las_9, suelo=45, seq=10)
        r = huerto.enviar("cama-a", las_9 - 5 * MIN, suelo=40, seq=9,
                          llegada=las_9 + 5 * MIN)

        assert r.estado == "atrasada"
        actual = repo.lectura_actual(bd, cama)
        assert actual["medido_en"] == las_9 and actual["suelo_prom"] == 45
        assert huerto.contar("lecturas") == 2                  # la atrasada va al historial
        assert huerto.tarjeta("cama-a")["lectura"]["medido_en"] == iso(las_9)

    def test_lectura_atrasada_no_genera_alertas(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO, suelo=50, seq=10)
        huerto.enviar("cama-a", INICIO - 5 * MIN, suelo=10, seq=9, llegada=INICIO + MIN)
        assert huerto.alertas(cama) == []

    def test_la_actual_es_la_valida_de_mayor_medido_en(self, huerto, bd):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO, suelo=45)
        # Más nueva, pero inválida (hora en el futuro): no cuenta como actual
        huerto.enviar("cama-a", INICIO + 30 * MIN, suelo=46, llegada=INICIO + MIN)
        assert repo.lectura_actual(bd, cama)["medido_en"] == INICIO

    def test_sin_lecturas(self, huerto, proc):
        huerto.crear_cama("cama-a", "Cama A")
        proc.tick()
        assert huerto.estado("cama-a")["mensaje"] == "Sin lecturas"
        assert huerto.estado("cama-a")["color"] == "gris"
        tarjeta = huerto.tarjeta("cama-a")
        assert tarjeta["lectura"] is None and tarjeta["texto_lectura"] == "Sin lecturas"


# =========================================================================
# HU-02 — Humedad del suelo
# =========================================================================

class TestHU02:
    def test_alerta_de_suelo_seco_con_texto_exacto(self, huerto):
        huerto.crear_cama("cama-b", "Cama B")
        r = huerto.enviar("cama-b", INICIO, suelo=22)
        assert len(r.alertas_nuevas) == 1
        assert r.decisiones[0].mensaje == "Cama B seca: 22 % (ideal 30 % a 70 %)"
        assert huerto.estado("cama-b") == {"color": "rojo", "mensaje": "Revisar: humedad 22 %",
                                           "desde": iso(INICIO + timedelta(seconds=2))}

    def test_exceso_de_agua_con_texto_exacto(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, suelo=85)
        [alerta] = huerto.alertas(cama)
        assert alerta["tipo"] == "suelo_encharcado"
        assert alerta["mensaje"] == "Cama B con exceso de agua: 85 %. No riegues hoy"

    def test_alerta_se_actualiza_sin_duplicarse(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B")
        r1 = huerto.enviar("cama-b", INICIO, suelo=22)
        r2 = huerto.enviar("cama-b", INICIO + MIN, suelo=21)
        r3 = huerto.enviar("cama-b", INICIO + 2 * MIN, suelo=20)

        [alerta] = huerto.alertas(cama)                  # UNA sola alerta
        assert alerta["estado"] == "abierta"
        assert (alerta["valor_inicial"], alerta["valor_actual"]) == (22, 20)
        assert alerta["iniciada_en"] == INICIO
        assert alerta["actualizada_en"] == INICIO + 2 * MIN
        assert alerta["mensaje"] == "Cama B seca: 20 % (ideal 30 % a 70 %)"
        # Solo la primera lectura genera un aviso nuevo
        assert (len(r1.alertas_nuevas), r2.alertas_nuevas, r3.alertas_nuevas) == (1, [], [])
        assert huerto.contar("eventos_alerta", "evento = 'apertura'") == 1

    def test_se_resuelve_al_volver_al_rango_con_histeresis(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, suelo=29)
        huerto.enviar("cama-b", INICIO + 1 * MIN, suelo=30.5)    # ya en rango, pero dentro del margen
        huerto.enviar("cama-b", INICIO + 2 * MIN, suelo=31.9)
        assert huerto.alertas(cama)[0]["estado"] == "abierta"

        huerto.enviar("cama-b", INICIO + 3 * MIN, suelo=32)      # mínimo + 2 puntos
        [alerta] = huerto.alertas(cama)
        assert alerta["estado"] == "resuelta"
        assert alerta["resuelta_en"] == INICIO + 3 * MIN
        assert huerto.estado("cama-b")["mensaje"] == "Todo bien"

    def test_oscilar_en_el_borde_no_genera_avisos_repetidos(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B")
        for i, valor in enumerate([29.8, 30.2, 29.9, 30.1, 29.7, 30.3, 29.9]):
            huerto.enviar("cama-b", INICIO + i * MIN, suelo=valor)
        assert len(huerto.alertas(cama)) == 1
        assert huerto.contar("eventos_alerta") == 1

    def test_cama_sin_cultivo_no_genera_alertas(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B", cultivo=None)
        huerto.enviar("cama-b", INICIO, suelo=5, temp=1)
        assert huerto.alertas(cama) == []
        assert huerto.estado("cama-b")["mensaje"] == "Configura un cultivo para activar las alertas"
        assert huerto.estado("cama-b")["color"] == "sin_configurar"

    def test_rango_personalizado_reemplaza_al_del_cultivo(self, huerto):
        """RF-09: en el norte la banda de humedad puede ser otra."""
        cama = huerto.crear_cama("cama-b", "Cama B", humedad_min=45)
        r = huerto.enviar("cama-b", INICIO, suelo=40)
        assert r.decisiones[0].mensaje == "Cama B seca: 40 % (ideal 45 % a 70 %)"

    def test_nodo_desconocido_crea_su_cama_sin_configurar(self, huerto, bd):
        huerto.enviar("cama-c", INICIO, suelo=5)
        cama = repo.obtener_cama_por_nodo(bd, "cama-c")
        assert cama["nombre"] == "Cama C" and cama["cultivo_id"] is None
        assert huerto.alertas(cama["id"]) == []

    def test_valores_invalidos_no_generan_alertas(self, huerto, bd):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, suelo=-5, temp=150)
        assert huerto.alertas(cama) == []
        with bd.cursor() as cur:
            cur.execute("SELECT suelo_prom, temp, campos_invalidos FROM lecturas")
            fila = cur.fetchone()
        bd.commit()
        assert fila["suelo_prom"] is None and fila["temp"] is None
        assert set(json.loads(fila["campos_invalidos"])) == {"suelo_sonda_1", "temp"}

    def test_salto_imposible_no_genera_alerta(self, huerto):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, suelo=55)
        huerto.enviar("cama-b", INICIO + MIN, suelo=20)          # -35 puntos en 1 minuto
        assert huerto.alertas(cama) == []


# =========================================================================
# HU-03 — Temperatura
# =========================================================================

class TestHU03:
    def test_helada_inmediata_y_resolucion_con_inicio_y_termino(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        r = huerto.enviar("cama-a", INICIO, temp=4)
        assert r.decisiones[0].mensaje == "Riesgo de helada en cama A: 4 °C. Cubre la planta"
        huerto.enviar("cama-a", INICIO + 10 * MIN, temp=16)       # mínimo 15 + 1 °C
        [alerta] = huerto.alertas(cama, "helada")
        assert alerta["estado"] == "resuelta"
        assert (alerta["iniciada_en"], alerta["resuelta_en"]) == (INICIO, INICIO + 10 * MIN)

    def test_calor_por_menos_de_30_minutos_no_alerta(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.serie("cama-a", INICIO, minutos=20, temp=36)
        assert huerto.alertas(cama, "calor") == []

    def test_dos_rachas_breves_no_se_suman(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.serie("cama-a", INICIO, minutos=20, temp=36)
        huerto.enviar("cama-a", INICIO + 25 * MIN, temp=29)
        huerto.serie("cama-a", INICIO + 30 * MIN, minutos=20, temp=36)
        assert huerto.alertas(cama, "calor") == []

    def test_calor_por_mas_de_30_minutos_alerta(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        resultados = huerto.serie("cama-a", INICIO, minutos=40, temp=36)

        [alerta] = huerto.alertas(cama, "calor")
        assert alerta["mensaje"] == "Calor excesivo en cama A: 36 °C. Dale sombra y revisa la humedad"
        assert alerta["iniciada_en"] == INICIO                    # inicio real del calor
        # El aviso sale exactamente al cumplir 30 minutos (lectura 31)
        avisos = [i for i, r in enumerate(resultados) if r.alertas_nuevas]
        assert avisos == [30]

        huerto.enviar("cama-a", INICIO + 50 * MIN, temp=29)       # máximo 30 - 1 °C
        [alerta] = huerto.alertas(cama, "calor")
        assert alerta["estado"] == "resuelta" and alerta["resuelta_en"] == INICIO + 50 * MIN


# =========================================================================
# HU-04 — Luz
# =========================================================================

def insertar_dia_de_luz(bd, cama_id: int, fecha: date, pico_lux: float, cada_min: int = 10,
                        desde_hora: int = 0, hasta_hora: int = 24):
    """Inserta directo en la BD un día de lecturas con forma de campana."""
    seq = int(datetime.combine(fecha, time(0)).timestamp()) // 60
    t_local = datetime.combine(fecha, time(0), tzinfo=ZONA)
    for i in range(0, 24 * 60, cada_min):
        local = t_local + timedelta(minutes=i)
        h = local.hour + local.minute / 60
        if not desde_hora <= h < hasta_hora:
            continue
        lux = max(0.0, math.sin(math.pi * (h - 6.5) / 14)) * pico_lux if 6.5 <= h <= 20.5 else 0.0
        utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        lv = LecturaValidada("x", seq + i, utc, [50.0], 50.0, 20.0, 60.0, round(lux))
        repo.insertar_lectura(bd, cama_id, lv, utc)
    bd.commit()


def medianoche_utc(fecha: date, horas: int = 0) -> datetime:
    local = datetime.combine(fecha, time(horas), tzinfo=ZONA)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


class TestHU04:
    TEXTO = ("Cama B recibe poca luz para tomate. Considera moverla o elegir un "
             "cultivo de sombra, como lechuga")

    def test_tres_dias_de_poca_luz_avisan(self, huerto, bd, proc, reloj):
        cama = huerto.crear_cama("cama-b", "Cama B")
        for d in (23, 24, 25):
            insertar_dia_de_luz(bd, cama, date(2026, 11, d), pico_lux=30000)  # ~5 h de sol directo
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=3)
        proc.tick()

        [alerta] = huerto.alertas(cama, "poca_luz")
        assert alerta["mensaje"] == self.TEXTO
        assert huerto.contar("luz_diaria") == 3
        assert 4.5 < alerta["valor_actual"] < 6                  # horas del último día

    def test_dos_dias_de_poca_luz_no_avisan(self, huerto, bd, proc, reloj):
        cama = huerto.crear_cama("cama-b", "Cama B")
        insertar_dia_de_luz(bd, cama, date(2026, 11, 23), pico_lux=60000)    # buen sol
        for d in (24, 25):
            insertar_dia_de_luz(bd, cama, date(2026, 11, d), pico_lux=30000)
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=3)
        proc.tick()
        assert huerto.alertas(cama, "poca_luz") == []

    def test_dia_con_pocos_datos_no_cuenta_y_corta_la_racha(self, huerto, bd, proc, reloj):
        cama = huerto.crear_cama("cama-b", "Cama B")
        insertar_dia_de_luz(bd, cama, date(2026, 11, 23), pico_lux=30000)
        insertar_dia_de_luz(bd, cama, date(2026, 11, 24), pico_lux=30000, hasta_hora=12)  # nodo caído
        insertar_dia_de_luz(bd, cama, date(2026, 11, 25), pico_lux=30000)
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=3)
        proc.tick()
        assert huerto.alertas(cama, "poca_luz") == []

    def test_el_dia_se_cierra_despues_del_margen_para_lecturas_atrasadas(self, huerto, bd, proc, reloj):
        cama = huerto.crear_cama("cama-b", "Cama B")
        insertar_dia_de_luz(bd, cama, date(2026, 11, 25), pico_lux=30000)
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=1)        # 01:00: aún no
        proc.tick()
        assert huerto.contar("luz_diaria") == 0
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=2)        # 02:00: se cierra
        proc.tick()
        assert huerto.contar("luz_diaria") == 1

    def test_sin_datos_de_luz_hoy(self, huerto):
        huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, lux=None)
        tarjeta = huerto.tarjeta("cama-b")
        assert tarjeta["horas_luz_hoy"] is None
        assert tarjeta["texto_luz"] == "Sin datos de luz hoy"

    def test_horas_de_luz_de_hoy_segun_intervalo_real(self, huerto):
        huerto.crear_cama("cama-b", "Cama B")
        huerto.serie("cama-b", INICIO, minutos=30, cada_s=300, lux=40000)   # 30 min de sol
        assert huerto.tarjeta("cama-b")["texto_luz"] == "0,5 h de luz"

    def test_dia_sin_lecturas_de_luz_queda_sin_datos_y_no_en_cero(self, huerto, bd, proc, reloj):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", medianoche_utc(date(2026, 11, 25), horas=12), lux=None)
        reloj.t = medianoche_utc(date(2026, 11, 26), horas=3)
        proc.tick()
        [dia] = repo.dias_luz_desc(bd, cama, 5)
        assert dia["horas_luz"] is None


# =========================================================================
# HU-05 — Estado de la cama
# =========================================================================

class TestHU05:
    def test_verde_todo_bien(self, huerto):
        huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO)
        assert huerto.estado("cama-a")["color"] == "verde"
        assert huerto.estado("cama-a")["mensaje"] == "Todo bien"

    def test_gris_tiene_prioridad_sobre_rojo(self, huerto, bd):
        cama = huerto.crear_cama("cama-a", "Cama A")
        # Suelo seco (rojo) y el sensor de temperatura no envía nada
        huerto.serie("cama-a", INICIO, minutos=110, cada_s=600, suelo=22, temp=None, hum_aire=None)
        assert huerto.estado("cama-a")["color"] == "rojo"

        huerto.enviar("cama-a", INICIO + 121 * MIN, suelo=22, temp=None, hum_aire=None)
        estado = huerto.estado("cama-a")
        assert (estado["color"], estado["mensaje"]) == ("gris", "Sensor de temperatura sin conexión")
        huerto.proc.tick()                       # la alerta de sensor la abre el ciclo periódico
        [alerta] = huerto.alertas(cama, "sensor_sin_datos")
        assert alerta["variable"] == "temperatura"
        # El estado se publica retenido (para el LED del nodo)
        assert [r for t, _, r in huerto.pub.mensajes if t == topico_estado("cama-a")][-1] is True

        # Vuelve la temperatura: se resuelve y queda el rojo por el suelo
        huerto.enviar("cama-a", INICIO + 122 * MIN, suelo=22, temp=20)
        assert huerto.estado("cama-a")["mensaje"] == "Revisar: humedad 22 %"
        assert huerto.alertas(cama, "sensor_sin_datos")[0]["estado"] == "resuelta"

    def test_nodo_que_deja_de_enviar_pasa_a_gris_por_el_ciclo_periodico(self, huerto, proc, reloj, bd):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO)
        reloj.t = INICIO + 119 * MIN
        proc.tick()
        assert huerto.estado("cama-a")["color"] == "verde"
        reloj.t = INICIO + 121 * MIN
        proc.tick()
        assert huerto.estado("cama-a")["mensaje"] == \
            "Sensores de humedad del suelo y temperatura sin conexión"
        # CQ-06: queda registrada la última lectura válida para medir el tiempo hasta el gris
        with bd.cursor() as cur:
            cur.execute("SELECT * FROM cambios_estado WHERE estado_nuevo = 'gris'")
            cambio = cur.fetchone()
        bd.commit()
        assert cambio["ultima_valida_en"] == INICIO

    def test_reenvio_de_buffer_atrasado_no_abre_alertas_de_sensor_falsas(self, huerto, reloj):
        """El nodo estuvo 3 h sin red y reenvía todo de golpe al volver."""
        cama = huerto.crear_cama("cama-a", "Cama A")
        ahora = INICIO + 3 * timedelta(hours=1)
        for i in range(0, 181, 10):
            huerto.enviar("cama-a", INICIO + i * MIN, llegada=ahora)
        assert huerto.alertas(cama, "sensor_sin_datos") == []
        assert huerto.estado("cama-a")["color"] == "verde"

    def test_cada_cambio_de_estado_se_publica_una_sola_vez(self, huerto):
        huerto.crear_cama("cama-a", "Cama A")
        huerto.serie("cama-a", INICIO, minutos=5)
        assert len(huerto.pub.de_topico(topico_estado("cama-a"))) == 1
        assert huerto.contar("cambios_estado") == 1

    def test_reinicio_del_procesador_no_repite_cambios_de_estado(self, huerto, bd, pub, reloj):
        huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO, suelo=22)
        nuevo = Procesador(bd, CFG, pub, reloj)
        pub.limpiar()
        nuevo.inicializar()
        assert huerto.estado("cama-a")["mensaje"] == "Revisar: humedad 22 %"   # se republica
        assert huerto.contar("cambios_estado") == 1                            # sin duplicar


# =========================================================================
# Deduplicación por seq y mensajes de los nodos
# =========================================================================

class TestDeduplicacion:
    def test_mismo_mensaje_dos_veces_se_guarda_una_vez(self, huerto):
        huerto.crear_cama("cama-a", "Cama A")
        assert huerto.enviar("cama-a", INICIO, seq=7).estado == "guardada"
        assert huerto.enviar("cama-a", INICIO, seq=7).estado == "duplicada"
        assert huerto.contar("lecturas") == 1

    def test_reenvio_del_buffer_con_duplicados_no_pierde_ni_duplica(self, huerto):
        huerto.crear_cama("cama-a", "Cama A")
        lecturas = [(INICIO + i * MIN, 100 + i) for i in range(20)]
        for t, seq in lecturas[:10]:
            huerto.enviar("cama-a", t, seq=seq)
        for t, seq in lecturas[5:]:                  # reconecta y reenvía desde la 5
            huerto.enviar("cama-a", t, seq=seq)
        assert huerto.contar("lecturas") == 20

    def test_contador_reiniciado_queda_como_incidencia(self, huerto):
        huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO, seq=5)
        assert huerto.enviar("cama-a", INICIO + 60 * MIN, seq=5).estado == "seq_reiniciado"
        huerto.enviar("cama-a", INICIO + 61 * MIN, seq=5)
        assert huerto.contar("incidencias", "tipo = 'seq_reiniciado'") == 1   # sin repetir

    def test_mensaje_roto_queda_como_incidencia(self, huerto, proc):
        r = proc.procesar_lectura("huerto/cama/cama-a/lectura", b"{roto")
        assert r.estado == "invalida"
        assert huerto.contar("incidencias", "tipo = 'mensaje_invalido'") == 1
        assert huerto.contar("lecturas") == 0

    def test_heartbeat_y_conexion(self, huerto, proc):
        hb = {"uptime_s": 3600, "rssi": -63, "motivo_reinicio": "TASK_WDT",
              "buffer_pendiente": 0, "heap_libre": 180000}
        proc.procesar_mensaje("huerto/nodo/cama-a/heartbeat", json.dumps(hb).encode())
        proc.procesar_mensaje("huerto/nodo/cama-a/conexion", b"offline", retenido=True)
        proc.procesar_mensaje("huerto/nodo/cama-a/conexion", b"online")
        assert huerto.contar("heartbeats", "motivo_reinicio = 'TASK_WDT'") == 1
        assert huerto.contar("conexiones_nodo") == 1           # el retenido es historia vieja


# =========================================================================
# Cambios de configuración desde el tablero
# =========================================================================

class TestConfiguracion:
    def test_asignar_cultivo_reevalua_la_cama_al_instante(self, huerto, bd, proc):
        cama = huerto.crear_cama("cama-b", "Cama B", cultivo=None)
        huerto.enviar("cama-b", INICIO, suelo=22)
        assert huerto.estado("cama-b")["color"] == "sin_configurar"

        with bd.cursor() as cur:
            cur.execute("UPDATE camas SET cultivo_id = (SELECT id FROM cultivos WHERE nombre='tomate') "
                        "WHERE id = %s", (cama,))
        bd.commit()
        proc.procesar_mensaje("huerto/central/configuracion", json.dumps({"cama_id": cama}).encode())

        [alerta] = huerto.alertas(cama)
        assert alerta["mensaje"] == "Cama B seca: 22 % (ideal 30 % a 70 %)"
        assert huerto.estado("cama-b")["mensaje"] == "Revisar: humedad 22 %"
        assert huerto.tarjeta("cama-b")["cultivo"] == "tomate"

    def test_quitar_el_cultivo_cierra_las_alertas(self, huerto, bd, proc):
        cama = huerto.crear_cama("cama-b", "Cama B")
        huerto.enviar("cama-b", INICIO, suelo=22)
        with bd.cursor() as cur:
            cur.execute("UPDATE camas SET cultivo_id = NULL WHERE id = %s", (cama,))
        bd.commit()
        proc.reevaluar_cama(cama)
        assert huerto.alertas(cama)[0]["estado"] == "resuelta"
        assert huerto.estado("cama-b")["color"] == "sin_configurar"

    def test_aviso_de_configuracion_mal_formado_se_ignora(self, proc):
        assert proc.procesar_mensaje("huerto/central/configuracion", b"basura") is None


# ---------------------------------------------------------------------------
# Lecturas que guardó la API HTTP: el procesador solo aplica las reglas
# ---------------------------------------------------------------------------

class TestLecturaGuardadaPorLaApi:
    def _guardar_por_api(self, huerto, medido_en, seq, suelo, temp=20.0):
        from procesador import ingreso
        cuerpo = json.dumps({"nodo_id": "cama-a", "seq": seq,
                             "medido_en": medido_en.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "temp": temp, "hum_aire": 60, "suelo_pct": suelo, "suelo_mv": 2000})
        r = ingreso.guardar_lectura(huerto.bd, "cama-a", cuerpo, medido_en + timedelta(seconds=2),
                                    huerto.proc.cfg)
        huerto.bd.commit()
        return r.lectura_id

    def test_aviso_abre_la_alerta_de_suelo_seco(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        lectura_id = self._guardar_por_api(huerto, INICIO, 1, suelo=22)
        huerto.reloj.t = INICIO + timedelta(seconds=3)
        r = huerto.proc.procesar_mensaje("huerto/central/lectura",
                                         json.dumps({"lectura_id": lectura_id}).encode())
        assert r.estado == "guardada"
        alerta, = huerto.alertas(cama, "suelo_seco")
        assert alerta["mensaje"] == "Cama A seca: 22 % (ideal 30 % a 70 %)"
        assert huerto.estado("cama-a")["color"] == "rojo"

    def test_aviso_de_lectura_atrasada_no_cambia_el_estado(self, huerto):
        cama = huerto.crear_cama("cama-a", "Cama A")
        huerto.enviar("cama-a", INICIO + 10 * MIN, suelo=50)
        lectura_id = self._guardar_por_api(huerto, INICIO, 99, suelo=22)
        r = huerto.proc.procesar_mensaje("huerto/central/lectura",
                                         json.dumps({"lectura_id": lectura_id}).encode())
        assert r.estado == "atrasada"
        assert huerto.alertas(cama) == []

    def test_aviso_de_lectura_inexistente_se_ignora(self, huerto):
        r = huerto.proc.procesar_mensaje("huerto/central/lectura", b'{"lectura_id": 12345}')
        assert r.estado == "invalida"

    def test_aviso_mal_formado_se_ignora(self, huerto):
        assert huerto.proc.procesar_mensaje("huerto/central/lectura", b"basura") is None


# ---------------------------------------------------------------------------
# Prototipo 1: sin sensor de luz, la luz no pone la cama en gris
# ---------------------------------------------------------------------------

class TestSinSensorDeLuz:
    def test_sin_luz_por_horas_la_cama_sigue_verde(self, huerto, proc, reloj):
        huerto.crear_cama("cama-a", "Cama A")
        huerto.serie("cama-a", INICIO, minutos=180, cada_s=600, lux=None)
        reloj.t = INICIO + 181 * MIN
        proc.tick()
        assert huerto.estado("cama-a")["color"] == "verde"

    def test_con_sensor_de_luz_configurado_si_cuenta(self, bd, pub, reloj):
        from dataclasses import replace

        from procesador.servicio import Procesador

        from .conftest import Huerto
        cfg = replace(CFG, sensores_requeridos="suelo,temperatura,luz")
        huerto = Huerto(bd, Procesador(bd, cfg, pub, reloj), pub, reloj)
        huerto.crear_cama("cama-a", "Cama A")
        huerto.serie("cama-a", INICIO, minutos=130, cada_s=600, lux=None)
        assert huerto.estado("cama-a")["mensaje"] == "Sensor de luz sin conexión"
