# Meta App Review · Guion de Video MALE Denim OS

**Versión:** 22 Junio 2026
**Duración objetivo:** 4-5 minutos
**Idioma:** Español (puedes traducir al inglés si prefieres)

---

## 📋 PREPARACIÓN ANTES DE GRABAR

### ✅ Checklist obligatorio Meta (verifica todo en verde antes de grabar)

- [ ] **Privacy Policy** publicada en URL pública (ej. `https://www.maledenim.com/privacy`)
- [ ] **Data Deletion URL** configurada (puede ser un `mailto:soporte@maledenim.com`)
- [ ] App en **Live Mode** en Meta Developer Portal
- [ ] **Business Verification** completa (estado "Verified")
- [ ] App tiene logo, descripción y website configurados
- [ ] Token vigente con todos los permisos básicos aprobados

### ✅ Setup técnico

- [ ] Mac con QuickTime listo (`File → New Screen Recording`)
- [ ] Micrófono interno funcionando (test rápido)
- [ ] Resolución pantalla: mínimo 1080p
- [ ] Tener cargado el celular para grabar mensajes WhatsApp/IG en vivo
- [ ] Tener una segunda cuenta de prueba para mandar mensajes (otro número/cuenta IG)

### ✅ Pestañas abiertas en el navegador

| Pestaña | URL |
|---|---|
| Tu app | `https://[tu-vercel].vercel.app/revenue` |
| Kommo | `https://drtjeans.kommo.com` |
| Meta Business Suite | con tus 3 números WhatsApp y 2 cuentas IG conectadas |
| Privacy Policy | URL de tu política publicada |

### ✅ Antes de hacer "Record"

- [ ] Cerrar todas las notificaciones (Mac: `Do Not Disturb` activado)
- [ ] Tener guion impreso/abierto en celular para no improvisar
- [ ] Test de audio (graba 5 seg, escucha, ajusta volumen)
- [ ] Ensayar 1 vez antes de la toma final

---

## 🎬 GUION COMPLETO (palabra por palabra)

---

### ESCENA 1 — Introducción (20 segundos)

**Pantalla:** Tu logo MALE Denim o tu landing page.

**Voz:**

> "Hola, soy Sebastián Hurtado, fundador de MALE Denim, una marca colombiana de jeans premium para mujer.
>
> Nuestra aplicación, MALE Denim OS, centraliza las conversaciones comerciales que recibimos por WhatsApp Business, Instagram y Facebook Messenger desde nuestras tres cuentas activas. Esto permite que nuestro equipo comercial atienda clientas y analice la calidad del servicio.
>
> A continuación demuestro cómo usamos cada permiso solicitado."

---

### ESCENA 2 — Demo `whatsapp_business_messaging` (45 segundos)

**Pantalla:** Tu app `/revenue` en tab Conversaciones.

**Voz:**

> "Aquí está el centro de operaciones. Esta tabla muestra las conversaciones de clientas en tiempo real."

**Acción:**

1. Desde tu celular envía un WhatsApp a uno de los 3 números MALE:
   > `"Hola, ¿tienen jeans talla 10?"`
2. Vuelve a la app, espera 3 segundos o haz refresh (`Cmd+R`)
3. Click en la conversación que apareció arriba

**Voz:**

> "El mensaje llega en menos de 3 segundos vía Meta WhatsApp Cloud API. Lo registramos asociado al lead correspondiente en Kommo, nuestro CRM. Esto nos permite responder oportunamente y analizar la operación comercial."

---

### ESCENA 3 — Demo `pages_messaging` + `pages_messaging_read` (45 segundos)

**Pantalla:** En tu app, filtra el canal por "Messenger".

**Voz:**

> "También recibimos consultas de venta por Facebook Messenger en nuestra página MALE Denim."

**Acción:**

1. Cambia el filtro de canal a "Messenger"
2. Muestra las conversaciones de Messenger si tienes
3. Si no tienes recientes, manda un DM a la página desde otra cuenta y espera 5 segundos
4. Click en una conversación para abrir el detalle

