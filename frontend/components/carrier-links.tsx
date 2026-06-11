"use client";

import { useState } from "react";
import { Truck, ExternalLink, Copy, Check } from "lucide-react";

interface Carrier {
  name: string;
  short: string;
  url: string;
  color: string;
}

const CARRIERS: Carrier[] = [
  { name: "Coordinadora",     short: "Coord.",  url: "https://coordinadora.com/portafolio-de-servicios/servicios-en-linea/rastreo-de-mercancia/", color: "bg-rust" },
  { name: "Envía",            short: "Envía",   url: "https://www.envia.co/rastreo-de-envios", color: "bg-navy" },
  { name: "Interrapidísimo",  short: "Inter.",  url: "https://www.interrapidisimo.com/sigue-tu-envio/", color: "bg-crimson" },
  { name: "TCC",              short: "TCC",     url: "https://tcc.com.co/rastreo-envios/", color: "bg-teal" },
  { name: "Servientrega",     short: "Servi.",  url: "https://www.servientrega.com/wps/portal/inicio/rastrea-tu-envio", color: "bg-khaki" },
];

interface Props {
  orden: string;
  melonnLink?: string;
}

/**
 * Mini-toolbar con acceso rápido a cada transportadora.
 * Copia el # de orden al portapapeles y abre la página de tracking.
 */
export function CarrierLinks({ orden, melonnLink }: Props) {
  const [copied, setCopied] = useState<string | null>(null);

  const handleClick = async (c: Carrier) => {
    try {
      await navigator.clipboard.writeText(orden);
      setCopied(c.name);
      setTimeout(() => setCopied(null), 2500);
    } catch {}
    window.open(c.url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="rounded-md border border-border bg-white p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">
          Rastrear envío
        </p>
        <div className="flex items-center gap-1.5 text-[0.65rem] text-graphite">
          {copied ? (
            <>
              <Check className="h-3 w-3 text-teal" />
              <span className="text-teal font-semibold">Orden {orden} copiada</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Click copia # y abre</span>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {CARRIERS.map((c) => (
          <button
            key={c.name}
            onClick={() => handleClick(c)}
            className={`inline-flex items-center gap-1.5 rounded-md ${c.color} hover:opacity-90 px-2.5 py-1.5 text-xs font-semibold text-white transition-opacity`}
            title={`Abrir ${c.name} y copiar orden ${orden}`}
          >
            <Truck className="h-3 w-3" />
            {c.short}
          </button>
        ))}

        {melonnLink && (
          <a
            href={melonnLink}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white hover:bg-concrete px-2.5 py-1.5 text-xs font-semibold text-graphite"
            title="Ver en Melonn (origen)"
          >
            <ExternalLink className="h-3 w-3" />
            Melonn
          </a>
        )}
      </div>
    </div>
  );
}
