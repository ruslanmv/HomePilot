/**
 * Settings Modal Component
 *
 * System settings modal for HomePilot Voice UI.
 * Contains advanced audio settings and content preferences.
 *
 * Features:
 * - Audio meter toggle
 * - Browser voice selection
 * - Language settings
 * - Adult content gating (18+)
 */

import React, { useState, useEffect } from 'react';
import {
  X,
  Activity,
  Volume2,
  Globe,
  Settings,
  Shield,
  AlertTriangle,
} from 'lucide-react';
import {
  isAdultContentEnabled,
  isAgeConfirmed,
  setAdultContentEnabled,
  setAgeConfirmed,
} from './personalityGating';

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
  // Adult content state
  const [adultEnabled, setAdultEnabled] = useState(false);
  const [ageConfirmed, setAgeConfirmedState] = useState(false);
  const [showAgeConfirmation, setShowAgeConfirmation] = useState(false);

  // Load adult content settings on mount
  useEffect(() => {
    setAdultEnabled(isAdultContentEnabled());
    setAgeConfirmedState(isAgeConfirmed());
  }, [isOpen]);

  // Handle adult content toggle
  const handleAdultToggle = () => {
    if (!adultEnabled) {
      // Trying to enable - check age confirmation
      if (ageConfirmed) {
        setAdultContentEnabled(true);
        setAdultEnabled(true);
      } else {
        // Show age confirmation dialog
        setShowAgeConfirmation(true);
      }
    } else {
      // Disabling
      setAdultContentEnabled(false);
      setAdultEnabled(false);
    }
  };

  // Handle age confirmation
  const handleAgeConfirm = () => {
    setAgeConfirmed(true);
    setAgeConfirmedState(true);
    setAdultContentEnabled(true);
    setAdultEnabled(true);
    setShowAgeConfirmation(false);
  };

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

          {/* Content Preferences Section */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-white/80">
              <Shield size={16} className="text-white/50" />
              <span>Content Preferences</span>
            </div>

            {/* Adult Content Toggle */}
            <div className="flex items-center justify-between p-3 rounded-[12px] bg-white/5">
              <div className="flex items-center gap-3">
                <AlertTriangle size={16} className="text-orange-400/70" />
                <div>
                  <span className="text-[13px] text-white/80 block">Enable 18+ Personalities</span>
                  <span className="text-[10px] text-white/40">Unlock adult-only conversation modes</span>
                </div>
              </div>
              <button
                onClick={handleAdultToggle}
                className={`w-12 h-6 rounded-full transition-all ${
                  adultEnabled ? 'bg-orange-500/30 border border-orange-500/50' : toggleOff
                }`}
              >
                <div
                  className={`w-5 h-5 rounded-full shadow-sm transition-transform ${
                    adultEnabled ? 'translate-x-6 bg-orange-400' : 'translate-x-0.5 bg-white'
                  }`}
                />
              </button>
            </div>

            {adultEnabled && (
              <div className="p-3 rounded-[12px] bg-orange-500/10 border border-orange-500/20">
                <p className="text-[11px] text-orange-300/80">
                  Adult personalities are now visible in the personality selector.
                  These modes may contain mature themes, strong language, and explicit content.
                </p>
              </div>
            )}
          </div>

          {/* Age Confirmation Modal */}
          {showAgeConfirmation && (
            <div className="fixed inset-0 bg-black/90 backdrop-blur-md z-[110] flex items-center justify-center p-4">
              <div className="w-full max-w-[400px] bg-[#1a1a1a] border border-orange-500/30 rounded-[20px] p-6 space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-orange-500/20 flex items-center justify-center">
                    <AlertTriangle size={24} className="text-orange-400" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white">Age Verification</h3>
                    <p className="text-[12px] text-white/50">Adult content requires confirmation</p>
                  </div>
                </div>

                <div className="space-y-3">
                  <p className="text-[13px] text-white/70 leading-relaxed">
                    You are about to enable access to adult-only personalities that may contain:
                  </p>
                  <ul className="text-[12px] text-white/60 space-y-1 pl-4">
                    <li>• Mature themes and conversations</li>
                    <li>• Strong language and profanity</li>
                    <li>• Sexual or romantic content</li>
                    <li>• Dark humor and edgy content</li>
                  </ul>
                  <p className="text-[13px] text-white/70">
                    By continuing, you confirm that you are <strong className="text-white">18 years or older</strong> and
                    consent to accessing this content.
                  </p>
                </div>

                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => setShowAgeConfirmation(false)}
                    className="flex-1 h-[44px] rounded-full bg-white/10 text-white/80 text-sm font-medium hover:bg-white/15 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAgeConfirm}
                    className="flex-1 h-[44px] rounded-full bg-orange-500 text-white text-sm font-bold hover:bg-orange-600 transition-colors"
                  >
                    I am 18+ · Enable
                  </button>
                </div>
              </div>
            </div>
          )}

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
