/**
 * Speed Slider Component
 *
 * Speech rate control slider for the Voice UI.
 */

import React from 'react';

interface SpeedSliderProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}

export default function SpeedSlider({
  value,
  onChange,
  min = 0.5,
  max = 2.0,
  step = 0.1,
}: SpeedSliderProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-between items-center">
        <span className="text-sm font-bold text-white">Speed</span>
        <span className="text-xs font-mono text-white/50">{value.toFixed(1)}x</span>
      </div>
      <div className="px-0">
        <input
          type="range"
          className="hp-slider"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
      </div>
    </div>
  );
}
