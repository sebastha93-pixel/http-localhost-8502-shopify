"use client";

/**
 * Botón verde de WhatsApp — link `wa.me` con teléfono + mensaje pre-armado.
 * Uso: <BotonWhatsApp telefono="573001234567" mensaje="Hola" />
 */
import { MessageCircle } from "lucide-react";
import { buildWaLink } from "@/lib/whatsapp";

export function BotonWhatsApp({ telefono, mensaje, label = "WhatsApp", size = "sm" }: {
  telefono?: string;
  mensaje: string;
  label?: string;
  size?: "sm" | "md";
}) {
  const href = buildWaLink({ telefono, mensaje });
  const cls = size === "md"
    ? "px-4 py-2 text-xs"
    : "px-3 py-1.5 text-[0.65rem]";
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className={`inline-flex items-center gap-1.5 rounded-sm bg-[#25D366] font-semibold uppercase tracking-widest text-white hover:opacity-90 ${cls}`}>
      <MessageCircle className="h-3 w-3" />
      {label}
    </a>
  );
}
