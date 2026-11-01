// The input rows above and below the legs table: instrument and spot window,
// then the step sizes and the Calculate button.

import { spotRange } from "../../lib/pricing/legs";

const INSTRUMENTS = ["CL", "NQ", "ES"] as const;

export interface SpotInputs {
  spotPrice: string;
  spotMin: string;
  spotMax: string;
}

const FIELD = "border border-gray-300 rounded px-2 py-1.5 w-28";

export function InstrumentSpotControls({
  instrument,
  onInstrument,
  spot,
  onSpot,
}: {
  instrument: string;
  onInstrument: (instrument: string) => void;
  spot: SpotInputs;
  onSpot: (next: SpotInputs) => void;
}) {
  return (
    <div className="flex items-end gap-4 mb-4">
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Instrument</span>
        <select
          value={instrument}
          onChange={(e) => onInstrument(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5"
        >
          {INSTRUMENTS.map((sym) => (
            <option key={sym} value={sym}>
              /{sym}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Spot Price</span>
        <input
          type="number"
          step="any"
          value={spot.spotPrice}
          onChange={(e) => {
            const val = e.target.value;
            const n = parseFloat(val);
            // Typing a spot re-seeds the ±20% window; a blank leaves it alone.
            if (!isNaN(n)) {
              const range = spotRange(n);
              onSpot({ spotPrice: val, spotMin: range.min, spotMax: range.max });
            } else {
              onSpot({ ...spot, spotPrice: val });
            }
          }}
          className={FIELD}
        />
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Spot Min</span>
        <input
          type="number"
          step="any"
          value={spot.spotMin}
          onChange={(e) => onSpot({ ...spot, spotMin: e.target.value })}
          className={FIELD}
        />
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Spot Max</span>
        <input
          type="number"
          step="any"
          value={spot.spotMax}
          onChange={(e) => onSpot({ ...spot, spotMax: e.target.value })}
          className={FIELD}
        />
      </label>
    </div>
  );
}

export function PnlControls({
  dayStep,
  onDayStep,
  strikeStep,
  onStrikeStep,
  loading,
  onCalculate,
}: {
  dayStep: string;
  onDayStep: (value: string) => void;
  strikeStep: string;
  onStrikeStep: (value: string) => void;
  loading: boolean;
  onCalculate: () => void;
}) {
  return (
    <div className="flex items-end gap-4 mb-6">
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Day Step</span>
        <input
          type="number"
          step="1"
          min="1"
          value={dayStep}
          onChange={(e) => onDayStep(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 w-20"
        />
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-600 mb-1">Strike Step</span>
        <input
          type="number"
          step="any"
          min="0.01"
          value={strikeStep}
          onChange={(e) => onStrikeStep(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 w-20"
        />
      </label>
      <button
        type="button"
        onClick={onCalculate}
        disabled={loading}
        className="bg-black text-white text-sm font-medium rounded px-4 py-1.5 hover:bg-gray-800 disabled:opacity-50"
      >
        {loading ? "Computing..." : "Calculate PnL"}
      </button>
    </div>
  );
}
