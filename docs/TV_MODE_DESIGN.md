# TV Mode Design Specification

## Overview

TV Mode is an immersive, fullscreen cinematic experience for viewing generated stories. It transforms the current manual scene-by-scene navigation into a lean-back, "Netflix-style" viewing experience where scenes auto-play with smooth transitions while the next scene prefetches in the background.

---

## Current State vs. Target State

### Current Flow (Manual)
```
Click "New Story" → Enter premise → Create
Click "Generate First Scene" → Wait → Scene appears
Click "Next Scene" repeatedly for each scene
Manually navigate between scenes
```

### Target Flow (TV Mode)
```
Create Story → Click "🎬 TV Mode" → Sit back and watch
Scenes auto-play → Next scene prefetches → Seamless transitions
Tap to show controls → Escape/Exit to return
```

---

## User Interface Design

### 1. Entry Point: TV Mode Button

Location: Story playback header (next to existing controls)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Stories    "The Neon Detective"    [🎬 TV Mode]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                     [Current Scene View]                        │
│                                                                 │
│  "Rain hammered the neon-soaked streets..."                     │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  [⏮] [▶️] [⏭]    ═══════●═══════════    3/24    [+ Next]       │
└─────────────────────────────────────────────────────────────────┘
```

### 2. TV Mode Interface (Fullscreen)

#### Default State (Controls Hidden)
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                                                                 │
│                                                                 │
│                    [FULLSCREEN SCENE IMAGE]                     │
│                                                                 │
│                                                                 │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  "Rain hammered the neon-soaked streets of New Naples,    │  │
│  │   where Detective Kai Chen hunted shadows..."             │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│                                          ◉ Generating next...   │
└─────────────────────────────────────────────────────────────────┘
```

#### Controls Visible State (Tap/Mouse Move)
```
┌─────────────────────────────────────────────────────────────────┐
│  [✕ Exit]                              Scene 3 of 24   [⚙️]    │  ← Top bar
│                                                                 │
│                                                                 │
│                    [FULLSCREEN SCENE IMAGE]                     │
│                                                                 │
│                                                                 │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  "Rain hammered the neon-soaked streets of New Naples,    │  │
│  │   where Detective Kai Chen hunted shadows..."             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [⏮ Prev] [⏸ Pause] [⏭ Next]    ●═══════════════    3/24      │  ← Bottom bar
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Loading/Transition States

#### Scene Transition (Crossfade)
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│          [Previous Scene]  →→→  [Next Scene]                    │
│              (fading)          (appearing)                      │
│                                                                 │
│                    opacity: 0.3 → 1.0                           │
│                    duration: 800ms                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Waiting for Scene Generation
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    [Current Scene Image]                        │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              ◉◉◉ Generating next scene...                 │  │
│  │                                                           │  │
│  │              This scene will continue playing             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### File Structure
```
frontend/src/ui/studio/
├── components/
│   └── TVMode/
│       ├── TVModeContainer.tsx      # Main fullscreen container
│       ├── TVModePlayer.tsx         # Scene display & transitions
│       ├── TVModeControls.tsx       # Playback controls overlay
│       ├── TVModeProgress.tsx       # Progress bar component
│       ├── TVModeNarration.tsx      # Text display with animations
│       ├── TVModeSettings.tsx       # Settings popover (speed, etc.)
│       ├── TVModeLoadingIndicator.tsx
│       ├── useTVMode.ts             # Main hook for TV Mode logic
│       ├── usePrefetch.ts           # Scene prefetching hook
│       ├── useAutoHideControls.ts   # Auto-hide controls logic
│       └── types.ts                 # TV Mode types
├── pages/
│   └── StoryPage.tsx                # Add TV Mode button here
└── stores/
    └── tvModeStore.ts               # Zustand store for TV Mode state
