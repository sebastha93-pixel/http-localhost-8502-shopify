"use client";

/**
 * Tipos y helpers del módulo Personal.
 *
 * Las etiquetas viven aquí y no en cada página para que "salida_anticipada"
 * se lea igual en el dashboard, en asistencia y en el autoservicio.
 */

// ── Tipos que espejan las respuestas del backend ─────────────────────────────

export interface Empleado {
  id: string;
  codigo_empleado: string;
  nombre_completo: string;
  numero_documento?: string;
  tipo_documento?: string;
  email?: string | null;
  telefono?: string | null;
  cargo?: string | null;
  area_id?: string | null;
  sede_id?: string | null;
  supervisor_id?: string | null;
  usuario_id?: string | null;
  estado_laboral: string;
  tipo_contrato?: string;
  fecha_ingreso: string;
  fecha_retiro?: string | null;
  sujeto_a_jornada?: boolean;
  rota_entre_sedes?: boolean;
}

export interface Jornada {
  id?: string;
  empleado_id: string;
  work_date: string;
  primera_entrada_at?: string | null;
  ultima_salida_at?: string | null;
  minutos_esperados: number;
  minutos_trabajados: number;
  minutos_permiso_autorizado: number;
  minutos_tarde: number;
  minutos_salida_anticipada: number;
  minutos_exceso_descanso: number;
  minutos_compensacion_aprob: number;
  /** HECHO observado: permanencia. NO es crédito. */
  minutos_posible_extra: number;
  /** DECISIÓN: extra autorizada previamente. Esto sí cuenta. */
  minutos_extra_aprobada: number;
  minutos_recargo_nocturno: number;
  minutos_dominical_festivo: number;
  estado_asistencia: string;
  explicacion?: string | null;
  bloqueado_at?: string | null;
}

export interface Permiso {
  id: string;
  empleado_id: string;
  tipo_permiso_id: string;
  inicio_solicitado_at: string;
  fin_solicitado_at: string;
  minutos_solicitados: number;
  motivo: string;
  estado: string;
  notas_jefe?: string | null;
  notas_th?: string | null;
  clasificacion_final?: string | null;
}

export interface TipoPermiso {
  id: string;
  codigo: string;
  nombre: string;
  categoria: string;
  es_compensable: boolean;
  requiere_soporte: boolean;
  minutos_max_solicitud?: number | null;
  descripcion?: string | null;
  base_legal?: string | null;
}

export interface MovimientoTiempo {
  id: string;
  fecha: string;
  tipo: string;
  direccion: "debito" | "credito";
  minutos: number;
  descripcion: string;
  origen: string;
  aprobado_por?: string | null;
  estado: string;
  automatico: boolean;
}

export interface Dashboard {
  fecha: string;
  quincena: { desde: string; hasta: string };
  programados: number;
  presentes: number;
  ausentes: number;
  tarde: number;
  en_permiso: number;
  descanso: number;
  sin_calcular: number;
  solicitudes_pendientes: number;
  incidencias_abiertas: number;
  minutos_por_compensar: number;
  posible_extra_hoy: number;
  extra_aprobada_hoy: number;
  puntualidad_pct: number | null;
}

// ── Formato ──────────────────────────────────────────────────────────────────

/** 450 → "7h 30m". Para mostrar, nunca para calcular. */
export function minutosAHoras(min: number | null | undefined): string {
  const m = Math.abs(Math.round(min ?? 0));
  const signo = (min ?? 0) < 0 ? "−" : "";
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (h && r) return `${signo}${h}h ${r}m`;
  if (h) return `${signo}${h}h`;
  return `${signo}${r}m`;
}

/** "2026-07-27T08:12:00" → "8:12 a. m." */
export function hora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit" });
}

/** "2026-07-27" → "lun 27 jul". Evita el corrimiento de un día por zona. */
export function fechaCorta(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es-CO", {
    weekday: "short", day: "numeric", month: "short",
  });
}

