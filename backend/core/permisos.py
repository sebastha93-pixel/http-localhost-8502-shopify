"""Roles y grupos de permisos — constantes puras, sin dependencias.

POR QUE VIVE AQUI Y NO EN `services.usuarios`. La comprobacion de permisos
(`core.security._check_permiso`) necesita el mapeo modulo→grupo. Cuando esa
constante vivia en `services.usuarios`, leerla arrastraba el import de
`supabase` — o sea que cualquier endpoint que chequeara un permiso dependia
del cliente de base de datos del ERP entero.

Se noto construyendo el modulo retail: sus pruebas de HTTP tenian que
instalar `supabase` para verificar un tope de descuento.

Este modulo NO importa nada. Ese es todo su valor.

`services.usuarios` sigue re-exportando estos nombres, asi que el codigo que
hace `from backend.services.usuarios import MODULOS_GRUPOS` no se entera.
"""
from __future__ import annotations

__all__ = ["ROLES", "ROLES_LEGACY", "MODULOS_GRUPOS", "GRUPOS", "MODULOS",
           "MODULO_A_GRUPO", "ACCIONES"]

# admin  = acceso total (owner)
# lector = solo lectura en todos los modulos
# user   = permisos granulares por modulo+accion en el campo `permisos`
ROLES = ("admin", "lector", "user")

# Aliases de retro-compat (usuarios viejos).
ROLES_LEGACY = {"operador": "user", "lectura": "lector"}

# Grupos de permisos — agrupados por afinidad operativa para que el
# administrador no tenga que dar permiso uno por uno a cada modulo.
# El permiso se asigna al GRUPO, y el helper resuelve modulo→grupo.
MODULOS_GRUPOS = {
    "centro_control": ["centro_control"],
    "operaciones":    ["logistica", "envios", "devoluciones", "incidencias",
                       "historico", "b2b", "contraentrega", "inventario"],
    "postventa":      ["postventa"],
    "finanzas":       ["finanzas"],
    "comercial":      ["comercial", "revenue", "inteligencia"],
    "produccion":     ["produccion", "produccion_ingreso", "produccion_corte",
                       "produccion_remisiones", "produccion_proveedores",
                       "produccion_cortador"],
    "produccion_costos": ["produccion_costos"],
    "configuracion":  ["configuracion", "usuarios", "auditoria"],
    # Modulo POS. Los permisos finos (tope de descuento, anular, cerrar con
    # descuadre) van en columnas de la fila del usuario, no aqui.
    "retail":         ["retail", "retail_venta", "retail_caja",
                       "retail_inventario", "retail_admin"],
}

# Lo que se expone en el formulario de permisos.
GRUPOS = tuple(MODULOS_GRUPOS.keys())

# Lista plana de todos los modulos individuales (retro-compat).
MODULOS = tuple(m for grupo in MODULOS_GRUPOS.values() for m in grupo)

# Mapping inverso: modulo → grupo, para resolver permisos al chequear.
MODULO_A_GRUPO = {m: g for g, mods in MODULOS_GRUPOS.items() for m in mods}

ACCIONES = ("ver", "modificar", "borrar")