```

### Component Hierarchy
```
<TVModeContainer>
  ├── <TVModePlayer>
  │   ├── <SceneImage />           # Current scene image
  │   ├── <SceneImage />           # Next scene (for crossfade)
  │   └── <TVModeNarration />      # Text overlay
  │
  ├── <TVModeControls>             # Auto-hiding overlay
  │   ├── <TopBar>
  │   │   ├── <ExitButton />
  │   │   ├── <SceneCounter />
  │   │   └── <SettingsButton />
  │   └── <BottomBar>
  │       ├── <PlaybackButtons />
  │       └── <TVModeProgress />
  │
  ├── <TVModeLoadingIndicator />   # "Generating next..." indicator
  └── <TVModeSettings />           # Popover for settings
</TVModeContainer>
```

---

## State Management

### TV Mode Store (Zustand)

```typescript
// frontend/src/ui/studio/stores/tvModeStore.ts

interface TVModeState {
  // Mode State
  isActive: boolean;
  isFullscreen: boolean;

  // Playback State
  isPlaying: boolean;
  currentSceneIndex: number;
  scenes: Scene[];

  // Prefetch State
  isPrefetching: boolean;
  prefetchedScene: Scene | null;
  prefetchError: string | null;

  // UI State
  controlsVisible: boolean;
  controlsTimeout: number | null;

  // Settings
  sceneDuration: number;          // Default: scene.duration_s or 8 seconds
  transitionDuration: number;     // Default: 800ms
  autoHideDelay: number;          // Default: 3000ms
  narrationPosition: 'bottom' | 'top';
  narrationSize: 'small' | 'medium' | 'large';

  // Actions
  enterTVMode: (sessionId: string, scenes: Scene[], startIndex?: number) => void;
  exitTVMode: () => void;

  play: () => void;
  pause: () => void;
  togglePlay: () => void;

  nextScene: () => void;
  prevScene: () => void;
  goToScene: (index: number) => void;

  showControls: () => void;
  hideControls: () => void;
  resetControlsTimer: () => void;

  addScene: (scene: Scene) => void;
  setPrefetchState: (state: Partial<PrefetchState>) => void;
  updateSettings: (settings: Partial<TVModeSettings>) => void;
}
```

### Scene Type

```typescript
interface Scene {
  idx: number;
  narration: string;
  image_prompt: string;
  negative_prompt?: string;
  duration_s: number;
  tags: string[];
  audio?: string;        // TTS audio URL (future)
  image?: string;        // Generated image URL
  status: 'pending' | 'generating' | 'ready' | 'error';
}
```

---

## Playback Logic

### Auto-Play Flow

```
┌──────────────────────────────────────────────────────────────┐
│                      TV Mode Started                          │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  1. Display current scene (index N)                          │
│  2. Start scene timer (duration_s seconds)                   │
│  3. Begin prefetching scene N+1 (if not already ready)       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Scene Timer Expires                        │
└──────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            │                                   │
            ▼                                   ▼
┌────────────────────────┐        ┌────────────────────────────┐
│  Next scene is ready   │        │  Next scene NOT ready      │
└────────────────────────┘        └────────────────────────────┘
            │                                   │
            ▼                                   ▼
┌────────────────────────┐        ┌────────────────────────────┐
│  Crossfade transition  │        │  Show "Generating..." msg  │
│  800ms animation       │        │  Keep current scene        │
│  Advance to N+1        │        │  Wait for generation       │
└────────────────────────┘        └────────────────────────────┘
            │                                   │
            │                                   ▼
            │                     ┌────────────────────────────┐
            │                     │  Scene ready? → Transition │
            │                     └────────────────────────────┘
            │                                   │
            └───────────────┬───────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Repeat from step 1 until:                                   │
│  - User pauses                                               │
│  - User exits TV Mode                                        │
│  - Last scene reached (show "Story Complete" then stop)      │
│  - Error occurs                                              │
└──────────────────────────────────────────────────────────────┘
```

### Prefetch Logic

```typescript
// usePrefetch.ts