export function fechaLarga(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es-CO", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

export const hoyISO = () => {
  // Bogotá es UTC-5 fijo. Sin este ajuste, después de las 7 p. m. el
  // navegador en UTC ya reporta el día siguiente.
  const ahora = new Date();
  const bog = new Date(ahora.getTime() - 5 * 60 * 60 * 1000);
  return bog.toISOString().slice(0, 10);
};

// ── Estados de asistencia ────────────────────────────────────────────────────

type Tone = "critico" | "riesgo" | "normal" | "pendiente" | "info" | "neutral";

export const ESTADO_JORNADA: Record<string, { label: string; tone: Tone }> = {
  completa:          { label: "Completa",          tone: "normal" },
  tarde:             { label: "Llegó tarde",       tone: "riesgo" },
  salida_anticipada: { label: "Salió antes",       tone: "riesgo" },
  incompleta:        { label: "Marcación incompleta", tone: "critico" },
  ausente:           { label: "Ausente",           tone: "critico" },
  permiso:           { label: "Permiso",           tone: "info" },
  vacaciones:        { label: "Vacaciones",        tone: "info" },
  incapacidad:       { label: "Incapacidad",       tone: "info" },
  festivo:           { label: "Festivo",           tone: "neutral" },
  descanso:          { label: "Descanso",          tone: "neutral" },
  sin_datos:         { label: "Sin datos",         tone: "neutral" },
};

export const ESTADO_PERMISO: Record<string, { label: string; tone: Tone }> = {
  borrador:         { label: "Borrador",            tone: "neutral" },
  enviada:          { label: "Enviada",             tone: "pendiente" },
  pendiente_jefe:   { label: "Espera al jefe",      tone: "pendiente" },
  pendiente_th:     { label: "Espera a Talento Humano", tone: "pendiente" },
  aprobada:         { label: "Aprobada",            tone: "normal" },
  en_compensacion:  { label: "Por compensar",       tone: "riesgo" },
  completada:       { label: "Completada",          tone: "normal" },
  rechazada:        { label: "Rechazada",           tone: "critico" },
  cancelada:        { label: "Cancelada",           tone: "neutral" },
  vencida:          { label: "Plazo vencido",       tone: "critico" },
  enviada_a_nomina: { label: "En nómina",           tone: "info" },
};

export const TIPO_INCIDENCIA: Record<string, string> = {
  falta_entrada: "Falta la entrada",
  falta_salida: "Falta la salida",
  evento_duplicado: "Marcación duplicada",
  empleado_desconocido: "Empleado sin mapear",
  dispositivo_offline: "Dispositivo desconectado",
  secuencia_imposible: "Secuencia imposible",
  salida_anticipada_no_autorizada: "Salida anticipada sin autorizar",
  llegada_tarde_no_autorizada: "Llegada tarde sin justificar",
  descanso_excedido: "Descanso excedido",
  eventos_solapados: "Marcaciones solapadas",
  ajuste_manual_requerido: "Requiere ajuste manual",
  posible_hora_extra: "Posible hora extra",
  horario_no_encontrado: "Sin horario asignado",
  evento_fuera_de_orden: "Marcación fuera de orden",
  marcacion_sin_jornada: "Marcación sin jornada",
};

export const SEVERIDAD: Record<string, Tone> = {
  baja: "neutral", media: "pendiente", alta: "riesgo", critica: "critico",
};

export const CATEGORIA_PERMISO: Record<string, string> = {
  legal_remunerado: "Legal remunerado",
  empresarial_remunerado: "Empresarial remunerado",
  personal_compensable: "Personal compensable",
  no_remunerado: "No remunerado",
  incapacidad: "Incapacidad",
  vacaciones: "Vacaciones",
};

export function etiquetaJornada(estado: string) {
  return ESTADO_JORNADA[estado] ?? { label: estado, tone: "neutral" as Tone };
}

export function etiquetaPermiso(estado: string) {
  return ESTADO_PERMISO[estado] ?? { label: estado, tone: "neutral" as Tone };
}

/** Quién tiene la pelota. Espeja `siguiente_paso` del backend. */
export function siguientePaso(estado: string): string | null {
  return ({
    borrador: "Tú debes enviarla",
    enviada: "Espera al jefe",
    pendiente_jefe: "Espera al jefe",
    pendiente_th: "Espera a Talento Humano",
    en_compensacion: "Debes reponer el tiempo",
    vencida: "Talento Humano decide",
  } as Record<string, string>)[estado] ?? null;
}
