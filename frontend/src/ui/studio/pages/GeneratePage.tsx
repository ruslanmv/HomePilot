import React, { useState, useEffect } from 'react';
import { ContentRatingToggle } from '../components/ContentRatingToggle';
import { PresetCard } from '../components/PresetCard';
import { ImageGenerator } from '../components/ImageGenerator';
import { getTheme, themeToCSS } from '../styles/themes';

interface Preset {
  id: string;
  label: string;
  description: string;
  content_rating: 'sfw' | 'mature';
  requires_mature_mode: boolean;
  recommended_models: string[];
  sampler_settings: {
    sampler: string;
    steps: number;
    cfg_scale: number;
    clip_skip: number;
  };
  prompt_injection?: {
    positive_prefix: string;
    positive_suffix: string;
    negative: string;
  };
}

/**
 * Generate Page
 *
 * Main image generation interface combining:
 * - Content rating toggle
 * - Preset selector sidebar
 * - Image generator main area
 */
export const GeneratePage: React.FC = () => {
  const [contentRating, setContentRating] = useState<'sfw' | 'mature'>('sfw');
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<Preset | null>(null);
  const [matureEnabled, setMatureEnabled] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedImage, setGeneratedImage] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const theme = getTheme(contentRating);

  // Fetch presets
  useEffect(() => {
    const fetchPresets = async () => {
      try {
        const res = await fetch('/studio/presets');
        const data = await res.json();
        setPresets(data.presets || []);
        setMatureEnabled(data.mature_mode_enabled || false);
      } catch (e) {
        console.error('Failed to fetch presets:', e);
      }
    };
    fetchPresets();
  }, []);

  // Fetch NSFW info
  useEffect(() => {
    const fetchNSFWInfo = async () => {
      try {
        const res = await fetch('/studio/image/nsfw-info');
        const data = await res.json();
        setMatureEnabled(data.nsfw_enabled || false);
      } catch (e) {
        console.error('Failed to fetch NSFW info:', e);
      }
    };
    fetchNSFWInfo();
  }, []);

  const handleRatingChange = async (rating: 'sfw' | 'mature') => {
    setContentRating(rating);
    // In real app, would update video/project content rating via API
  };

  const handleSelectPreset = (preset: Preset) => {
    setSelectedPreset(preset);
    // Auto-switch to mature mode if preset requires it
    if (preset.requires_mature_mode && contentRating !== 'mature') {
      // This would trigger the age verification modal via ContentRatingToggle
      // For now, just warn
      console.log('This preset requires mature mode');
    }
  };

  const handleGenerate = async (
    prompt: string,
    negPrompt: string,
    settings: any
  ) => {
    setIsGenerating(true);
    try {
      // In real app, would call ComfyUI generation API
      // Simulating generation delay
      await new Promise((resolve) => setTimeout(resolve, 2000));

      // Placeholder - in real app would get generated image URL
      setGeneratedImage('/api/placeholder/512/768');
    } catch (e) {
      console.error('Generation failed:', e);
    } finally {
      setIsGenerating(false);
    }
  };

  // Prepare preset settings for generator
  const presetSettings = selectedPreset
    ? {
        steps: selectedPreset.sampler_settings.steps,
        cfg: selectedPreset.sampler_settings.cfg_scale,
        sampler: selectedPreset.sampler_settings.sampler,
        clipSkip: selectedPreset.sampler_settings.clip_skip,
        model: selectedPreset.recommended_models[0],
      }
    : undefined;

  return (
    <div className="generate-page" style={{ '--theme': themeToCSS(theme) } as React.CSSProperties}>
      <style>{`
        .generate-page {
          ${themeToCSS(theme)}
          min-height: 100vh;
          background: var(--color-background);
          color: var(--color-text);
          display: flex;
          flex-direction: column;
        }

        .page-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 24px;
          background: var(--color-surface);
          border-bottom: 1px solid var(--color-border);
        }

        .header-left {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .logo {
          font-size: 20px;
          font-weight: 700;
          color: var(--color-primary);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .project-name {
          font-size: 14px;
          color: var(--color-text-muted);
          padding: 6px 12px;
          background: var(--color-background);
          border-radius: 6px;
          border: 1px solid var(--color-border);
        }

        .page-content {
          flex: 1;
          display: flex;
          overflow: hidden;
        }

        .sidebar {
          width: 320px;
          background: var(--color-surface);
          border-right: 1px solid var(--color-border);
          overflow-y: auto;
          padding: 20px;
          transition: width 0.3s, padding 0.3s;
        }

        .sidebar.collapsed {
          width: 60px;
          padding: 20px 10px;
        }

        .sidebar-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }

        .sidebar-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--color-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .collapse-btn {
          background: none;
          border: none;
          color: var(--color-text-muted);
          cursor: pointer;
          padding: 4px;
          font-size: 16px;
        }

        .preset-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .main-area {
          flex: 1;
          padding: 24px;
          overflow-y: auto;
        }

        .status-bar {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 10px 24px;
          background: var(--color-surface);
          border-top: 1px solid var(--color-border);
          font-size: 12px;
          color: var(--color-text-muted);
        }

        .status-item {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }

        .status-dot.sfw {
          background: #10B981;
        }

        .status-dot.mature {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
        }

        @media (max-width: 1024px) {
          .sidebar {
            position: fixed;
            left: 0;
            top: 64px;
            bottom: 40px;
            z-index: 100;
            transform: translateX(-100%);
            box-shadow: var(--shadow-lg);
          }

          .sidebar:not(.collapsed) {
            transform: translateX(0);
          }
        }
      `}</style>

      {/* Header */}
      <header className="page-header">
        <div className="header-left">
          <div className="logo">
            <span>&#127916;</span>
            Studio
          </div>
          <div className="project-name">My Anime Project</div>
        </div>

        <ContentRatingToggle
          contentRating={contentRating}
          onRatingChange={handleRatingChange}
          disabled={!matureEnabled && contentRating === 'sfw'}
        />
      </header>

      {/* Main Content */}
      <div className="page-content">
        {/* Sidebar - Presets */}
        <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="sidebar-header">
            {!sidebarCollapsed && <span className="sidebar-title">Presets</span>}
            <button
              className="collapse-btn"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            >
              {sidebarCollapsed ? '\u25B6' : '\u25C0'}
            </button>
          </div>

          {!sidebarCollapsed && (
            <div className="preset-list">
              {presets.map((preset) => (
                <PresetCard
                  key={preset.id}
                  preset={preset}
                  selected={selectedPreset?.id === preset.id}
                  onSelect={handleSelectPreset}
                  matureEnabled={matureEnabled}
                />
              ))}

              {presets.length === 0 && (
                <p style={{ color: 'var(--color-text-muted)', fontSize: '13px' }}>
                  Loading presets...
                </p>
              )}
            </div>
          )}
        </aside>

        {/* Main - Generator */}
        <main className="main-area">
          <ImageGenerator
            contentRating={contentRating}
            onGenerate={handleGenerate}
            isGenerating={isGenerating}
            generatedImage={generatedImage}
            presetSettings={presetSettings}
            presetPositivePrefix={selectedPreset?.prompt_injection?.positive_prefix || ''}
            presetPositiveSuffix={selectedPreset?.prompt_injection?.positive_suffix || ''}
            presetNegative={selectedPreset?.prompt_injection?.negative || ''}
          />
        </main>
      </div>

      {/* Status Bar */}
      <footer className="status-bar">
        <div className="status-item">
          <span className={`status-dot ${contentRating}`} />
          Policy: {contentRating === 'mature' ? 'Mature (NSFW)' : 'SFW'}
        </div>
        <div className="status-item">
          Provider: ComfyUI
        </div>
        {selectedPreset && (
          <div className="status-item">
            Preset: {selectedPreset.label}
          </div>
        )}
        {matureEnabled && contentRating === 'mature' && (
          <div className="status-item" style={{ color: '#F59E0B' }}>
            &#128286; Explicit content allowed
          </div>
        )}
      </footer>
    </div>
  );
};

export default GeneratePage;