const usePrefetch = (sessionId: string, currentIndex: number, scenes: Scene[]) => {
  const prefetchNext = useCallback(async () => {
    const nextIndex = currentIndex + 1;

    // Don't prefetch if already at max or scene exists
    if (nextIndex >= MAX_SCENES || scenes[nextIndex]?.status === 'ready') {
      return;
    }

    setPrefetching(true);

    try {
      // Call /story/next endpoint
      const response = await fetch(`${backendUrl}/story/next`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${apiKey}` },
        body: JSON.stringify({ session_id: sessionId })
      });

      const newScene = await response.json();
      addScene(newScene);

    } catch (error) {
      setPrefetchError(error.message);
    } finally {
      setPrefetching(false);
    }
  }, [sessionId, currentIndex, scenes]);

  // Auto-trigger prefetch when current scene starts
  useEffect(() => {
    if (isPlaying && scenes[currentIndex + 1]?.status !== 'ready') {
      prefetchNext();
    }
  }, [currentIndex, isPlaying]);

  return { prefetchNext, isPrefetching, prefetchError };
};
```

---

## User Interactions

### Keyboard Controls

| Key | Action |
|-----|--------|
| `Escape` | Exit TV Mode |
| `Space` | Play/Pause |
| `→` / `L` | Next scene |
| `←` / `J` | Previous scene |
| `F` | Toggle fullscreen |
| `M` | Mute/Unmute (when audio available) |
| `↑` / `↓` | Adjust volume (when audio available) |
| Any key | Show controls |

### Mouse/Touch Interactions

| Action | Result |
|--------|--------|
| Move mouse | Show controls (auto-hide after 3s) |
| Click anywhere | Show controls |
| Click play/pause button | Toggle playback |
| Click progress bar | Jump to scene |
| Click exit button | Exit TV Mode |
| Double-click | Toggle fullscreen |
| Swipe left (touch) | Next scene |
| Swipe right (touch) | Previous scene |

### Gesture Detection (Touch)

```typescript
const useSwipeGesture = (onSwipeLeft: () => void, onSwipeRight: () => void) => {
  const touchStartX = useRef(0);
  const minSwipeDistance = 50;

  const handleTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  };

  const handleTouchEnd = (e: TouchEvent) => {
    const deltaX = e.changedTouches[0].clientX - touchStartX.current;

    if (Math.abs(deltaX) > minSwipeDistance) {
      if (deltaX > 0) onSwipeRight();  // Previous scene
      else onSwipeLeft();               // Next scene
    }
  };

  return { handleTouchStart, handleTouchEnd };
};
```

---

## Transitions & Animations

### Scene Transition (Crossfade)

```css
/* Crossfade animation */
.scene-image {
  position: absolute;
  inset: 0;
  transition: opacity 800ms ease-in-out;
}

.scene-image.entering {
  opacity: 0;
  animation: fadeIn 800ms ease-in-out forwards;
}

.scene-image.exiting {
  animation: fadeOut 800ms ease-in-out forwards;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes fadeOut {
  from { opacity: 1; }
  to { opacity: 0; }
}
```

### Narration Text Animation

```css
/* Typewriter effect for narration */
.narration-text {
  animation: fadeSlideUp 600ms ease-out;
}

@keyframes fadeSlideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

### Controls Fade In/Out

```css
/* Controls overlay animation */
.controls-overlay {
  transition: opacity 300ms ease-in-out;
}

.controls-overlay.hidden {
  opacity: 0;
  pointer-events: none;
}

.controls-overlay.visible {
  opacity: 1;
  pointer-events: auto;
}
```

---

## Settings Panel

### Available Settings

```typescript
interface TVModeSettings {
  // Timing
  sceneDuration: number;       // 5-30 seconds, default: auto (from scene.duration_s)
  transitionDuration: number;  // 300-1500ms, default: 800ms

  // Display
  narrationPosition: 'bottom' | 'top';
  narrationSize: 'small' | 'medium' | 'large';
  showSceneNumber: boolean;

  // Behavior
  autoHideControls: boolean;
  autoHideDelay: number;       // 2-10 seconds, default: 3s
  pauseOnEnd: boolean;         // Pause on last scene or loop

  // Audio (future)
  enableTTS: boolean;
  ttsVoice: string;
  volume: number;
}
```

### Settings UI

```
┌─────────────────────────────┐
│  ⚙️ TV Mode Settings        │
├─────────────────────────────┤
│                             │
│  Scene Duration             │
│  [Auto ▾]  [  5s  |  10s  ] │
│                             │
│  Transition Speed           │
│  [Slow]  [Normal]  [Fast]   │
│                             │
│  Narration Position         │
│  [Bottom]  [Top]            │
│                             │
│  Text Size                  │
│  [S]  [M]  [L]              │
│                             │
│  ☑ Auto-hide controls       │
│  ☑ Show scene numbers       │
│                             │
│  [Reset to Defaults]        │
│                             │
└─────────────────────────────┘
```

---

## Error Handling

### Generation Failure

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    [Current Scene Image]                        │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ⚠️ Couldn't generate next scene                          │  │
│  │                                                           │  │
│  │  [Retry]  [Skip]  [Exit TV Mode]                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Network Error

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    [Last Known Scene]                           │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  📡 Connection lost                                        │  │
│  │                                                           │  │
│  │  TV Mode paused. Retrying...                              │  │
│  │  [Retry Now]  [Exit]                                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Story Complete

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    [Final Scene Image]                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │                    ✨ The End ✨                            │  │
│  │                                                           │  │
│  │            "The Neon Detective" - 24 scenes               │  │
│  │                                                           │  │
│  │  [Watch Again]  [Exit]  [Share]                           │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Accessibility

### Requirements

1. **Keyboard Navigation**: All controls accessible via keyboard
2. **Screen Reader Support**: ARIA labels on all interactive elements
3. **Reduced Motion**: Respect `prefers-reduced-motion` media query
4. **High Contrast**: Support high contrast mode
5. **Focus Indicators**: Clear focus states on all controls

### ARIA Labels

```tsx
<button aria-label="Exit TV Mode" onClick={exitTVMode}>
  <X size={24} />
</button>

<button aria-label={isPlaying ? "Pause" : "Play"} onClick={togglePlay}>
  {isPlaying ? <Pause /> : <Play />}
</button>

<div
  role="progressbar"
  aria-valuenow={currentSceneIndex + 1}
  aria-valuemin={1}
  aria-valuemax={scenes.length}
  aria-label={`Scene ${currentSceneIndex + 1} of ${scenes.length}`}
>
```

### Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  .scene-image,
  .narration-text,
  .controls-overlay {
    animation: none;
    transition: none;
  }
}
```

---

## Implementation Phases

### Phase 1: Core TV Mode (MVP)
- [ ] Create TVModeContainer with fullscreen API
- [ ] Implement basic scene display
- [ ] Add play/pause functionality
- [ ] Add prev/next navigation
- [ ] Implement auto-advance timer
- [ ] Add exit functionality (button + Escape key)
- [ ] Basic crossfade transitions

### Phase 2: Prefetching & Polish
- [ ] Implement scene prefetching logic
- [ ] Add loading indicator during generation
- [ ] Handle generation errors gracefully
- [ ] Implement auto-hide controls
- [ ] Add keyboard shortcuts
- [ ] Add touch/swipe gestures

### Phase 3: Settings & Enhancements
- [ ] Create settings panel
- [ ] Persist settings to localStorage
- [ ] Add "Story Complete" screen
- [ ] Add progress bar click-to-seek
- [ ] Add scene thumbnail previews on progress hover

### Phase 4: Audio & Future Features
- [ ] Integrate TTS for narration
- [ ] Add background music support
- [ ] Add volume controls
- [ ] Add playback speed control
- [ ] Add "Share" functionality

---

## API Integration

### Required Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/story/next` | POST | Generate next scene (existing) |
| `/story/scenes/{session_id}` | GET | Get all scenes for session (may need to add) |
| `/story/scene/{session_id}/{idx}` | GET | Get specific scene (may need to add) |

### Prefetch Request

```typescript
// Called when entering TV Mode or advancing scenes
const prefetchNextScene = async (sessionId: string) => {
  const response = await fetch(`${backendUrl}/story/next`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      session_id: sessionId,
      refine_image_prompt: true
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to generate scene: ${response.statusText}`);
  }

  return response.json();
};
```

---

## Performance Considerations

### Image Preloading

```typescript
// Preload next scene's image while current scene plays
const preloadImage = (url: string): Promise<void> => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = reject;
    img.src = url;
  });
};

