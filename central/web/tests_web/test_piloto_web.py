"""Formulario «Sumarse al piloto»: POST /api/piloto envía el correo por SMTP."""

from __future__ import annotations

import smtplib
from datetime import timedelta

import pytest

from pruebas.bd import CFG, INICIO
from web import crear_app, rutas_piloto
from web.config import ConfigWeb

SMTP = dict(piloto_correo="macarena@mjamett.cl", smtp_host="mail.mjamett.cl",
            smtp_usuario="no-responder@mjamett.cl", smtp_clave="secreta")

SOLICITUD = {"nombre": "Ana Pérez", "estamento": "Docente", "correo": "ana@colegio.cl",
             "comentario": "Propongo lechugas.\nY cilantro.", "sitio_web": ""}


class Buzon:
    def __init__(self):
        self.enviados = []
        self.falla = None

    def __call__(self, cfg, mensaje):
        if self.falla:
            raise self.falla
        self.enviados.append(mensaje)


@pytest.fixture
def buzon():
    return Buzon()


@pytest.fixture
def crear(difusor, reloj, buzon):
    rutas_piloto.reiniciar_limites()

    def _crear(**cfg):
        app = crear_app(ConfigWeb(bd=CFG, clave_sesion="x", **cfg), difusor=difusor,
                        conectar_bd=lambda: None, reloj=reloj, enviar_correo=buzon)
        return app.test_client()
    return _crear


@pytest.fixture
def cliente(crear):
    return crear(**SMTP)


def enviar(cliente, **cambios):
    return cliente.post("/api/piloto", json={**SOLICITUD, **cambios})


def test_envia_el_correo_al_equipo(cliente, buzon):
    r = enviar(cliente)
    assert r.status_code == 200 and r.get_json() == {"estado": "enviado"}
    m, = buzon.enviados
    assert m["To"] == "macarena@mjamett.cl"
    assert m["Subject"] == "Quiero sumarme al piloto smartYusChaMau (Docente)"
    assert "no-responder@mjamett.cl" in m["From"]
    assert m["Reply-To"] == "Ana Pérez <ana@colegio.cl>"
    texto = m.get_content()
    for linea in ("Nombre: Ana Pérez", "Estamento: Docente", "Correo: ana@colegio.cl",
                  "Propongo lechugas.\nY cilantro.", "Enviado el 26-11-2026 a las 12:00"):
        assert linea in texto


def test_remitente_propio(crear, buzon):
    enviar(crear(**SMTP, smtp_remitente="huerto@mjamett.cl"))
    assert "huerto@mjamett.cl" in buzon.enviados[0]["From"]


@pytest.mark.parametrize("cambios, texto", [
    ({"nombre": "A"}, "nombre completo"),
    ({"estamento": "Rector"}, "estamento"),
    ({"correo": "ana@"}, "correo"),
    ({"correo": "ana@colegio.cl\nBcc: x@y.cl"}, "correo"),
])
def test_datos_invalidos_no_se_envian(cliente, buzon, cambios, texto):
    r = enviar(cliente, **cambios)
    assert r.status_code == 400 and texto in r.get_json()["error"]
    assert buzon.enviados == []


def test_un_nombre_con_saltos_de_linea_no_inyecta_cabeceras(cliente, buzon):
    enviar(cliente, nombre="Ana\r\nBcc: espia@x.cl")
    m, = buzon.enviados
    assert m["Bcc"] is None and "\n" not in m["Reply-To"]


def test_campo_trampa_lleno_finge_exito_sin_enviar(cliente, buzon):
    r = enviar(cliente, sitio_web="http://spam.example")
    assert r.status_code == 200 and buzon.enviados == []


def test_json_mal_formado(cliente, buzon):
    r = cliente.post("/api/piloto", data="hola", content_type="application/json")
    assert r.status_code == 400 and buzon.enviados == []


def test_otro_sitio_no_puede_usar_el_formulario(cliente, buzon):
    r = cliente.post("/api/piloto", json=SOLICITUD, headers={"Origin": "https://spam.example"})
    assert r.status_code == 403 and buzon.enviados == []
    r = cliente.post("/api/piloto", json=SOLICITUD, headers={"Origin": "http://localhost"})
    assert r.status_code == 200


def test_limite_por_ip(cliente, buzon, reloj):
    for _ in range(3):
        assert enviar(cliente).status_code == 200
    r = enviar(cliente)
    assert r.status_code == 429 and "Espera unos minutos" in r.get_json()["error"]
    reloj.t = INICIO + timedelta(minutes=16)
    assert enviar(cliente).status_code == 200
    assert len(buzon.enviados) == 4


def test_sin_smtp_responde_503_con_el_correo_para_escribir_directo(crear, buzon):
    r = enviar(crear(piloto_correo="macarena@mjamett.cl"))
    assert r.status_code == 503 and r.get_json()["correo"] == "macarena@mjamett.cl"
    assert buzon.enviados == []


@pytest.mark.parametrize("falla", [smtplib.SMTPAuthenticationError(535, b"mala clave"),
                                   TimeoutError("sin respuesta"), ConnectionRefusedError(),
                                   UnicodeEncodeError("ascii", "contraseña", 6, 7, "ordinal not in range")])
def test_si_el_smtp_falla_responde_503(cliente, buzon, falla):
    buzon.falla = falla
    r = enviar(cliente)
    assert r.status_code == 503 and r.get_json()["correo"] == "macarena@mjamett.cl"


def test_smtp_desde_el_env():
    cfg = ConfigWeb.desde_entorno({"SMTP_HOST": "mail.mjamett.cl", "SMTP_PUERTO": "587",
                                   "SMTP_USUARIO": "no-responder@mjamett.cl", "SMTP_CLAVE": "x"})
    assert cfg.smtp_configurado and cfg.smtp_puerto == 587
    assert not ConfigWeb.desde_entorno({}).smtp_configurado
    assert ConfigWeb.desde_entorno({}).smtp_puerto == 465


class SmtpFalso:
    instancias: list = []

    def __init__(self, host, puerto, **kw):
        self.host, self.puerto, self.pasos = host, puerto, []
        SmtpFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.pasos.append("cerrar")

    def starttls(self, context=None):
        self.pasos.append("starttls")

    def login(self, usuario, clave):
        self.pasos.append(f"login {usuario}")

    def send_message(self, mensaje):
        self.pasos.append(f"enviar {mensaje['To']}")


@pytest.mark.parametrize("puerto, clase, pasos", [
    (465, "SMTP_SSL", ["login no-responder@mjamett.cl", "enviar macarena@mjamett.cl", "cerrar"]),
    (587, "SMTP", ["starttls", "login no-responder@mjamett.cl", "enviar macarena@mjamett.cl", "cerrar"]),
])
def test_enviar_smtp(monkeypatch, puerto, clase, pasos):
    from email.message import EmailMessage

    from web import correo
    SmtpFalso.instancias = []
    monkeypatch.setattr(correo.smtplib, clase, SmtpFalso)
    m = EmailMessage()
    m["To"] = "macarena@mjamett.cl"
    m.set_content("hola")
    correo.enviar_smtp(ConfigWeb(**SMTP, smtp_puerto=puerto), m)
    s, = SmtpFalso.instancias
    assert (s.host, s.puerto, s.pasos) == ("mail.mjamett.cl", puerto, pasos)
