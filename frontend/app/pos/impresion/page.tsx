"use client";

/**
 * Ajuste de la impresora — de ESTE equipo.
 *
 * Existe porque la misma tirilla salió bien en una tienda y en la otra salió
 * más pequeña y cortada por la derecha: otra impresora, otro controlador. No
 * hay número que sirva para todas, así que se ajusta aquí, mirando una tirilla
 * de prueba, y se guarda en el equipo.
 *
 * LA VISTA PREVIA ES EL MISMO COMPONENTE QUE SE IMPRIME, con el mismo ajuste.
 * El recuadro punteado es el ancho de la hoja; lo que quede por fuera, la
 * impresora lo corta.
 */
import { useAuth } from "@/components/auth-provider";
import { Rail } from "@/components/pos/rail";
import { Tirilla, TirillaImpresa, estilosDelEquipo } from "@/components/pos/tirilla";
import {
  IMPRESION_POR_DEFECTO,
  LIMITES,
  useConfigImpresion,
  type ConfigImpresion,
} from "@/lib/pos/impresion";
import type { Tirilla as DatosTirilla } from "@/lib/pos/api";

export default function PaginaImpresion() {
  const { user } = useAuth();
  const [cfg, guardar] = useConfigImpresion();

  const cambiar = (k: keyof ConfigImpresion, v: number) =>
    guardar({ ...cfg, [k]: v });

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />
      <TirillaImpresa datos={EJEMPLO} />

      <main className="flex min-w-0 flex-1 gap-8 overflow-y-auto p-6">
        <section className="w-full max-w-[420px] shrink-0">
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Ajuste de la impresora
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-[var(--pos-700)]">
            Vale sólo para <b>este equipo</b>. Mueve los valores, imprime la
            prueba y repite hasta que el papel salga completo y se lea bien.
            Se guarda solo.
          </p>

          <div className="mt-6 flex flex-col gap-5">
            <Ajuste
              titulo="Tamaño de la letra"
              ayuda="Súbelo si la tirilla sale muy pequeña."
              valor={cfg.letraPct} unidad="%" clave="letraPct" onCambio={cambiar}
            />
            <Ajuste
              titulo="Ancho del texto"
              ayuda="Bájalo si el borde derecho sale cortado: los valores pierden el último número."
              valor={cfg.anchoMm} unidad=" mm" clave="anchoMm" onCambio={cambiar}
            />
            <Ajuste
              titulo="Correr hacia la derecha"
              ayuda="Súbelo si el borde izquierdo sale cortado."
              valor={cfg.margenMm} unidad=" mm" clave="margenMm" onCambio={cambiar}
            />
            <Ajuste
              titulo="Ancho del rollo"
              ayuda="80 mm es el de casi todas. Cámbialo sólo si la impresora usa rollo de 58 mm."
              valor={cfg.hojaMm} unidad=" mm" clave="hojaMm" onCambio={cambiar}
            />
          </div>

          <div className="mt-7 flex flex-wrap gap-3">
            <button
              onClick={() => window.print()}
              className="pos-btn pos-btn-primario px-8 py-3.5 text-[13.5px]"
            >
              IMPRIMIR PRUEBA
            </button>
            <button
              onClick={() => guardar(IMPRESION_POR_DEFECTO)}
              className="pos-btn pos-btn-sec px-5 py-3.5 text-[13.5px]"
            >
              VOLVER A LO DE FÁBRICA
            </button>
          </div>

          <p className="mt-5 text-[12px] leading-relaxed text-[var(--pos-600)]">
            Si después de ajustar el navegador sigue encogiendo la hoja, revisa
            en el cuadro de impresión que la <b>escala</b> esté en 100 y los{" "}
            <b>márgenes</b> en «Ninguno».
          </p>
        </section>

        <section className="min-w-0">
          <p className="kicker mb-2 text-[var(--pos-600)]">
            Así sale por el papel · tamaño real
          </p>
          {/* El recuadro punteado es la HOJA. Lo que se salga, se corta. */}
          <div
            className="pos-impresion-vista overflow-hidden bg-white"
            style={{
              width: `${cfg.hojaMm}mm`,
              outline: "1px dashed var(--pos-600)",
              boxShadow: "0 1px 3px rgba(0,0,0,.08)",
            }}
          >
            <div className="pos-impresion" style={{ display: "block" }}>
              <Tirilla datos={EJEMPLO} />
              <style>{estilosDelEquipo(cfg)}</style>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function Ajuste({
  titulo, ayuda, valor, unidad, clave, onCambio,
}: {
  titulo: string;
  ayuda: string;
  valor: number;
  unidad: string;
  clave: keyof ConfigImpresion;
  onCambio: (k: keyof ConfigImpresion, v: number) => void;
}) {
  const { min, max, paso } = LIMITES[clave];
  const mover = (d: number) =>
    onCambio(clave, Math.min(Math.max(+(valor + d).toFixed(2), min), max));
  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 text-[14px] font-medium">{titulo}</span>
        {/* 44×44: se ajusta de pie, con la tirilla de prueba en la otra mano. */}
        <button
          onClick={() => mover(-paso)}
          disabled={valor <= min}
          aria-label={`Bajar ${titulo.toLowerCase()}`}
          className="h-11 w-11 border border-[var(--pos-divider)] text-[18px] disabled:opacity-40"
        >
          −
        </button>
        <span className="tabular w-[76px] text-center text-[15px] tabular-nums">
          {String(valor).replace(".", ",")}{unidad}
        </span>
        <button
          onClick={() => mover(paso)}
          disabled={valor >= max}
          aria-label={`Subir ${titulo.toLowerCase()}`}
          className="h-11 w-11 border border-[var(--pos-divider)] text-[18px] disabled:opacity-40"
        >
          +
        </button>
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-[var(--pos-600)]">{ayuda}</p>
    </div>
  );
}

