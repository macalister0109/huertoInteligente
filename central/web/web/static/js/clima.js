/* Clima exterior de REFERENCIA (no es un pronóstico).
 *
 * El navegador nunca llama a la API externa: pide /api/clima/... al equipo
 * central. Este archivo se carga aparte: si falla o el clima no está
 * disponible, las camas se ven igual que siempre.
 */
"use strict";

const HuertoClima = (() => {
  const H = Huerto;

  const num = (v, unidad) => (v === null || v === undefined ? null : `${H.entero(v)} ${unidad}`);

  /** Bloque de la cabecera del tablero: temperatura, humedad, radiación, lluvia, fuente y hora. */
  function dibujarResumen(contenedor, datos) {
    const c = datos && datos.clima;
    if (!c) {
      contenedor.className = "clima-exterior sin-clima";
      contenedor.replaceChildren(H.el("p", { class: "clima-estado" },
        (datos && datos.texto_estado) || "Clima exterior no disponible"));
      contenedor.hidden = false;
      return;
    }
    const valores = [
      ["Temperatura", num(c.temp_aire_c, "°C")],
      ["Humedad del aire", num(c.hum_rel_pct, "%")],
      ["Sol (radiación)", num(c.radiacion_wm2, "W/m²")],
      ["Lluvia (última hora)", c.precipitacion_mm === null ? null : `${H.decimal(c.precipitacion_mm)} mm`],
    ].filter(([, v]) => v !== null);
    contenedor.className = `clima-exterior estado-clima-${datos.estado}`;
    contenedor.replaceChildren(
      H.el("h2", {}, "Afuera, en la zona"),
      H.el("dl", { class: "clima-valores" },
        valores.map(([etiqueta, v]) => H.el("div", {}, H.el("dt", {}, etiqueta), H.el("dd", {}, v)))),
      datos.et0 ? H.el("p", { class: "clima-et0" }, `${datos.et0}.`) : null,
      H.el("p", { class: "clima-estado" }, datos.texto_estado));
    contenedor.hidden = false;
  }

  async function cargarResumen(contenedor) {
    if (!contenedor) return;
    try {
      dibujarResumen(contenedor, await H.obtenerJson("/api/clima/actual"));
    } catch (e) {
      dibujarResumen(contenedor, null);
    }
  }

  /** Una línea para la tarjeta de cama: «Afuera 25 °C · +3 °C más que afuera». */
  function lineaTarjeta(comp) {
    if (!comp) return null;
    const t = comp.temperatura;
    const partes = [];
    if (t) partes.push(H.el("span", {}, `Afuera ${H.entero(t.externo)} °C · `, H.el("strong", {}, t.texto)));
    else if (comp.humedad_aire) partes.push(H.el("span", {}, `Aire: ${comp.humedad_aire.texto}`));
    if (!partes.length) return null;
    return [
      H.el("p", { class: "comparacion-exterior" }, partes),
      ...comp.sugerencias.map((s) => H.el("p", { class: "sugerencia" }, s)),
    ];
  }

  return { cargarResumen, dibujarResumen, lineaTarjeta };
})();
