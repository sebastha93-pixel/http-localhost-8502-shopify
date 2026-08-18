/**
 * OYENTE DEL GRUPO DE PRODUCCIÓN — reenvía al OS lo que se dice en WhatsApp.
 *
 * POR QUÉ EXISTE (2026-08-18). El equipo ya reporta la producción en un grupo
 * de WhatsApp y la idea es que eso alimente el OS sin cambiarle la costumbre a
 * nadie. La API oficial de Meta no puede leer ese grupo: exige Official
 * Business Account, tope de 8 participantes, y solo entra a grupos que ella
 * misma crea. A uno nacido en el WhatsApp normal no hay forma de meterla.
 *
 * Entonces esto: un NÚMERO DEDICADO entra al grupo como un participante más, y
 * este proceso —un dispositivo vinculado, como WhatsApp Web— reenvía al OS lo
 * que pasa.
 *
 * LO QUE ESTE PROCESO NO HACE, A PROPÓSITO:
 *
 * · No interpreta. Reenvía texto, autor y hora tal cual. Toda la lectura vive
 *   en el OS, contra una tabla que se puede auditar; si algún día una IA lee
 *   mal un mensaje, el original sigue ahí para comparar.
 * · No contesta en el grupo. Es un oyente. Un bot que responde mal en un grupo
 *   de trabajo se vuelve ruido en dos días.
 * · No lee otros chats. Filtra por el JID del grupo configurado y descarta todo
 *   lo demás — el número dedicado puede recibir spam y eso no es del OS.
 *
 * ADVERTENCIA HONESTA: WhatsApp no soporta este uso. El número que escucha
 * puede quedar bloqueado. Por eso va un número dedicado que no hace nada más:
 * si lo bloquean, el grupo sigue vivo y solo se calla el oyente. NUNCA usar acá
 * el número de la WABA del CRM — ese está consumido por la API oficial y no
 * puede ser dispositivo vinculado.
 *
 * Config por variables de entorno (ver instalar.ps1):
 *   OS_URL          https://backend-production-21f0.up.railway.app
 *   GRUPO_WA_SECRET el mismo valor que está en Railway
 *   GRUPO_JID       el id del grupo (lo imprime este script al arrancar)
 */
"use strict";

const fs = require("fs");
const path = require("path");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
} = require("@whiskeysockets/baileys");

const OS_URL = (process.env.OS_URL || "").replace(/\/+$/, "");
const SECRET = process.env.GRUPO_WA_SECRET || "";
const GRUPO_JID = process.env.GRUPO_JID || "";
// Número dedicado que escucha, en formato internacional sin + ni espacios
// (ej. 573001234567). Con esto se vincula por CÓDIGO y no por QR, así nadie
// tiene que mirar la pantalla del servidor.
const NUMERO = (process.env.NUMERO_DEDICADO || "").replace(/[^0-9]/g, "");
const SESION_DIR = process.env.SESION_DIR || path.join(__dirname, "sesion");
const PENDIENTES = path.join(__dirname, "pendientes.jsonl");

if (!OS_URL || !SECRET) {
  console.error("Falta OS_URL o GRUPO_WA_SECRET. Revisa la instalación.");
  process.exit(1);
}

function log(...a) {
  console.log(new Date().toISOString(), ...a);
}

/**
 * Los mensajes que no se pudieron enviar quedan en un archivo y se reintentan.
 *
 * Sin esto, un corte de internet de diez minutos —o un redeploy del backend—
 * borraría para siempre lo que el equipo escribió en esos diez minutos, y nadie
 * se daría cuenta: el grupo se ve normal y el OS simplemente tiene un hueco.
 */
function encolar(payload) {
  try {
    fs.appendFileSync(PENDIENTES, JSON.stringify(payload) + "\n");
  } catch (e) {
    console.error("no pude encolar:", e.message);
  }
}

/**
 * Le cuenta al OS cómo va: conectado, con error, o con un código de pareo.
 *
 * El código se publica en el OS y NO solo en la consola del servidor: quien
 * vincula el número lo lee desde el celular que ya tiene en la mano, sin tener
 * que entrar al servidor. Si falla el latido no se cae nada — es telemetría.
 */
let grupoObjetivo = GRUPO_JID;   // el OS puede cambiarlo en caliente

async function latido(datos) {
  try {
    const r = await fetch(`${OS_URL}/api/produccion/grupo/latido`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Webhook-Secret": SECRET },
      body: JSON.stringify({ numero: NUMERO, ...datos }),
    });
    if (!r.ok) return;
    // La respuesta manda sobre el .env: el grupo se elige desde el OS y cambia
    // en el siguiente latido, sin entrar a esta máquina.
    const res = await r.json();
    if (res?.grupo_id && res.grupo_id !== grupoObjetivo) {
      grupoObjetivo = res.grupo_id;
      log(`grupo a escuchar (definido en el OS): ${grupoObjetivo}`);
    }
  } catch (e) {
    log(`latido no pudo salir: ${e.message}`);
  }
}

