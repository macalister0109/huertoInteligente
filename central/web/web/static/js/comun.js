/* Utilidades compartidas por las páginas del tablero. Sin dependencias externas. */
"use strict";

const Huerto = (() => {
  const zona = document.body.dataset.zona || "America/Santiago";
  const formatoHora = new Intl.DateTimeFormat("es-CL", { timeZone: zona, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const formatoDia = new Intl.DateTimeFormat("es-CL", { timeZone: zona, day: "numeric", month: "short" });
  const formatoClave = new Intl.DateTimeFormat("es-CL", { timeZone: zona, year: "numeric", month: "2-digit", day: "2-digit" });
  const formatoEntero = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  const formatoDecimal = new Intl.NumberFormat("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const esHoy = (fecha) => formatoClave.format(fecha) === formatoClave.format(new Date());

  /** "14:32" si es de hoy, "25 nov 14:32" si es de otro día. */
  function hora(iso) {
    if (!iso) return "—";
    const fecha = new Date(iso);
    const texto = formatoHora.format(fecha);
    return esHoy(fecha) ? texto : `${formatoDia.format(fecha)} ${texto}`;
  }

  const entero = (v) => (v === null || v === undefined ? null : formatoEntero.format(v));
  const decimal = (v) => (v === null || v === undefined ? null : formatoDecimal.format(v));

  /** Crea un elemento. Los textos van siempre con textContent (nunca HTML). */
  function el(etiqueta, atributos = {}, ...hijos) {
    const nodo = document.createElement(etiqueta);
    for (const [clave, valor] of Object.entries(atributos)) {
      if (valor === null || valor === undefined || valor === false) continue;
      if (clave === "class") nodo.className = valor;
      else nodo.setAttribute(clave, valor === true ? "" : valor);
    }
    for (const hijo of hijos.flat()) {
      if (hijo === null || hijo === undefined || hijo === false) continue;
      nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
    }
    return nodo;
  }

  function iniciarReloj() {
    const reloj = document.getElementById("reloj");
    if (!reloj) return;
    const tic = () => { reloj.textContent = formatoHora.format(new Date()); };
    tic();
    setInterval(tic, 1000);
  }

  /** Aviso en la barra superior cuando se pierde la conexión con el equipo central. */
  function avisoConexion(texto) {
    const aviso = document.getElementById("estado-central");
    if (!aviso) return;
    aviso.hidden = !texto;
    aviso.textContent = texto || "";
  }

  async function obtenerJson(url) {
    const respuesta = await fetch(url, { cache: "no-store" });
    if (!respuesta.ok) throw new Error(`${url}: ${respuesta.status}`);
    return respuesta.json();
  }

  function enviarJson(url, datos) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    });
  }

  /** Lista de avisos (abiertos o resueltos) para el tablero y el detalle. */
  function itemAviso(a, mostrarCama = true) {
    const cuando = a.resuelta_en
      ? `De ${hora(a.iniciada_en)} a ${hora(a.resuelta_en)}`
      : `Desde ${hora(a.iniciada_en)}`;
    return el("li", { class: `aviso tipo-${a.tipo}`, "data-id": a.id },
      mostrarCama ? el("span", { class: "cama" }, a.cama) : null,
      el("span", { class: "texto" }, a.mensaje),
      el("span", { class: "cuando" }, cuando));
  }

  function dibujarAvisos(lista, avisos, textoVacio, mostrarCama = true) {
    lista.replaceChildren(...(avisos.length
      ? avisos.map((a) => itemAviso(a, mostrarCama))
      : [el("li", { class: "vacio" }, textoVacio)]));
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarReloj();
    // Fechas que vienen del servidor en UTC (p. ej. en la configuración)
    document.querySelectorAll("time[data-iso]").forEach((t) => { t.textContent = hora(t.dataset.iso); });
  });

  return { hora, entero, decimal, el, avisoConexion, obtenerJson, enviarJson, dibujarAvisos };
})();
