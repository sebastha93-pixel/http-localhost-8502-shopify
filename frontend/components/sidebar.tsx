"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Collapsible from "@radix-ui/react-collapsible";
import { ChevronDown, UserCircle, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { ROL_LABEL, puedeVerModulo } from "@/lib/auth";
import { NAV_HOME, gruposVisibles, homePath, type NavGroup, type NavItem } from "@/lib/nav";
import { SyncButton } from "@/components/sync-button";

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  // Visibilidad centralizada en lib/nav.ts (misma fuente que /inicio)
  const groups = gruposVisibles(user);
  // Home según permisos: Centro de Control, o Inicio (launcher de módulos)
  const home: NavItem = puedeVerModulo(user, "centro_control")
    ? NAV_HOME
    : { label: "Inicio", href: "/inicio" };

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col bg-ink-950 text-concrete">
      {/* Logo */}
      <div className="relative px-5 pt-6 pb-5 border-b border-white/5">
        <p className="font-display text-[1.1rem] font-medium tracking-[0.28em] text-white leading-none">
          MALE&apos;DENIM
        </p>
        <p className="mt-1.5 text-[0.5rem] font-semibold tracking-[0.4em] text-steel-300/70 uppercase">
          That Fits
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        <NavLink item={home} pathname={pathname} highlight />

        {groups.map((g) => (
          <NavGroupCollapsible key={g.title} group={g} pathname={pathname} />
        ))}
      </nav>

      {/* Bot Melonn removido — los webhooks de Melonn ya cubren el flujo */}
      {/* Sync button (admin/operador) */}
      <SyncButton />
      {/* Footer — identidad del usuario (auditoría) */}
      <UserBox />
      <div className="border-t border-white/5 px-5 py-2 text-[0.5rem] tracking-[0.25em] text-steel/40 text-center">
        MALE'DENIM OS · v3
      </div>
    </aside>
  );
}

function UserBox() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="border-t border-white/5 px-4 py-3">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <UserCircle className="h-4 w-4 text-steel flex-none" />
        <div className="text-left min-w-0 flex-1">
          <p className="text-xs font-semibold text-concrete truncate">{user.nombre}</p>
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.2em] text-steel/60">
            {ROL_LABEL[user.rol]}
          </p>
        </div>
        <button
          onClick={logout}
          title="Cerrar sesión"
          className="text-steel/70 hover:text-white p-1 rounded hover:bg-white/5"
        >
          <LogOut className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function NavGroupCollapsible({ group, pathname }: { group: NavGroup; pathname: string }) {
  const activeInGroup = group.items.some((i) => pathname.startsWith(i.href));
  const [open, setOpen] = useState(group.defaultOpen ?? activeInGroup);

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen} className="mt-3">
      <Collapsible.Trigger className="flex w-full items-center justify-between px-2 py-1.5 text-[0.68rem] font-bold uppercase tracking-[0.22em] text-steel/55 hover:text-concrete transition-colors">
        <span>{group.title}</span>
        <ChevronDown
          className={cn("h-3 w-3 transition-transform", open ? "rotate-0" : "-rotate-90")}
        />
      </Collapsible.Trigger>
      <Collapsible.Content className="data-[state=open]:animate-accordion-down data-[state=closed]:animate-accordion-up overflow-hidden">
        <div className="mt-1 space-y-0.5">
          {group.items.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} />
          ))}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function NavLink({
  item,
  pathname,
  highlight,
}: {
  item: NavItem;
  pathname: string;
  highlight?: boolean;
}) {
  const active = pathname === item.href || pathname.startsWith(item.href + "/");
  return (
    <Link
      href={item.href}
      className={cn(
        "relative block rounded-sm px-3 py-2 text-[0.7rem] font-semibold uppercase tracking-[0.15em] transition-colors",
        active
          ? "stitch-rail bg-white/[0.06] text-white pl-4"
          : "text-concrete/75 hover:bg-white/5 hover:text-white",
        highlight && !active && "text-white/90",
      )}
    >
      {item.label}
    </Link>
  );
}
