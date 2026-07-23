"""
backend.api.dashboard — Agregado completo para el Centro de Control.

Combina data de Logística + Finanzas + Auditoría en un payload único.
Evita múltiples queries del frontend.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client

from backend.core.security import CurrentUser, get_current_user
from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc
from backend.services import conciliacion as cnc_svc


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception:
        return None


# ── Modelos ──────────────────────────────────────────────────────────

class QuickAction(BaseModel):
    label: str
    count: int
    valor: float = 0
    href: str
    severity: str = "info"   # info | warning | danger | success


class PedidoUrgente(BaseModel):
    orden_tienda: str
    orden_melonn: str
    cliente: str
    ciudad: str
    zona: str
    nivel: str
    dias: int
    sla: int
    valor_cod: float
    sub_estado: str
    transportadora: str


class ZonaStat(BaseModel):
    zona: str
    total: int
    en_riesgo: int
    pct_riesgo: float
    valor_total: float


class CarrierStat(BaseModel):
    transportadora: str
    total: int
    novedades: int
    pct_novedades: float


class ActividadHoy(BaseModel):
    pedidos_creados_hoy: int
    entregados_hoy: int
    acciones_hoy: int
    autorizados_hoy: int


class AccionReciente(BaseModel):
    orden: str
    tipo: str
    descripcion: str
    autor: str
    creada_en: str


class ResumenFinanzas(BaseModel):
    cod_total: float
    cod_pendientes: float
    cod_transito: float
    cod_novedades: float
    cod_entregados: float
    cod_por_liquidar: float       # entregado y no liquidado en Supabase
    n_por_liquidar: int
    n_con_diferencia: int


class DashboardOverview(BaseModel):
    fetched_at: str
    fuente: str
    # KPIs logísticos
    n_total: int
    n_critico: int
    n_riesgo: int
    n_normal: int
    n_pend: int
    n_transito: int
    n_novedades: int
    n_entregados: int
    val_cod: float
    val_cod_riesgo: float
    # Bloques nuevos
    quick_actions: list[QuickAction]
    urgentes: list[PedidoUrgente]
    por_zona: list[ZonaStat]
    por_carrier: list[CarrierStat]
    actividad_hoy: ActividadHoy
    acciones_recientes: list[AccionReciente]
    finanzas: ResumenFinanzas


# ── Helpers ──────────────────────────────────────────────────────────

def _hoy_bogota() -> str:
    """Fecha hoy en zona Bogotá (UTC-5)."""
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()


def _acciones_hoy(sb: Client) -> tuple[int, int]:
    """Devuelve (total_acciones_hoy, autorizaciones_hoy)."""
    hoy = _hoy_bogota()
    try:
        res = sb.table("acciones").select("tipo,creada_en").gte("creada_en", hoy).execute()
        all_today = res.data or []
        return (
            len(all_today),
            sum(1 for r in all_today if r.get("tipo") == "despacho_autorizado"),
        )
    except Exception:
        return (0, 0)


def _acciones_recientes(sb: Client, limit: int = 8) -> list[AccionReciente]:
    try:
        res = (sb.table("acciones")
               .select("orden,tipo,descripcion,autor,creada_en")
               .order("creada_en", desc=True)
               .limit(limit)
               .execute())
        return [AccionReciente(**r) for r in (res.data or [])]
    except Exception:
        return []


# ── Endpoint ─────────────────────────────────────────────────────────

@router.get("/salud")
def salud_sistema(_: CurrentUser = Depends(get_current_user)) -> dict:
    """CENTRO DE SALUD: un semáforo por circuito (webhooks, crons,
    integraciones, impresión, lotes estancados, integridad de datos)."""
    from services import salud as _salud
    return _salud.resumen()


@router.get("/overview", response_model=DashboardOverview)
def overview(_: CurrentUser = Depends(get_current_user)) -> DashboardOverview:
    """Payload completo para el Centro de Control."""
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Melonn error: {e}")

    pedidos = [metricas_svc.clasificar(p) for p in data["pedidos"]]
    hoy = _hoy_bogota()

    # ── KPIs base ──
    def _code(p): return int(p.get("estado_melonn_code") or 0)
    cods   = [p for p in pedidos if p.get("tipo_recaudo") == "Contraentrega"]
    n_pend = sum(1 for p in cods if _code(p) in (26, 29))
    n_tran = sum(1 for p in cods if _code(p) in (5, 7, 24, 28))
    n_nov  = sum(1 for p in pedidos if p.get("es_novedad_visible"))
    n_ent  = sum(1 for p in cods if _code(p) in (6, 8))
    n_crit = sum(1 for p in pedidos if p.get("nivel") == "CRITICO")
    n_ries = sum(1 for p in pedidos if p.get("nivel") == "RIESGO")
    n_norm = max(0, len(pedidos) - n_crit - n_ries)
    val_cod = sum(p.get("valor_num", 0) for p in cods)
    val_cod_riesgo = sum(
        p.get("valor_num", 0) for p in cods
        if p.get("nivel") in ("CRITICO", "RIESGO")
    )

    # ── Quick actions ──
    quick: list[QuickAction] = []
    if n_pend:
        quick.append(QuickAction(
            label="Pendientes despacho", count=n_pend,
            valor=sum(p.get("valor_num", 0) for p in cods if _code(p) in (26, 29)),
            href="/contraentrega", severity="warning",
        ))
    if n_nov:
        quick.append(QuickAction(
            label="Con novedad", count=n_nov,
            valor=sum(p.get("valor_num", 0) for p in pedidos if p.get("es_novedad_visible")),
            href="/incidencias", severity="danger",
        ))
    if n_crit:
        quick.append(QuickAction(
            label="Críticos", count=n_crit,
            valor=sum(p.get("valor_num", 0) for p in pedidos if p.get("nivel") == "CRITICO"),
            href="/logistica", severity="danger",
        ))

    # ── Urgentes (top 8) ──
    urgentes_list = sorted(
        [p for p in pedidos if p.get("nivel") in ("CRITICO", "VENCIDO") or p.get("es_novedad_visible")],
        key=lambda p: (-int(p.get("dias_real") or 0), -float(p.get("valor_num") or 0)),
    )[:8]
    urgentes = [
        PedidoUrgente(
            orden_tienda=str(p.get("orden_tienda") or ""),
            orden_melonn=str(p.get("orden_melonn") or ""),
            cliente=str(p.get("nombre_comprador") or "—"),
            ciudad=str(p.get("ciudad_destino") or "—"),
            zona=str(p.get("zona") or "—"),
            nivel=str(p.get("nivel") or "NORMAL"),
            dias=int(p.get("dias_real") or 0),
            sla=int(p.get("sla_critico") or 0),
            valor_cod=float(p.get("valor_num") or 0),
            sub_estado=str(p.get("sub_estado_logistico") or ""),
            transportadora=str(p.get("transportadora") or "—"),
        )
        for p in urgentes_list
    ]

    # ── Performance por zona ──
    zonas_counter: dict[str, list] = defaultdict(list)
    for p in pedidos:
        zonas_counter[p.get("zona") or "OTRA"].append(p)
    por_zona = []
    for zona, ps in zonas_counter.items():
        n_riesgo = sum(1 for p in ps if p.get("nivel") in ("CRITICO", "RIESGO", "VENCIDO"))
        por_zona.append(ZonaStat(
            zona=zona,
            total=len(ps),
            en_riesgo=n_riesgo,
            pct_riesgo=round(100 * n_riesgo / len(ps), 1) if ps else 0,
            valor_total=sum(p.get("valor_num", 0) for p in ps),
        ))
    por_zona.sort(key=lambda z: -z.pct_riesgo)

    # ── Performance por transportadora ──
    carriers: dict[str, list] = defaultdict(list)
    for p in pedidos:
        c = (p.get("transportadora") or "—").strip()
        carriers[c].append(p)
    por_carrier = []
    for c, ps in carriers.items():
        if c == "—" or len(ps) < 3:
            continue
        n_nov_c = sum(1 for p in ps if p.get("es_novedad_visible"))
        por_carrier.append(CarrierStat(
            transportadora=c,
            total=len(ps),
            novedades=n_nov_c,
            pct_novedades=round(100 * n_nov_c / len(ps), 1) if ps else 0,
        ))
    por_carrier.sort(key=lambda c: -c.pct_novedades)
    por_carrier = por_carrier[:8]

    # ── Actividad de hoy ──
    creados_hoy = sum(
        1 for p in pedidos
        if str(p.get("fecha_creacion") or "")[:10] == hoy
    )
    entregados_hoy = sum(
        1 for p in pedidos
        if str(p.get("fecha_entrega") or "")[:10] == hoy
    )
    sb = _sb()
    acciones_total = 0
    autorizados_hoy = 0
    acciones_recientes_list: list[AccionReciente] = []
    if sb:
        acciones_total, autorizados_hoy = _acciones_hoy(sb)
        acciones_recientes_list = _acciones_recientes(sb, limit=8)

    actividad = ActividadHoy(
        pedidos_creados_hoy=creados_hoy,
        entregados_hoy=entregados_hoy,
        acciones_hoy=acciones_total,
        autorizados_hoy=autorizados_hoy,
    )

    # ── Finanzas: COD por liquidar ──
    liq_map = cnc_svc.cargar_map()
    cod_entregados_pedidos = [p for p in cods if _code(p) in (6, 8)]
    sin_liquidar = [
        p for p in cod_entregados_pedidos
        if not (liq_map.get(p.get("orden_tienda", "")) or liq_map.get(p.get("orden_melonn", "")))
    ]
    cod_por_liquidar = sum(p.get("valor_num", 0) for p in sin_liquidar)

    # Diferencias en liquidados (monto recibido != esperado)
    n_con_diff = 0
    for p in cod_entregados_pedidos:
        liq = liq_map.get(p.get("orden_tienda", "")) or liq_map.get(p.get("orden_melonn", ""))
        if liq:
            diff = abs(float(liq.get("monto_liquidado") or 0) - float(p.get("valor_num") or 0))
            if diff > 1:
                n_con_diff += 1

    finanzas = ResumenFinanzas(
        cod_total=val_cod,
        cod_pendientes=sum(p.get("valor_num", 0) for p in cods if _code(p) in (26, 29)),
        cod_transito=sum(p.get("valor_num", 0) for p in cods if _code(p) in (5, 7, 24, 28)),
        cod_novedades=sum(p.get("valor_num", 0) for p in cods if p.get("es_novedad_visible")),
        cod_entregados=sum(p.get("valor_num", 0) for p in cod_entregados_pedidos),
        cod_por_liquidar=cod_por_liquidar,
        n_por_liquidar=len(sin_liquidar),
        n_con_diferencia=n_con_diff,
    )

    # Agregar liquidaciones pendientes a quick actions si hay
    if finanzas.n_por_liquidar > 0:
        quick.append(QuickAction(
            label="Por conciliar",
            count=finanzas.n_por_liquidar,
            valor=finanzas.cod_por_liquidar,
            href="/conciliacion",
            severity="info",
        ))

    return DashboardOverview(
        fetched_at=data["fetched_at"],
        fuente=data["fuente"],
        n_total=len(pedidos),
        n_critico=n_crit,
        n_riesgo=n_ries,
        n_normal=n_norm,
        n_pend=n_pend,
        n_transito=n_tran,
        n_novedades=n_nov,
        n_entregados=n_ent,
        val_cod=val_cod,
        val_cod_riesgo=val_cod_riesgo,
        quick_actions=quick,
        urgentes=urgentes,
        por_zona=por_zona,
        por_carrier=por_carrier,
        actividad_hoy=actividad,
        acciones_recientes=acciones_recientes_list,
        finanzas=finanzas,
    )