**Voz:**

> "Usamos `pages_messaging` para recibir estos DMs y `pages_messaging_read` para que nuestras asesoras vean el historial completo y ofrezcan mejor servicio. Sin estos permisos no podemos sincronizar la conversación a nuestro sistema interno."

---

### ESCENA 4 — Demo `instagram_manage_messages` (45 segundos)

**Pantalla:** En tu app, filtra canal por "Instagram".

**Voz:**

> "Lo mismo aplica para Instagram. Tenemos dos cuentas Instagram Business conectadas a Kommo donde las clientas escriben constantemente."

**Acción:**

1. Cambia filtro a "Instagram"
2. Muestra las conversaciones IG capturadas
3. Manda un DM en vivo desde otra cuenta IG a `@maledenim`
4. Espera 10 segundos, refresca, muestra que apareció

**Voz:**

> "Usamos `instagram_manage_messages` para captar estas consultas y unificar el cliente en una sola vista comercial, junto con sus mensajes de WhatsApp y Messenger."

---

### ESCENA 5 — `message_echoes` — LA MÁS IMPORTANTE (1 minuto)

**Pantalla:** Modal de detalle de una conversación. Debe mostrar mensajes del cliente con texto Y respuestas de la asesora aparecen como entradas vacías (los stubs).

**Voz:**

> "Aquí está donde solicitamos el permiso de message_echoes — el permiso más importante para nuestro negocio.
>
> Como pueden ver en esta conversación, los mensajes del cliente aparecen completos con su contenido. Pero los mensajes que envía nuestra asesora aparecen como registros vacíos — solo tenemos el ID y la confirmación de envío, no el texto.
>
> Esto es un problema crítico para nosotros porque nuestro motor de inteligencia artificial analiza la calidad de las respuestas comerciales para tres propósitos:
>
> Primero, auditar la calidad del servicio de cada asesora.
> Segundo, entrenar al equipo con scripts mejorados basados en respuestas reales.
> Tercero, identificar por qué se pierden ventas — el momento exacto donde la conversación se rompe.
>
> Solicitamos message_echoes para acceder al contenido de los mensajes salientes que nuestras propias asesoras envían desde nuestras cuentas verificadas. No accedemos a mensajes de terceros — solo a las respuestas que nuestro propio equipo envía desde nuestros números."

---

### ESCENA 6 — Demo del valor (45 segundos)

**Pantalla:** Tab "🔴 Sin respuesta" mostrando los leads urgentes resaltados en amber/rojo.

**Voz:**

> "Esta vista muestra los leads que aún no han sido atendidos, ordenados por urgencia. Las filas en rojo llevan más de dos horas sin respuesta — perdiendo oportunidades de venta concretas.
>
> Con los permisos completos podemos cerrar el ciclo del análisis comercial: capturar mensajes entrantes, capturar respuestas salientes, analizar con IA, alertar al equipo, y mejorar continuamente la conversión."

**Acción:**

1. Click en un lead urgente → modal abre
2. Mostrar info del lead: estado venta, valor estimado, teléfono, Lead ID
3. Click en "Auditar con IA"
4. Cuando termine la auditoría, mostrar el resultado (scores, motivos de pérdida)

---

### ESCENA 7 — Privacidad y cierre (30 segundos)

**Pantalla:** Tu política de privacidad publicada (URL `maledenim.com/privacy`).

**Voz:**

> "Todos los datos se almacenan en infraestructura segura: Railway para el procesamiento y Supabase para la base de datos, ambos con cifrado en reposo. Solo el equipo interno de MALE Denim — máximo cinco usuarios administradores — accede a estos datos.
>
> Tenemos política de privacidad publicada accesible en maledenim.com slash privacy, y un proceso de eliminación de datos por solicitud del cliente.
>
> No compartimos información con terceros, no vendemos datos, no hacemos perfilado con fines publicitarios.
>
> Gracias por considerar nuestra solicitud. Estos permisos nos permitirán seguir mejorando el servicio al cliente y la operación comercial de MALE Denim."

