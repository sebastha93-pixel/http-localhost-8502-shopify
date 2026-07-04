"use client";

/** Raíz: redirige según permisos — Centro de Control o Inicio (módulos). */
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { homePath } from "@/lib/nav";
import { LoadingState } from "@/components/page-shell";

export default function Home() {
  const router = useRouter();
  const { user, loading } = useAuth();
  useEffect(() => {
    if (!loading && user) router.replace(homePath(user));
  }, [loading, user, router]);
  return <LoadingState label="Entrando…" />;
}
