/**
 * Personality List Component
 *
 * Dropdown list for selecting AI personality modes.
 * Uses fixed positioning to float the dropdown to the RIGHT of the settings panel,
 * similar to Grok's two-layer design.
 */

import React, { useState, useRef, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { ChevronDown, Check } from 'lucide-react';
import { PERSONALITIES, PersonalityDef } from './personalities';

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
  const dropdownRef = useRef<HTMLDivElement>(null);

  const btnInactive =
    'bg-[#1F1F1F] border border-transparent hover:bg-[#2A2A2A] hover:border-white/5';
  const panelBg =
    'bg-[#121212]/95 backdrop-blur-xl border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.9)]';

  const Icon = activePersonality.icon;

  // Calculate dropdown position when opened - align to parent panel's top and match height
  useEffect(() => {
    if (showList && triggerRef.current) {
      // Find the parent settings panel to position relative to it
      const parentPanel = triggerRef.current.closest('.hp-panel, [class*="rounded-[24px]"]');
      if (parentPanel) {
        const panelRect = parentPanel.getBoundingClientRect();
        setDropdownPos({
          top: panelRect.top,           // Align to panel top (not trigger)
          left: panelRect.right + 12,   // 12px gap from settings panel
          height: panelRect.height,     // Match panel height
        });
      } else {
        // Fallback: position to the right of the trigger
        const rect = triggerRef.current.getBoundingClientRect();
        setDropdownPos({
          top: rect.top,
          left: rect.right + 12,
          height: 400,
        });
      }
    }
  }, [showList]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showList) return;

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current &&
        !triggerRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setShowList(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showList]);

  // Dropdown portal content - matches voice settings panel height
  const dropdownContent = showList && (
    <div
      ref={dropdownRef}
      className={`fixed w-[280px] rounded-[24px] overflow-y-auto hp-scroll flex flex-col p-3 z-[100] hp-fade-in ${panelBg}`}
      style={{
        top: dropdownPos.top,
        left: dropdownPos.left,
        height: dropdownPos.height,
        maxHeight: dropdownPos.height,
      }}
    >
      <div className="px-2 py-3 text-sm font-bold text-white">
        Personality
      </div>
      <div className="flex flex-col gap-1">
        {PERSONALITIES.map((p) => {
          const PIcon = p.icon;
          const isActive = activePersonality.id === p.id;
          return (
            <button
              key={p.id}
              onClick={() => {
                onSelect(p);
                setShowList(false);
              }}
              className={`
                flex items-center gap-3 p-3 rounded-[16px] text-left transition-all
                ${isActive ? 'bg-white/10 text-white' : 'text-white/50 hover:bg-white/5 hover:text-white'}
              `}
            >
              <PIcon size={18} className={isActive ? 'text-white' : 'opacity-60'} />
              <span className="text-[13px] font-medium flex-1">
                {p.label}
                {p.mature && (
                  <span className="text-[10px] text-white/30 ml-2 px-1.5 py-0.5 bg-white/5 rounded">18+</span>
                )}
              </span>
              {isActive && <Check size={14} className="text-white" />}
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-bold text-white">Personality</span>

      {/* Trigger button */}
      <button
        ref={triggerRef}
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

      {/* Personality list - Portal to body for fixed positioning */}
      {typeof document !== 'undefined' &&
        ReactDOM.createPortal(dropdownContent, document.body)}
    </div>
  );
}