/** Una factura de mentira con todo lo que trae una de verdad: nombres largos,
 *  cliente, descuento, QR y los textos legales del pie. Si ésta cabe, las
 *  reales caben. */
const EJEMPLO: DatosTirilla = {
  razon_social: "DIRTY JEANS S.A.S.",
  nit: "901680460-1",
  direccion: "PRUEBA DE IMPRESIÓN",
  telefono: "",
  tienda_nombre: "Tirilla de prueba",
  resolucion_dian:
    "Número Autorización 00000000000000 aprobado en 20261008 prefijo PRUEBA "
    + "desde el número 1 al 1000000 Vigencia: 24 meses",
  mensaje: null,
  numero: "PRUEBA-0001",
  fecha: "10/10/2026 12:16",
  caja_nombre: "Caja 1",
  cajera_nombre: "Nombre de la asesora",
  cliente_nombre: "NOMBRE COMPLETO DE LA CLIENTA",
  cliente_documento: "CC 1000000000",
  lineas: [
    { sku: "25625-1T6", descripcion: "JEAN BOTA CAMPANA GRIS CON HILO CONTRASTE · Talla 6",
      cantidad: 1, precio_unitario_centavos: 14990000, descuento_centavos: 1499000,
      descuento_motivo: "promoción", total_centavos: 13491000 },
    { sku: "5354", descripcion: "BOLSA MALE GRANDE · Talla U", cantidad: 1,
      precio_unitario_centavos: 200000, descuento_centavos: 0,
      descuento_motivo: null, total_centavos: 200000 },
  ],
  pagos: [{ nombre: "Datáfono", monto_centavos: 13691000, referencia: "004512" }],
  subtotal_centavos: 15190000,
  total_bruto_centavos: 12764706,
  descuento_base_centavos: 1259664,
  impuestos: [{ tasa: "19.00", base_centavos: 11505042, impuesto_centavos: 2185958 }],
  descuento_centavos: 1499000,
  total_centavos: 13691000,
  base_gravable_centavos: 11505042,
  iva_centavos: 2185958,
  pagado_centavos: 13691000,
  vuelto_centavos: 0,
  unidades: 2,
  estado_fiscal: "emitido",
  documento_fiscal: "PRUEBA-1",
  cufe: "0".repeat(96),
  anulada: false,
  qr_contenido: "prueba",
  qr_ruta: cuadricula(29),
  qr_modulos: 29,
  es_documento_fiscal: true,
  fecha_expedicion: "10/10/2026 12:16",
  regimen: "Responsable de IVA - Actividad económica 4782",
  factura_en_camino: false,
};

/** Un patrón con forma de QR, para ver cuánto ocupa. No codifica nada. */
function cuadricula(n: number): string {
  let d = "";
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const esquina = (x < 7 && y < 7) || (x >= n - 7 && y < 7) || (x < 7 && y >= n - 7);
      const marco = esquina
        && (x % (n - 7) === 0 || x % (n - 7) === 6 || y % (n - 7) === 0 || y % (n - 7) === 6
            || (x % (n - 7) >= 2 && x % (n - 7) <= 4 && y % (n - 7) >= 2 && y % (n - 7) <= 4));
      if (esquina ? marco : (x * 7 + y * 13 + x * y) % 3 === 0) d += `M${x} ${y}h1v1h-1z`;
    }
  }
  return d;
}