---

## 📝 LO QUE LLENAS EN EL FORMULARIO DE META

### Por cada permiso solicitado, copia el texto correspondiente en el campo "How will you use this permission?":

---

**`pages_messaging`**

> Used to receive incoming messages from customers via our 3 Facebook Pages connected to our business. Messages are stored in our internal CRM (Kommo) and displayed in our admin dashboard for sales advisors to respond. This is core to our customer service operation — without this permission we cannot receive customer inquiries through Messenger.

---

**`pages_messaging_read`**

> Used to read the full message history of customer conversations on Messenger. Our sales advisors need historical context (previous purchases, prior inquiries, complaints) to provide informed and personalized service. The data is only used internally by our sales team — never shared with third parties.

---

**`instagram_manage_messages`**

> Used to receive and respond to customer DMs sent to our 2 Instagram Business accounts (@maledenim and @maledenim_mayoristas). Same use case as Messenger — unified customer service via our internal dashboard. Without this permission we cannot capture Instagram inquiries which represent approximately 30% of our incoming sales conversations.

---

**`message_echoes` (o `messages_outgoing` / equivalente que pidas)**

> Used to capture the full text of outgoing messages sent by our sales advisors from our business WhatsApp and Messenger accounts. This is critical for our internal AI quality analysis engine which:
>
> 1. Audits the quality of advisor responses
> 2. Identifies lost sales opportunities and the exact conversation moments where they occurred
> 3. Provides coaching feedback to improve advisor performance
>
> Without echoes, we only capture incoming customer messages, giving us an incomplete view of the conversation. We only access messages sent from our own verified business accounts by our own employees — never third-party content.

---

## ⚠️ ERRORES COMUNES QUE META RECHAZA

Evita estos:

- ❌ Video sin audio o sin explicación verbal
- ❌ Mostrar solo Meta Business Suite, no tu app
- ❌ Decir "esto sería para…" — Meta quiere ver el caso real funcionando
- ❌ Permisos pedidos que no se usan en el video
- ❌ Usar cuentas falsas o de prueba sin marcarlas como test
- ❌ Video > 10 minutos o < 1 minuto
- ❌ Pantalla borrosa, audio bajo, ruido de fondo

## ✅ ERRORES QUE SI MOSTRAR

Está bien mostrar:

- ✅ Stubs vacíos de outgoing — JUSTIFICA tu solicitud de echoes
- ✅ Filtros vacíos si los muestras explicando para qué sirven
- ✅ Errores leves del UI mientras explicas el flujo principal

---

## 🚀 PASO A PASO PARA SUBIR

1. Graba el video siguiendo el guion
2. Edita si necesitas (quitar pausas largas, agregar texto sobre puntos clave). NO uses transiciones excesivas — Meta prefiere video crudo
3. Exporta como MP4, 1080p, máximo 100 MB
4. Entra a Meta Developer Portal → tu app **MALE DENIM** → **App Review** → **Permissions and Features**
5. Por cada permiso pendiente:
   - Click **Request Advanced Access**
   - Sube el video (Upload Screencast)
   - Pega el texto del campo "How will you use" correspondiente
6. **Test User**: marca que los videos usan datos de producción reales (no test users)
7. Click **Submit for Review**

---

## ⏰ TIEMPOS DE RESPUESTA META

- Respuesta inicial: **3 a 14 días hábiles**
- Si piden cambios: tienes 30 días para responder con video corregido
- Si aprueban: los permisos están activos inmediatamente
- Si rechazan: lees el motivo, corriges, vuelves a enviar (puedes reintentar ilimitadamente)

---

## 📞 CONTACTOS DE SOPORTE

- Meta Business Help: https://www.facebook.com/business/help
- Meta Developer Support: https://developers.facebook.com/support
- Comunidad: https://developers.facebook.com/community

---

**Buena suerte, Sebastián. Tienes todo listo para grabar.** 🎬
