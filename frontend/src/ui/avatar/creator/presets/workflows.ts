/**
 * Avatar workflow presets — TypeScript mirror of backend registry.
 *
 * Additive module.  Provides type-safe workflow preset definitions and
 * auto-selection logic for the Character Creator wizard.
 *
 * These presets map to ComfyUI workflow JSON templates in workflows/avatar/.
 * The wizard uses them to determine which backend endpoint/workflow to call
 * for each generation step.
 *
 * Non-destructive: no existing code is modified.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type WizardStep =
  | 'FACE'
  | 'BODY'
  | 'OUTFIT'
  | 'PORTRAIT'
  | 'REPAIR_FACE'
  | 'EDIT_OUTFIT'
  | 'EDIT_BG'
  | 'EDIT_EXPRESSION'
  | 'EDIT_POSE'

export type WorkflowEngine = 'SD15' | 'SDXL' | 'FLUX' | 'UTILITY'

export type WorkflowId =
  // Face
  | 'wf01_face_stylegan'
  | 'wf02_face_diffusion'
  | 'wf03_face_upload'
  // Body
  | 'wf04_body_anchor'
  | 'wf05_body_pose'
  | 'wf06_body_sdxl'
  // Outfit
  | 'wf07_outfit_default'
  | 'wf08_outfit_photomaker'
  | 'wf09_outfit_sdxl'
  // Repair
  | 'wf10_faceswap_repair'
  | 'wf11_identity_reproject'
  // Edit
  | 'wf12_inpaint_outfit'
  | 'wf13_bg_replace'
  | 'wf14_expression_change'
  | 'wf15_pose_adjust'
  // Special
  | 'wf16_portrait'
  | 'wf17_studio_photoshoot'
  | 'wf18_fantasy'
  | 'wf19_anime'

export interface WorkflowPreset {
  id: WorkflowId
  step: WizardStep
  label: string
  description: string
  engine: WorkflowEngine
  requires: string[]
  advanced?: boolean
  commercialOk?: boolean
  defaults?: {
    width?: number
    height?: number
    steps?: number
    cfg?: number
    sampler?: string
    scheduler?: string
    denoise?: number
  }
}

// ---------------------------------------------------------------------------
// Complete preset registry — all 19 production workflows
// ---------------------------------------------------------------------------

export const WORKFLOW_PRESETS: Record<WorkflowId, WorkflowPreset> = {
  // ═══════ FACE ═══════
  wf01_face_stylegan: {
    id: 'wf01_face_stylegan',
    step: 'FACE',
    label: 'Random Face (StyleGAN)',
    description: 'Generate random identity via StyleGAN2 FFHQ. Fast, no prompt needed.',
    engine: 'UTILITY',
    requires: [],
    commercialOk: false,
    defaults: { width: 1024, height: 1024 },
  },
  wf02_face_diffusion: {
    id: 'wf02_face_diffusion',
    step: 'FACE',
    label: 'Diffusion Face (SD1.5)',
    description: 'Generate face portrait via SD1.5 diffusion model. Prompt-guided.',
    engine: 'SD15',
    requires: [],
    defaults: { width: 512, height: 512, steps: 25 },
  },
  wf03_face_upload: {
    id: 'wf03_face_upload',
    step: 'FACE',
    label: 'Upload Face',
    description: 'Upload an existing photo as the identity anchor.',
    engine: 'UTILITY',
    requires: [],
  },

  // ═══════ BODY ═══════
  wf04_body_anchor: {
    id: 'wf04_body_anchor',
    step: 'BODY',
    label: 'Body Base (InstantID SDXL)',
    description: 'Generate full body from face reference with identity preservation. Uses SDXL.',
    engine: 'SDXL',
    requires: ['ref_image'],
    defaults: { width: 1024, height: 1536, steps: 30 },
  },
  wf05_body_pose: {
    id: 'wf05_body_pose',
    step: 'BODY',
    label: 'Body + Pose (OpenPose SDXL)',
    description: 'Body generation with pose control via OpenPose ControlNet. Uses SDXL.',
    engine: 'SDXL',
    requires: ['ref_image', 'pose_image'],
    advanced: true,
    defaults: { width: 1024, height: 1536, steps: 30 },
  },
  wf06_body_sdxl: {
    id: 'wf06_body_sdxl',
    step: 'BODY',
    label: 'Body Base (SDXL)',
    description: 'Higher quality body generation using SDXL models.',
    engine: 'SDXL',
    requires: ['ref_image'],
    advanced: true,
    defaults: { width: 1024, height: 1536, steps: 30 },
  },

  // ═══════ OUTFIT ═══════
  wf07_outfit_default: {
    id: 'wf07_outfit_default',
    step: 'OUTFIT',
    label: 'Outfit (InstantID SDXL)',
    description: 'Generate outfit variations preserving identity from body anchor. Uses SDXL.',
    engine: 'SDXL',
    requires: ['ref_image'],
    defaults: { width: 1024, height: 1536, steps: 25 },
  },
  wf08_outfit_photomaker: {
    id: 'wf08_outfit_photomaker',
    step: 'OUTFIT',
    label: 'Outfit (PhotoMaker)',
    description: 'Higher identity fidelity using PhotoMaker V2 encoder.',
    engine: 'SD15',
    requires: ['ref_image'],
    advanced: true,
  },
  wf09_outfit_sdxl: {
    id: 'wf09_outfit_sdxl',
    step: 'OUTFIT',
    label: 'Outfit (SDXL)',
    description: 'High-quality outfit generation using SDXL models.',
    engine: 'SDXL',
    requires: ['ref_image'],
    advanced: true,
    defaults: { width: 1024, height: 1536, steps: 25 },
  },

  // ═══════ REPAIR ═══════
  wf10_faceswap_repair: {
    id: 'wf10_faceswap_repair',
    step: 'REPAIR_FACE',
    label: 'Face Swap Repair',
    description: 'Swap face from identity anchor onto body image. Fixes identity drift.',
    engine: 'UTILITY',
    requires: ['subject_image', 'ref_image'],
  },
  wf11_identity_reproject: {
    id: 'wf11_identity_reproject',
    step: 'REPAIR_FACE',
    label: 'Identity Reprojection',
    description: 'Subtle identity correction via img2img with InstantID. Uses SDXL.',
    engine: 'SDXL',
    requires: ['subject_image', 'ref_image'],
    defaults: { denoise: 0.45, steps: 20, cfg: 5.0 },
  },

  // ═══════ EDIT ═══════
  wf12_inpaint_outfit: {
    id: 'wf12_inpaint_outfit',
    step: 'EDIT_OUTFIT',
    label: 'Inpaint Outfit',
    description: 'Replace clothing region with mask-guided inpainting.',
    engine: 'SD15',
    requires: ['subject_image', 'mask_image'],
    defaults: { denoise: 0.85, steps: 25 },
  },
  wf13_bg_replace: {
    id: 'wf13_bg_replace',
    step: 'EDIT_BG',
    label: 'Background Replace',
    description: 'Replace background while preserving character. Auto-segments with Rembg.',
    engine: 'SD15',
    requires: ['subject_image'],
    defaults: { denoise: 1.0, steps: 25, sampler: 'euler_ancestral', scheduler: 'normal' },
  },
  wf14_expression_change: {
    id: 'wf14_expression_change',
    step: 'EDIT_EXPRESSION',
    label: 'Expression Change',
    description: 'Change facial expression via face-region inpainting.',
    engine: 'SD15',
    requires: ['subject_image', 'mask_image'],
    defaults: { denoise: 0.55, steps: 20, cfg: 5.0 },
  },
  wf15_pose_adjust: {
    id: 'wf15_pose_adjust',
    step: 'EDIT_POSE',
    label: 'Pose Adjustment',
    description: 'Re-pose a character using OpenPose ControlNet.',
    engine: 'SD15',
    requires: ['ref_image', 'pose_image'],
    advanced: true,
    defaults: { denoise: 0.7 },
  },

  // ═══════ SPECIAL ═══════
  wf16_portrait: {
    id: 'wf16_portrait',
    step: 'PORTRAIT',
    label: 'Portrait Headshot',
    description: 'High-quality square portrait from face reference. Studio lighting. SDXL.',
    engine: 'SDXL',
    requires: ['ref_image'],
    defaults: { width: 1024, height: 1024, steps: 30 },
  },
  wf17_studio_photoshoot: {
    id: 'wf17_studio_photoshoot',
    step: 'OUTFIT',
    label: 'Studio Photoshoot',
    description: 'Full body with professional lighting presets.',
    engine: 'SD15',
    requires: ['ref_image'],
    advanced: true,
  },
  wf18_fantasy: {
    id: 'wf18_fantasy',
    step: 'OUTFIT',
    label: 'Fantasy Character',
    description: 'Fantasy/RPG style character using aZovya RPG Artist checkpoint.',
    engine: 'SD15',
    requires: ['ref_image'],
    advanced: true,
  },
  wf19_anime: {
    id: 'wf19_anime',
    step: 'OUTFIT',
    label: 'Anime Character',
    description: 'Anime-style character using Pony/NoobAI/MeinaMix checkpoints.',
    engine: 'SD15',
    requires: ['ref_image'],
    advanced: true,
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Get all presets for a given wizard step. */
export function presetsForStep(
  step: WizardStep,
  includeAdvanced = false,
): WorkflowPreset[] {
  return Object.values(WORKFLOW_PRESETS).filter(
    (p) => p.step === step && (includeAdvanced || !p.advanced),
  )
}