// In prefetch logic
if (nextScene.image) {
  await preloadImage(nextScene.image);
}
```

### Memory Management

- Keep only current scene + next scene in memory
- Dispose of old scene images after transition
- Use `object-fit: contain` to avoid image scaling issues

### Debouncing

```typescript
// Debounce control visibility toggle
const showControlsDebounced = useMemo(
  () => debounce(() => showControls(), 100),
  [showControls]
);
```

---

## Testing Checklist

### Functional Tests
- [ ] TV Mode enters fullscreen correctly
- [ ] Exit button returns to normal view
- [ ] Escape key exits TV Mode
- [ ] Play/pause works
- [ ] Scene auto-advances after duration
- [ ] Prefetch triggers during scene playback
- [ ] Manual navigation (prev/next) works
- [ ] Progress bar shows correct scene
- [ ] Controls auto-hide after 3 seconds
- [ ] Mouse movement shows controls

### Edge Cases
- [ ] Single scene story
- [ ] Last scene behavior
- [ ] Network failure during prefetch
- [ ] Generation error handling
- [ ] Rapid prev/next clicking
- [ ] Browser fullscreen API failures

### Browser Compatibility
- [ ] Chrome
- [ ] Firefox
- [ ] Safari
- [ ] Edge
- [ ] Mobile Chrome (Android)
- [ ] Mobile Safari (iOS)

---

## Appendix: Component Mockup Code

### TVModeContainer.tsx (Skeleton)

```tsx
import React, { useEffect, useRef } from 'react';
import { useTVModeStore } from '../stores/tvModeStore';
import { TVModePlayer } from './TVModePlayer';
import { TVModeControls } from './TVModeControls';
import { TVModeLoadingIndicator } from './TVModeLoadingIndicator';

