"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PedidoListResponse, MetricasResponse } from "@/lib/types";

export function usePedidos() {
  return useQuery({
    queryKey: ["melonn", "pedidos", "all"],
    queryFn: () => api.get<PedidoListResponse>("/api/melonn/pedidos"),
  });
}

export function useMetricas() {
  return useQuery({
    queryKey: ["metricas"],
    queryFn: () => api.get<MetricasResponse>("/api/metricas"),
  });
}
