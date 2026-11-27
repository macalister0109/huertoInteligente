// Envío de una lectura a la API:  POST API_URL  (Authorization: Bearer API_TOKEN)
#pragma once

#include "buffer.h"

enum class AccionEnvio {
  BORRAR,     // llegó (201 o 200 duplicada) o el servidor la rechaza para siempre (400, 409)
  REINTENTAR  // sin red, servidor caído o token malo: queda en el buffer
};

struct ResultadoEnvio {
  int codigoHttp;   // negativo = error de conexión (ver HTTPClient)
  AccionEnvio accion;
};

ResultadoEnvio enviarLectura(const Registro &r);

// Arma el JSON de la lectura (también se usa en el log)
size_t armarJson(const Registro &r, char *destino, size_t largo);