export function TVModeContainer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { isActive, exitTVMode, showControls, hideControls } = useTVModeStore();

  // Enter fullscreen on mount
  useEffect(() => {
    if (isActive && containerRef.current) {
      containerRef.current.requestFullscreen?.();
    }

    return () => {
      document.exitFullscreen?.();
    };
  }, [isActive]);

  // Keyboard handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape':
          exitTVMode();
          break;
        case ' ':
          togglePlay();
          break;
        // ... more keys
      }
      showControls();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (!isActive) return null;

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 bg-black z-50"
      onMouseMove={showControls}
      onClick={showControls}
    >
      <TVModePlayer />
      <TVModeControls />
      <TVModeLoadingIndicator />
    </div>
  );
}
```

---

## Summary

TV Mode transforms the story viewing experience from manual clicking to immersive cinema. Key features:

1. **One-Click Entry**: Single button enters fullscreen mode
2. **Auto-Play**: Scenes advance automatically based on duration
3. **Smart Prefetch**: Next scene generates while you watch
4. **Smooth Transitions**: Crossfade animations between scenes
5. **Minimal UI**: Controls auto-hide, appear on interaction
6. **Easy Exit**: Escape key or button returns to normal view

This design prioritizes the "lean-back" experience while maintaining user control when needed.
