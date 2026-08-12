import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * El POS vive en su propio dominio: pos.maledenim.com
 *
 * Mismo código, mismo despliegue, mismo API — pero otra puerta. Lo que cambia
 * no es la arquitectura (el POS sigue siendo un módulo del ERP, ADR-001) sino
 * la superficie que ve quien entra por ahí.
 *
 * TRES RAZONES POR LAS QUE IMPORTA:
 *
 * **La caja no navega al ERP.** En pos.maledenim.com no existe /produccion ni
 * /finanzas. No están escondidas: no responden. Una cajera con una clienta
 * enfrente no debería poder llegar a Producción ni por accidente ni tecleando
 * una URL.
 *
 * **La sesión queda separada.** localStorage es por origen, así que quien
 * entra en la caja no hereda —ni contamina— la sesión de quien administra el
 * ERP desde el mismo computador.
 *
 * **La raíz es la venta.** Abrir pos.maledenim.com cae directo en la pantalla
 * de venta. Un POS no tiene página de inicio.
 *
 * LO QUE ESTO NO DA: despliegues independientes. Sigue siendo un solo proyecto
 * de Vercel, así que un deploy malo del ERP también toca la caja. Separarlo de
 * verdad es un segundo proyecto apuntando al mismo repo — está documentado en
 * docs/retail-pos/01-ARQUITECTURA.md, y es una decisión de operación, no de
 * código.
 */

/** Dominios que sirven SÓLO el POS. En local se simula con la cabecera Host. */
const ES_POS = /^pos\./i;

/** Lo único que responde en el dominio del POS. */
const PERMITIDO = [
  "/pos",
  "/login",     // el ingreso es con correo y contraseña, el mismo del ERP
  "/_next",
  "/api",
  "/icon.svg",
  "/favicon.ico",
  "/manifest.json",
];

export function middleware(req: NextRequest) {
  const host = req.headers.get("host") || "";
  if (!ES_POS.test(host)) return NextResponse.next();

  const { pathname } = req.nextUrl;

  // Un POS no tiene página de inicio: la raíz ES la venta.
  if (pathname === "/") {
    const url = req.nextUrl.clone();
    url.pathname = "/pos/venta";
    return NextResponse.redirect(url);
  }

  if (PERMITIDO.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  // Todo lo demás del ERP simplemente no existe aquí. Se manda a la venta en
  // vez de a un 404: quien llegó a /produccion desde la caja se equivocó de
  // pestaña, y dejarlo en un error no le ayuda.
  const url = req.nextUrl.clone();
  url.pathname = "/pos/venta";
  return NextResponse.redirect(url);
}

export const config = {
  // Se excluyen los estáticos para no pagar middleware en cada asset.
  matcher: ["/((?!_next/static|_next/image).*)"],
};
