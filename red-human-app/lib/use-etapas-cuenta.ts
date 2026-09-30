"use client";

import { useEffect, useState } from "react";
import { fetchFlujoCandidatos } from "@/lib/api";

const ETAPAS_RH = ["Prefiltro", "Entrevista IA", "Evaluación", "Entrevista Humana", "Contratación", "Onboarding"];

/** Etapas del Kanban de la Cuenta actual (demo SEZA: «operativo» = 8 etapas; «rh» = las 6 de siempre). Mientras
 * carga regresa las de siempre. `<PorCuenta>` remonta el árbol al cambiar de Cuenta, así que no hay caché. */
export function useEtapasCuenta(): string[] {
  const [etapas, setEtapas] = useState<string[]>(ETAPAS_RH);
  useEffect(() => {
    fetchFlujoCandidatos().then((f) => f?.etapas?.length && setEtapas(f.etapas));
  }, []);
  return etapas;
}
