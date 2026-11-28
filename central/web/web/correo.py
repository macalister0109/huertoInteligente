"""Envío de correos por SMTP (formulario «Sumarse al piloto»)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .config import ConfigWeb

TIMEOUT_SMTP_S = 20


def enviar_smtp(cfg: ConfigWeb, mensaje: EmailMessage) -> None:
    contexto_tls = ssl.create_default_context()
    if cfg.smtp_puerto == 465:
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_puerto, context=contexto_tls,
                              timeout=TIMEOUT_SMTP_S) as smtp:
            smtp.login(cfg.smtp_usuario, cfg.smtp_clave)
            smtp.send_message(mensaje)
    else:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_puerto, timeout=TIMEOUT_SMTP_S) as smtp:
            smtp.starttls(context=contexto_tls)
            smtp.login(cfg.smtp_usuario, cfg.smtp_clave)
            smtp.send_message(mensaje)
