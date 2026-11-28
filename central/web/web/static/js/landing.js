/* Página del proyecto: menú móvil, simulador de cama (HU-05) y formulario.
   Sin dependencias. El formulario se envía a POST /api/piloto: el servidor
   manda el correo al equipo del piloto y no guarda los datos. */
"use strict";

(() => {
  // ------------------------------------------------------------- menú móvil
  const botonMenu = document.querySelector(".boton-menu");
  const menu = document.getElementById("menu-landing");
  if (botonMenu && menu) {
    botonMenu.addEventListener("click", () => {
      const abierto = menu.classList.toggle("abierto");
      botonMenu.setAttribute("aria-expanded", String(abierto));
    });
    menu.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => {
      menu.classList.remove("abierto");
      botonMenu.setAttribute("aria-expanded", "false");
    }));
  }

  // --------------------------------------------------- simulador de la cama
  const ESTADOS = {
    verde: {
      nombre: "Cama A", cultivo: "Tomates · zona central", icono: "✔", mensaje: "Todo bien",
      humedad: "54 %", ideal: "ideal 30 a 70 %", temp: "24 °C", luz: "6,8 h", pie: "Medido hace 1 min",
      nota: "Verde: la humedad, la temperatura y la luz están dentro del rango del cultivo.",
    },
    rojo: {
      nombre: "Cama B", cultivo: "Tomates · zona central", icono: "!", mensaje: "Revisar: humedad 22 %",
      humedad: "22 %", ideal: "ideal 30 a 70 %", temp: "31 °C", luz: "7,2 h", pie: "Aviso generado en menos de 5 min",
      nota: "Rojo: el calor de la tarde secó la cama. Aparece el aviso «Cama B seca: 22 % (ideal 30 % a 70 %)», una sola vez mientras siga seca.",
    },
    gris: {
      nombre: "Cama C", cultivo: "Lechugas · zona central", icono: "?", mensaje: "Sensor sin conexión",
      humedad: "—", ideal: "sin lecturas", temp: "—", luz: "—", pie: "Última lectura hace más de 2 h",
      nota: "Gris: el sensor lleva más de 2 horas sin enviar datos. Así nadie toma decisiones con lecturas viejas.",
    },
  };

  const tarjeta = document.getElementById("tarjeta-sim");
  const botones = document.querySelectorAll(".simulador-botones button");
  const nota = document.querySelector(".sim-nota");

  function mostrar(estado) {
    const datos = ESTADOS[estado];
    if (!datos || !tarjeta) return;
    botones.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.estado === estado)));
    tarjeta.classList.add("cambiando");
    setTimeout(() => {
      tarjeta.className = `tarjeta-sim estado-${estado}`;
      tarjeta.querySelectorAll("[data-campo]").forEach((el) => {
        const valor = datos[el.dataset.campo];
        if (valor !== undefined) el.textContent = valor;
      });
      if (nota) nota.textContent = datos.nota;
    }, 160);
  }

  botones.forEach((b, i) => {
    b.addEventListener("click", () => mostrar(b.dataset.estado));
    // Flechas del teclado entre las pestañas
    b.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const siguiente = botones[(i + (e.key === "ArrowRight" ? 1 : botones.length - 1)) % botones.length];
      siguiente.focus();
      mostrar(siguiente.dataset.estado);
    });
  });

  // ------------------------------------------------------------- formulario
  const formulario = document.getElementById("formulario-piloto");
  const confirmacion = document.getElementById("confirmacion");
  if (!formulario) return;
  const error = formulario.querySelector(".error-formulario");
  const correoDestino = formulario.dataset.correo || "";
  const CORREO_VALIDO = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function validar() {
    const problemas = [];
    const campos = {
      nombre: formulario.elements.nombre, estamento: formulario.elements.estamento, correo: formulario.elements.correo,
    };
    Object.values(campos).forEach((c) => c.removeAttribute("aria-invalid"));
    if (campos.nombre.value.trim().length < 3) {
      problemas.push("Escribe tu nombre completo.");
      campos.nombre.setAttribute("aria-invalid", "true");
    }
    if (!campos.estamento.value) {
      problemas.push("Elige tu estamento.");
      campos.estamento.setAttribute("aria-invalid", "true");
    }
    if (!CORREO_VALIDO.test(campos.correo.value.trim())) {
      problemas.push("Revisa tu correo electrónico.");
      campos.correo.setAttribute("aria-invalid", "true");
    }
    return problemas;
  }

  function mostrarError(texto, correo) {
    error.textContent = texto;
    if (correo) {
      error.append(" Escríbenos directamente a ");
      const enlace = document.createElement("a");
      enlace.href = `mailto:${correo}`;
      enlace.textContent = correo;
      error.append(enlace, ".");
    }
    error.hidden = false;
  }

  const boton = formulario.querySelector('button[type="submit"]');
  const textoBoton = boton.textContent;

  formulario.addEventListener("submit", async (e) => {
    e.preventDefault();
    const problemas = validar();
    if (problemas.length) {
      mostrarError(problemas.join(" "));
      formulario.querySelector('[aria-invalid="true"]')?.focus();
      return;
    }
    error.hidden = true;
    const f = formulario.elements;
    const datos = {
      nombre: f.nombre.value.trim(), estamento: f.estamento.value, correo: f.correo.value.trim(),
      comentario: f.comentario.value.trim(), sitio_web: f.sitio_web ? f.sitio_web.value : "",
    };
    boton.disabled = true;
    boton.textContent = "Enviando…";
    let respuesta = null;
    let cuerpo = {};
    try {
      respuesta = await fetch(formulario.action, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos),
      });
      cuerpo = await respuesta.json().catch(() => ({}));
    } catch (_) {
      respuesta = null;
    } finally {
      boton.disabled = false;
      boton.textContent = textoBoton;
    }
    if (!respuesta || !respuesta.ok) {
      const texto = respuesta ? (cuerpo.error || "No se pudo enviar la solicitud.") :
        "No hay conexión con el sitio. Revisa tu internet e inténtalo de nuevo.";
      mostrarError(texto, cuerpo.correo || (respuesta && respuesta.status >= 500 ? correoDestino : ""));
      return;
    }
    confirmacion.querySelector('[data-campo="visitante"]').textContent = datos.correo;
    const enlace = confirmacion.querySelector('[data-campo="correo"]');
    enlace.textContent = correoDestino;
    enlace.href = `mailto:${correoDestino}`;
    formulario.hidden = true;
    confirmacion.hidden = false;
    confirmacion.scrollIntoView({ behavior: "smooth", block: "center" });
  });
})();
