# Nota para continuar el lunes 30-11-2026

**Escrita:** sábado 28-11-2026, 11:20  ·  **Versión en el servidor:** `625d4df`
(migración 008 aplicada)  ·  Estado completo en [ESTADO_DESPLIEGUE.md](ESTADO_DESPLIEGUE.md).

## Dónde quedamos

- La Cama A envía lecturas cada 30 s a https://huerto.mjvirtual.cl sin cortes importantes.
- **El % de humedad lo calcula el servidor**, con una calibración **provisional**:
  seco 3160 mV = 0 %, mojado 980 mV = 100 %. El sábado a las 11:16 marcaba 1422 mV → 79,7 %.
- El «mojado» de 980 mV es el valor más bajo registrado (27-11, 17:42), no una medición con la
  tierra saturada. Por eso los % todavía no son confiables: sirven para ver si la humedad sube o
  baja.
- En esta sonda, **menos mV = más húmedo**. Del viernes en la noche al sábado en la mañana bajó de
  1700 a 1422 mV: la sonda indica que la tierra **se humedeció**, aunque no se regó (por confirmar).

## Lunes: pasos en orden

### 1. Revisar el fin de semana (antes de tocar nada)

- En https://huerto.mjvirtual.cl/cama/1, gráfico de 7 días: ¿la humedad bajó de día y subió de
  noche? ¿Siguió subiendo sin riego?
  - Si **sube sin riego todo el tiempo**, sospechar de la sonda (corrosión o deriva): revisar la
    sonda YL-69 al sacarla.
- Anotar los mV de ahora en `/api/camas/cama-a/ultima` (`suelo_mv`), para comparar después del
  riego.

### 2. Recalibrar el «mojado» (sin conectar la placa al PC)

1. Regar bien alrededor de la sonda hasta que la tierra quede **saturada** (que no absorba más).
2. Esperar **unos 5 minutos** para que la lectura se estabilice.
3. Entrar a https://huerto.mjvirtual.cl/configuracion/ con el PIN.
4. En «Calibración de la sonda de suelo de Cama A», dejar marcada **«Aplicar también a las
   lecturas ya guardadas»** y apretar **«Usar la lectura actual como mojado»**.
5. Comprobar el mensaje verde: dice cuántos mV se usaron (el promedio de las últimas lecturas) y
   cuántas lecturas del historial cambiaron. Ahora la cama debería marcar cerca de 100 %.
6. El «seco» (3160 mV, la sonda al aire) se deja como está.

### 3. Revisar en los días siguientes

- Que la curva **baje entre riegos** (la tierra se seca) y que los riegos aparezcan como
  «Riego detectado».
- Que la tendencia diga «Bajando» y estime las horas hasta el mínimo cuando se está secando.
- Configurar el cultivo de la Cama A en `/configuracion` (hoy está sin cultivo, así que no hay
  avisos).

### 4. Cuando haya tiempo (no urgente)

- Copiar los valores finales en `firmware/nodo/config.h` (`SUELO_MV_SECO` y `SUELO_MV_MOJADO`) y
  volver a subir el programa: la OLED y el LED de la placa siguen con mojado 2042 mV y muestran
  100 %.
- Correo del formulario de la portada: ya quedó `macarena@mjamett.cl` por defecto en el código.
  Si no se desplegó el fin de semana: `git pull` y `docker compose up -d --build web` (desde
  `~/huertoInteligente/central`, sin migraciones) y comprobar que la portada ya no avisa que falta
  el correo.
- Revisar los registros del procesador: `docker compose logs --tail 50 procesador` (sin `ERROR`).
- La instalación del 27-11 (la sonda al aire, de 0 % a 100 %) aparece como un «Riego detectado»
  falso. Si molesta, se puede marcar ese tramo como «instalación» para que no cuente.
