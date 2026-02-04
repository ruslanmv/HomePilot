/**
 * Personality List Component
 *
 * Dropdown list for selecting AI personality modes.
 * Uses a portal with transparent overlay for reliable click handling.
 *
 * Features:
 * - Category-based grouping (General, Kids, Wellness, Adult)
 * - 18+ content gating with visual indicators
 * - Reliable click handling via overlay pattern (no containment race conditions)
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { ChevronDown, Check, Sparkles, Stars, Heart, Flame } from 'lucide-react';
import { PersonalityDef } from './personalities';
import { PERSONALITY_CAPS, PersonalityCategory } from './personalityCaps';
import {
  getPersonalitiesByCategory,
  getCategoryLabel,
  canAccessAdultContent,
} from './personalityGating';

interface PersonalityListProps {
  activePersonality: PersonalityDef;
  onSelect: (personality: PersonalityDef) => void;
}

export default function PersonalityList({
  activePersonality,
  onSelect,
}: PersonalityListProps) {
  const [showList, setShowList] = useState(false);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0, height: 400 });
  const triggerRef = useRef<HTMLButtonElement>(null);

  const btnInactive =
    'bg-[#1F1F1F] border border-transparent hover:bg-[#2A2A2A] hover:border-white/5';
  const panelBg =
    'bg-[#121212]/95 backdrop-blur-xl border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.9)]';

  const Icon = activePersonality.icon;

  // Calculate dropdown position when opened
  useEffect(() => {
    if (showList && triggerRef.current) {
      const dropdownWidth = 280;
      const viewportWidth = window.innerWidth;

      // Find the parent settings panel to position relative to it
      const parentPanel = triggerRef.current.closest('[class*="rounded-[24px]"]');
      if (parentPanel) {
        const panelRect = parentPanel.getBoundingClientRect();
        const rightPosition = panelRect.right + 12;

        if (rightPosition + dropdownWidth > viewportWidth - 12) {
          const leftPosition = panelRect.left - dropdownWidth - 12;
          if (leftPosition >= 12) {
            setDropdownPos({ top: panelRect.top, left: leftPosition, height: panelRect.height });
          } else {
            setDropdownPos({ top: panelRect.top, left: panelRect.left, height: panelRect.height });
          }
        } else {
          setDropdownPos({ top: panelRect.top, left: rightPosition, height: panelRect.height });
        }
      } else {
        const rect = triggerRef.current.getBoundingClientRect();
        setDropdownPos({
          top: rect.bottom + 8,
          left: Math.min(rect.left, viewportWidth - dropdownWidth - 12),
          height: 400,
        });
      }
    }
  }, [showList]);

  // Handle personality selection
  const handleSelect = useCallback((p: PersonalityDef) => {
    onSelect(p);
    setShowList(false);
  }, [onSelect]);

  // Get enabled personalities grouped by category
  const personalitiesByCategory = getPersonalitiesByCategory();
  const adultAllowed = canAccessAdultContent();

  // Category icons
  const categoryIcons: Record<PersonalityCategory, React.ReactNode> = {
    general: <Sparkles size={12} />,
    kids: <Stars size={12} />,
    wellness: <Heart size={12} />,
    adult: <Flame size={12} />,
  };

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-bold text-white">Personality</span>

      {/* Trigger button */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setShowList(!showList)}
        className={`w-full h-[48px] px-4 rounded-[16px] flex items-center justify-between transition-colors ${btnInactive}`}
      >
        <div className="flex items-center gap-3">
          <Icon size={16} className="text-white/70" />
          <span className="text-[13px] font-medium text-white">
            {activePersonality.label}
          </span>
        </div>
        <ChevronDown
          size={14}
          className={`text-white/40 transition-transform ${showList ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Personality dropdown - Portal with overlay for reliable click handling */}
      {showList && typeof document !== 'undefined' &&
        ReactDOM.createPortal(
          <>
            {/* Transparent overlay - catches outside clicks without complex containment logic */}
            <div
              className="fixed inset-0 z-[99]"
              data-hp-voice-portal="true"
              onClick={() => setShowList(false)}
            />

            {/* Dropdown panel */}
            <div
              data-hp-voice-portal="true"
              className={`fixed w-[280px] rounded-[24px] overflow-y-auto hp-scroll flex flex-col p-3 z-[100] hp-fade-in ${panelBg}`}
              style={{
                top: dropdownPos.top,
                left: dropdownPos.left,
                height: dropdownPos.height,
                maxHeight: dropdownPos.height,
              }}
            >
              <div className="px-2 py-2 text-sm font-bold text-white">
                Personality
              </div>

              {/* Render personalities by category */}
              {(['general', 'wellness', 'kids', 'adult'] as PersonalityCategory[]).map((category) => {
                const personalities = personalitiesByCategory[category];
                if (!personalities || personalities.length === 0) return null;

                return (
                  <div key={category} className="mb-2">
                    {/* Category Header */}
                    <div className={`flex items-center gap-2 px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider ${
                      category === 'adult' ? 'text-orange-400/70' : 'text-white/40'
                    }`}>
                      {categoryIcons[category]}
                      <span>{getCategoryLabel(category)}</span>
                    </div>

                    {/* Personalities in category */}
                    <div className="flex flex-col gap-0.5">
                      {personalities.map((p) => {
                        const PIcon = p.icon;
                        const isActive = activePersonality.id === p.id;
                        const caps = PERSONALITY_CAPS[p.id];

                        return (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => handleSelect(p)}
                            className={`
                              flex items-center gap-3 p-2.5 rounded-[12px] text-left transition-all cursor-pointer
                              ${isActive
                                ? category === 'adult'
                                  ? 'bg-orange-500/15 text-white'
                                  : 'bg-white/10 text-white'
                                : 'text-white/50 hover:bg-white/5 hover:text-white'
                              }
                            `}
                          >
                            <PIcon size={16} className={isActive ? 'text-white' : 'opacity-60'} />
                            <div className="flex-1 min-w-0">
                              <span className="text-[12px] font-medium block truncate">
                                {p.label.replace(' 18+', '')}
                              </span>
                              {caps && (
                                <span className="text-[9px] text-white/30 block truncate">
                                  {caps.responseStyle.tone}
                                </span>
                              )}
                            </div>
                            {p.mature && (
                              <span className="text-[8px] text-orange-400/80 px-1.5 py-0.5 bg-orange-500/10 rounded font-medium">
                                18+
                              </span>
                            )}
                            {isActive && <Check size={12} className="text-white shrink-0" />}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              {/* Adult content hint if not enabled */}
              {!adultAllowed && (
                <div className="mt-2 p-2 rounded-[10px] bg-white/5 border border-white/5">
                  <p className="text-[9px] text-white/30 text-center">
                    Enable 18+ content in Settings to unlock adult personalities
                  </p>
                </div>
              )}
            </div>
          </>,
          document.body
        )}
    </div>
  );
}