/** Auto-select the best workflow for a step based on capabilities. */
export function pickWizardWorkflow(opts: {
  step: WizardStep
  wantsPose?: boolean
  wantsSdxl?: boolean
  wantsPhotoMaker?: boolean
  hasStyleGAN?: boolean
  capabilities?: { photomaker?: boolean; openpose?: boolean; sdxl?: boolean }
}): WorkflowId {
  const { step, wantsPose, wantsSdxl, wantsPhotoMaker, hasStyleGAN, capabilities } = opts

  if (step === 'FACE') {
    if (hasStyleGAN) return 'wf01_face_stylegan'
    return 'wf02_face_diffusion'
  }

  if (step === 'BODY') {
    if (wantsPose && capabilities?.openpose) return 'wf05_body_pose'
    if (wantsSdxl && capabilities?.sdxl) return 'wf06_body_sdxl'
    return 'wf04_body_anchor'
  }

  if (step === 'OUTFIT') {
    if (wantsSdxl && capabilities?.sdxl) return 'wf09_outfit_sdxl'
    if (wantsPhotoMaker && capabilities?.photomaker) return 'wf08_outfit_photomaker'
    return 'wf07_outfit_default'
  }

  if (step === 'PORTRAIT') return 'wf16_portrait'
  if (step === 'REPAIR_FACE') return 'wf11_identity_reproject'
  if (step === 'EDIT_OUTFIT') return 'wf12_inpaint_outfit'
  if (step === 'EDIT_BG') return 'wf13_bg_replace'
  if (step === 'EDIT_EXPRESSION') return 'wf14_expression_change'
  if (step === 'EDIT_POSE') return 'wf15_pose_adjust'

  return 'wf07_outfit_default'
}
