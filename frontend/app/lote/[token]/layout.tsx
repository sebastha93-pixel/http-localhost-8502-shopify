/**
 * Layout dedicado para la vista pública del lote — sin sidebar ni auth.
 * Anula el layout de la app por completo.
 */
export default function LoteLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