async function enviarAlOS(payload) {
  const r = await fetch(`${OS_URL}/api/produccion/grupo/mensajes`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Webhook-Secret": SECRET },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

async function drenarPendientes() {
  if (!fs.existsSync(PENDIENTES)) return;
  const lineas = fs.readFileSync(PENDIENTES, "utf8").split("\n").filter(Boolean);
  if (!lineas.length) return;
  log(`reintentando ${lineas.length} lote(s) pendiente(s)`);
  const quedan = [];
  for (const l of lineas) {
    try {
      await enviarAlOS(JSON.parse(l));
    } catch (e) {
      quedan.push(l);
    }
  }
  // El endpoint es idempotente por wa_message_id, así que reintentar de más
  // nunca duplica: en el peor caso el OS responde "ya lo tenía".
  fs.writeFileSync(PENDIENTES, quedan.length ? quedan.join("\n") + "\n" : "");
  if (quedan.length) log(`${quedan.length} lote(s) siguen pendientes`);
}

function tipoDe(m) {
  const c = m.message || {};
  if (c.imageMessage) return "imagen";
  if (c.documentMessage) return "documento";
  if (c.audioMessage) return "audio";
  if (c.videoMessage) return "video";
  if (c.conversation || c.extendedTextMessage) return "texto";
  return "otro";
}

function textoDe(m) {
  const c = m.message || {};
  return (
    c.conversation ||
    c.extendedTextMessage?.text ||
    c.imageMessage?.caption ||
    c.videoMessage?.caption ||
    c.documentMessage?.caption ||
    null
  );
}

async function arrancar() {
  const { state, saveCreds } = await useMultiFileAuthState(SESION_DIR);
  // printQRInTerminal en false cuando hay número: el QR obligaría a mirar la
  // consola del servidor, que es justo lo que se quiere evitar.
  const sock = makeWASocket({ auth: state, printQRInTerminal: !NUMERO });

  // Vinculación por código. Solo si no hay sesión: pedirlo estando registrado
  // la tumbaría.
  if (NUMERO && !state.creds?.registered) {
    setTimeout(async () => {
      try {
        const codigo = await sock.requestPairingCode(NUMERO);
        log(`CÓDIGO DE PAREO: ${codigo}`);
        log("Tecléalo en WhatsApp del número dedicado:");
        log("  Ajustes → Dispositivos vinculados → Vincular con número de teléfono");
        await latido({ codigo_pareo: codigo });
      } catch (e) {
        log(`no pude pedir el código: ${e.message}`);
        await latido({ error: `codigo_pareo: ${e.message}` });
      }
    }, 3000);   // Baileys necesita un momento antes de poder pedirlo
  }

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (u) => {
    const { connection, lastDisconnect, qr } = u;
    if (qr) {
      log("ESCANEA EL QR de arriba con el celular del número dedicado.");
    }
    if (connection === "open") {
      log("conectado a WhatsApp");
      latido({ conectado: true });
      drenarPendientes().catch((e) => console.error(e.message));
      // Los grupos se REPORTAN al OS, no solo se imprimen: así se elige el
      // correcto desde la app sin que nadie tenga que leer esta consola.
      sock.groupFetchAllParticipating()
        .then((gs) => {
          const lista = Object.entries(gs).map(([jid, g]) => ({
            jid, nombre: g.subject, participantes: (g.participants || []).length,
          }));
          for (const g of lista) log(`   ${g.jid}   ${g.nombre}`);
          return latido({ grupos: lista });
        })
        .catch((e) => console.error("no pude listar grupos:", e.message));
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        // Sesión revocada: reconectar en bucle no sirve, hay que re-escanear.
        log("SESIÓN CERRADA en WhatsApp. Borra la carpeta 'sesion' y vuelve a vincular.");
        latido({ error: "sesion_cerrada: hay que volver a vincular" })
          .finally(() => process.exit(1));
        return;
      }
      log(`conexión cerrada (${code}); reintentando en 5s`);
      latido({ error: `conexion_cerrada:${code}` });
      setTimeout(() => arrancar().catch((e) => console.error(e.message)), 5000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;   // 'append' es historial, no novedades
    const utiles = [];
    for (const m of messages) {
      const jid = m.key?.remoteJid || "";
      if (!jid.endsWith("@g.us")) continue;              // solo grupos
      if (grupoObjetivo && jid !== grupoObjetivo) continue;  // solo EL grupo
      if (m.key?.fromMe) continue;                       // no eco de sí mismo

      const texto = textoDe(m);
      const tipo = tipoDe(m);
      // Un mensaje sin texto ni archivo no aporta nada al espejo.
      if (!texto && tipo === "otro") continue;

      utiles.push({
        wa_message_id: m.key.id,
        autor_telefono: (m.key.participant || "").split("@")[0],
        autor_nombre: m.pushName || "",
        tipo,
        texto,
        media_url: null,   // fase 1 no descarga archivos todavía
        enviado_en: new Date((Number(m.messageTimestamp) || 0) * 1000).toISOString(),
        crudo: null,
      });
    }
    if (!utiles.length) return;
    if (!grupoObjetivo) {
      log("todavía no hay grupo definido en el OS; no guardo nada");
      return;
    }

    const jid = messages[0].key.remoteJid;
    let nombre = "";
    try {
      nombre = (await sock.groupMetadata(jid))?.subject || "";
    } catch (_) { /* el nombre es opcional */ }

    const payload = { grupo_id: jid, grupo_nombre: nombre, mensajes: utiles };
    try {
      const res = await enviarAlOS(payload);
      log(`enviados ${utiles.length}, guardados ${res.guardados}`);
    } catch (e) {
      log(`fallo el envío (${e.message}); queda en cola`);
      encolar(payload);
    }
  });
}

// Reintento cada 2 minutos aunque no llegue nada: si el backend estuvo caído,
// la cola no debe esperar a que alguien escriba en el grupo para vaciarse.
setInterval(() => {
  drenarPendientes().catch(() => {});
  latido({});   // señal de vida, para distinguir "grupo callado" de "proceso muerto"
}, 120000);

arrancar().catch((e) => {
  console.error("no pude arrancar:", e.message);
  process.exit(1);
});
