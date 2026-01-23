export interface TVScene {
  idx: number;
  narration: string;
  image_prompt: string;
  negative_prompt?: string;
  duration_s: number;
  tags: Record<string, string>;
  audio?: string | null;
  audio_url?: string | null;
  image?: string | null;
  image_url?: string | null;
  status: "pending" | "generating" | "ready" | "error";
  imageStatus?: "pending" | "generating" | "ready" | "error";
}

export interface TVModeSettings {
  sceneDuration: number;
  transitionDuration: number;
  autoHideDelay: number;
  narrationPosition: "bottom" | "top";
  narrationSize: "small" | "medium" | "large";
  showSceneNumber: boolean;
  pauseOnEnd: boolean;
}

export interface TVModeProps {
  sessionId: string;
  storyTitle: string;
  scenes: TVScene[];
  onGenerateNext: () => Promise<TVScene | null>;
  onExit?: () => void;
}
