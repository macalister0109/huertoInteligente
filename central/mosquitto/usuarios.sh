#!/usr/bin/env bash
# Administra los usuarios de Mosquitto (archivo config/passwd, que NO se versiona).
#
# Uso (desde la carpeta central/):
#   ./mosquitto/usuarios.sh servicios        crea procesador, web y simulador con las claves del .env
#   ./mosquitto/usuarios.sh nodo cama-a      crea el usuario del nodo y muestra su clave para config.h
#   ./mosquitto/usuarios.sh borrar cama-a    elimina un usuario
#   ./mosquitto/usuarios.sh listar           lista los usuarios
#
# Usa la imagen de Mosquitto, así que no hay que instalar nada en la Pi.
set -euo pipefail

# Git Bash en Windows convierte las rutas /mosquitto/... : se desactiva.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."            # carpeta central/
ARCHIVO=mosquitto/config/passwd
IMAGEN=eclipse-mosquitto:2

if [[ ! -f .env ]]; then
    echo "Falta central/.env (copia .env.example y edítalo)." >&2
    exit 1
fi
set -a; source .env; set +a

touch "$ARCHIVO"

en_contenedor() {
    docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" "$IMAGEN" sh -c "$1"
}

passwd_cmd() {
    # Mosquitto exige que passwd no sea legible por otros usuarios (en Linux).
    # En Windows el chmod no tiene efecto y solo queda una advertencia.
    docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" "$IMAGEN" sh -c \
        'set -o pipefail
         # mosquitto_passwd advierte que el dueño no es root: se oculta ese aviso.
         mosquitto_passwd "$@" 2>&1 | { grep -v -e "Future versions" -e "To fix this" || true; }
         estado=$?
         # mosquitto_passwd REESCRIBE el archivo como root (0600). El broker corre como
         # usuario "mosquitto" y debe poder leerlo: el dueño se corrige DESPUÉS de escribir.
         # (En Windows no se nota porque Docker Desktop ignora estos permisos.)
         chown mosquitto:mosquitto /mosquitto/config/passwd
         chmod 0700 /mosquitto/config/passwd
         exit $estado' _ "$@"
}

recargar() {
    # Mosquitto relee passwd y acl con SIGHUP, sin cortar las conexiones
    if docker compose ps --status running mosquitto 2>/dev/null | grep -q mosquitto; then
        docker compose kill -s HUP mosquitto >/dev/null 2>&1 && echo "Mosquitto recargado."
    fi
}

validar_id() {
    if [[ ! "$1" =~ ^[a-z0-9-]{1,40}$ ]]; then
        echo "Identificador inválido: usa minúsculas, números y guiones (ej. cama-a)." >&2
        exit 1
    fi
    # Un nodo con nombre de servicio heredaría sus permisos de la ACL
    case "$1" in
        procesador|web|simulador|"$MQTT_USER_PROCESADOR"|"$MQTT_USER_WEB"|"$MQTT_USER_SIMULADOR")
            echo "'$1' está reservado para un servicio." >&2; exit 1 ;;
    esac
}

case "${1:-}" in
    servicios)
        passwd_cmd -b /mosquitto/config/passwd "$MQTT_USER_PROCESADOR" "$MQTT_PASS_PROCESADOR"
        passwd_cmd -b /mosquitto/config/passwd "$MQTT_USER_WEB" "$MQTT_PASS_WEB"
        if [[ -n "${MQTT_PASS_SIMULADOR:-}" ]]; then
            passwd_cmd -b /mosquitto/config/passwd "$MQTT_USER_SIMULADOR" "$MQTT_PASS_SIMULADOR"
        fi
        echo "Usuarios de servicios creados."
        recargar
        ;;
    nodo)
        validar_id "${2:-}"
        clave=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
        passwd_cmd -b /mosquitto/config/passwd "$2" "$clave"
        echo "Nodo '$2' creado. Copia en firmware/include/config.h:"
        echo "  #define NODO_ID   \"$2\""
        echo "  #define MQTT_USER \"$2\""
        echo "  #define MQTT_PASS \"$clave\""
        recargar
        ;;
    borrar)
        validar_id "${2:-}"
        passwd_cmd -D /mosquitto/config/passwd "$2"
        echo "Usuario '$2' eliminado."
        recargar
        ;;
    listar)
        en_contenedor 'cut -d: -f1 /mosquitto/config/passwd'
        ;;
    *)
        sed -n '2,10p' "$0"
        exit 1
        ;;
esac
