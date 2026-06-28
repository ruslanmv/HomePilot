// Single source of truth for shared DTOs (Wave B monorepo).
//
// New frontend code should import these shapes from here; existing call sites
// migrate incrementally (the strangler pattern). This is a *type-only*
// re-export — it is erased at build time, so it adds zero runtime weight and
// requires no Vite runtime resolution, only the tsconfig "paths" alias to
// ../packages/types/src.
//
// First M2-extract slice: proves @homepilot/* resolves in the frontend build.
export type {
  Artifact,
  ComputeMode,
  ComputeStatus,
  CreditsWallet,
  Device,
  Job,
  JobEvent,
  JobStatus,
  Persona,
  SupplierPolicy,
  Task,
} from "@homepilot/types";
