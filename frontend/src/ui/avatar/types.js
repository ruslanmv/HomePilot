/**
 * Avatar Studio — TypeScript types (mirrors backend schemas).
 */
export const RECOMMENDED_CHECKPOINTS = [
    {
        id: 'dreamshaper8',
        label: 'DreamShaper 8',
        description: 'SD 1.5 — balanced portraits, fast, low VRAM',
        filename: 'dreamshaper_8.safetensors',
    },
    {
        id: 'realisticvision',
        label: 'Realistic Vision V5.1',
        description: 'SD 1.5 — photorealistic faces, great skin detail',
        filename: 'realisticVisionV51.safetensors',
    },
    {
        id: 'epicrealism',
        label: 'epiCRealism',
        description: 'SD 1.5 — hyperrealistic portraits, natural lighting',
        filename: 'epicrealism_pureEvolution.safetensors',
    },
];
/** Available body workflow methods for the Advanced Settings selector. */
export const BODY_WORKFLOW_OPTIONS = [
    {
        id: 'disabled',
        label: 'Disabled',
        description: 'Skip body generation. Go directly from face to outfits (original workflow).',
    },
    {
        id: 'default',
        label: 'InstantID (SDXL)',
        description: 'Default face-to-body with identity preservation. Balanced speed and quality.',
        badge: 'Default',
    },
    {
        id: 'sdxl_hq',
        label: 'SDXL High Quality',
        description: 'Higher quality 1024x1536 generation. Slower but more detailed output.',
        badge: 'HQ',
    },
    {
        id: 'pose',
        label: 'Pose Guided',
        description: 'Body generation with OpenPose control. Requires OpenPose ControlNet model. Falls back to default if missing.',
        badge: 'Pose',
    },
];
