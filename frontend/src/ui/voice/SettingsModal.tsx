/**
 * Settings Modal Component
 *
 * System settings modal for HomePilot Voice UI.
 * Contains advanced audio settings previously in the voice settings panel.
 *
 * Features:
 * - Audio meter toggle
 * - Browser voice selection
 * - Language settings
 */

import React from 'react';
import {
  X,
  Activity,
  Volume2,
  Globe,
  Settings,
} from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  // Audio settings
  showAudioMeter?: boolean;
  setShowAudioMeter?: (show: boolean) => void;
  browserVoices?: SpeechSynthesisVoice[];
  selectedBrowserVoice?: string;
  setSelectedBrowserVoice?: (voiceURI: string) => void;
}

export default function SettingsModal({
  isOpen,
  onClose,
  showAudioMeter,
  setShowAudioMeter,
  browserVoices,
  selectedBrowserVoice,
  setSelectedBrowserVoice,
}: SettingsModalProps) {
  if (!isOpen) return null;

  const toggleOn = 'bg-white/15 border border-white/20';
  const toggleOff = 'bg-[#1F1F1F] border border-transparent';

  // Filter English voices for cleaner display
  const englishVoices = browserVoices?.filter((v) =>
    v.lang.startsWith('en')
  ) || [];

  // Group voices by language
  const voicesByLang = browserVoices?.reduce((acc, voice) => {
    const lang = voice.lang.split('-')[0];
    if (!acc[lang]) acc[lang] = [];
    acc[lang].push(voice);
    return acc;
  }, {} as Record<string, SpeechSynthesisVoice[]>) || {};

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4 hp-fade-in">
      <div className="w-full max-w-[480px] bg-[#121212] border border-white/10 rounded-[24px] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
              <Settings size={20} className="text-white/70" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">System Settings</h2>
              <p className="text-[11px] text-white/40">HomePilot Voice Configuration</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-white/60 hover:bg-white/10 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-6 max-h-[60vh] overflow-y-auto hp-scroll">
          {/* Audio Settings Section */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-white/80">
              <Activity size={16} className="text-white/50" />
              <span>Audio Settings</span>
            </div>

            {/* Audio Level Meter Toggle */}
            {setShowAudioMeter && (
              <div className="flex items-center justify-between p-3 rounded-[12px] bg-white/5">
                <div className="flex items-center gap-3">
                  <Activity size={16} className="text-white/50" />
                  <div>
                    <span className="text-[13px] text-white/80 block">Show Audio Meter</span>
                    <span className="text-[10px] text-white/40">Display real-time audio level in hands-free mode</span>
                  </div>
                </div>
                <button
                  onClick={() => setShowAudioMeter(!showAudioMeter)}
                  className={`w-12 h-6 rounded-full transition-all ${
                    showAudioMeter ? toggleOn : toggleOff
                  }`}
                >
                  <div
                    className={`w-5 h-5 rounded-full bg-white shadow-sm transition-transform ${
                      showAudioMeter ? 'translate-x-6' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
            )}

            {/* Browser Voice Selection */}
            {browserVoices && browserVoices.length > 0 && setSelectedBrowserVoice && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 px-1">
                  <Volume2 size={14} className="text-white/50" />
                  <span className="text-[12px] text-white/60">System Voice</span>
                </div>
                <select
                  value={selectedBrowserVoice || ''}
                  onChange={(e) => setSelectedBrowserVoice(e.target.value)}
                  className="w-full bg-[#1a1a1a] border border-white/10 rounded-[12px] px-4 py-3 text-[13px] text-white/80 focus:outline-none focus:border-white/20 transition-colors appearance-none cursor-pointer"
                >
                  <option value="">Auto (Best Match)</option>
                  {englishVoices.length > 0 && (
                    <optgroup label="English Voices">
                      {englishVoices.map((v) => (
                        <option key={v.voiceURI} value={v.voiceURI}>
                          {v.name} ({v.lang})
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {Object.entries(voicesByLang)
                    .filter(([lang]) => lang !== 'en')
                    .map(([lang, voices]) => (
                      <optgroup key={lang} label={`${lang.toUpperCase()} Voices`}>
                        {voices.map((v) => (
                          <option key={v.voiceURI} value={v.voiceURI}>
                            {v.name} ({v.lang})
                          </option>
                        ))}
                      </optgroup>
                    ))}
                </select>
                <p className="text-[10px] text-white/30 px-1">
                  {browserVoices.length} system voices available
                </p>
              </div>
            )}
          </div>

          {/* Language Section */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-white/80">
              <Globe size={16} className="text-white/50" />
              <span>Language & Recognition</span>
            </div>
            <div className="p-3 rounded-[12px] bg-white/5">
              <p className="text-[12px] text-white/50">
                Voice recognition uses your browser's default language settings.
                To change the recognition language, update your browser's language preferences.
              </p>
            </div>
          </div>

          {/* Info Section */}
          <div className="p-4 rounded-[16px] bg-gradient-to-br from-white/5 to-transparent border border-white/5">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center shrink-0">
                <Activity size={16} className="text-white/50" />
              </div>
              <div>
                <h3 className="text-[13px] font-semibold text-white/80 mb-1">Studio Quality Audio</h3>
                <p className="text-[11px] text-white/40 leading-relaxed">
                  HomePilot Voice uses adaptive noise suppression, echo cancellation,
                  and automatic gain control for crystal-clear audio capture.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-5 border-t border-white/10">
          <button
            onClick={onClose}
            className="w-full h-[48px] rounded-full bg-white text-black text-sm font-bold hover:bg-gray-200 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
