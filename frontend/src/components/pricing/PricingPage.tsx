// /structures: build an options structure leg by leg against the live chain,
// save it, and chart its expected P&L over spot and time. This file wires the
// hooks to the panes: instrument data in useInstrumentData, the sidebar in
// useSavedStructures, the legs and quote fetches in useLegs, the pricing call
// in useExpectedPnl.

import { useCallback, useMemo, useState } from "react";
import { errorMessage } from "../../lib/api";
import {
  legsToSaved,
  savedLegsToRows,
  spotRange,
} from "../../lib/pricing/legs";
import { buildPlotTraces } from "../../lib/pricing/plot";
import type { FuturesContract } from "../../types/pricing";
import LegsTable from "./LegsTable";
import PnlChart from "./PnlChart";
import {
  InstrumentSpotControls,
  PnlControls,
  type SpotInputs,
} from "./PricingControls";
import SavedStructuresSidebar from "./SavedStructuresSidebar";
import { useExpectedPnl } from "./useExpectedPnl";
import { useInstrumentData } from "./useInstrumentData";
import { useLegs } from "./useLegs";
import { useSavedStructures, type StructureBody } from "./useSavedStructures";

const EMPTY_SPOT: SpotInputs = { spotPrice: "", spotMin: "", spotMax: "" };

function seededSpot(price: number): SpotInputs {
  const range = spotRange(price);
  return { spotPrice: range.spot, spotMin: range.min, spotMax: range.max };
}

export default function PricingPage() {
  const [instrument, setInstrument] = useState("CL");
  const [spot, setSpot] = useState<SpotInputs>(EMPTY_SPOT);
  const [dayStep, setDayStep] = useState("1");
  const [strikeStep, setStrikeStep] = useState("1");
  // One error line for the page; the latest failure wins, a new calculation
  // clears it.
  const [error, setError] = useState<string | null>(null);

  // The front contract's price seeds the spot window whenever a term
  // structure arrives (first load and each instrument change).
  const onFuturesLoaded = useCallback(
    (contracts: FuturesContract[]) => {
      if (contracts.length > 0) {
        setSpot(seededSpot(contracts[0].last ?? contracts[0].close ?? 0));
      }
    },
    [],
  );
  const instrumentCallbacks = useMemo(
    () => ({ onFuturesLoaded, onError: setError }),
    [onFuturesLoaded],
  );
  const instrumentData = useInstrumentData(instrument, instrumentCallbacks);
  const saved = useSavedStructures(setError);
  const legState = useLegs(setError);
  const pnl = useExpectedPnl();

  const structureBody = (): StructureBody => {
    const price = parseFloat(spot.spotPrice);
    return {
      instrument,
      legs: legsToSaved(legState.legs),
      spot_price: isNaN(price) ? null : price,
    };
  };

  const loadStructure = (id: number) => {
    const structure = saved.select(id);
    if (!structure) return;
    setInstrument(structure.instrument);
    legState.setLegs(savedLegsToRows(structure.legs));
    if (structure.spot_price != null) setSpot(seededSpot(structure.spot_price));
  };

  const saveAs = () => {
    const name = window.prompt("Enter a name for this structure:");
    if (!name) return;
    void saved.saveAs(name, structureBody());
  };

  const deleteStructure = () => {
    if (!window.confirm("Delete this saved structure?")) return;
    void saved.remove();
  };

  const calculate = () => {
    setError(null);
    pnl
      .calculate({ ...spot, dayStep, strikeStep, legs: legState.legs })
      .catch((err: unknown) => setError(errorMessage(err)));
  };

  const plotTraces = buildPlotTraces(pnl.data);

  return (
    <div className="flex gap-6">
      <SavedStructuresSidebar
        saved={saved}
        onLoad={loadStructure}
        onSave={() => void saved.save(structureBody())}
        onSaveAs={saveAs}
        onDelete={deleteStructure}
      />

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <h1 className="text-xl font-bold mb-4">Pricing — Expected PnL</h1>

        <InstrumentSpotControls
          instrument={instrument}
          onInstrument={setInstrument}
          spot={spot}
          onSpot={setSpot}
        />

        <LegsTable
          legs={legState.legs}
          instrumentData={instrumentData}
          onUpdate={legState.updateLeg}
          onRemove={legState.removeLeg}
          onAdd={legState.addLeg}
          onFetchPrice={legState.fetchPriceForContract}
        />

        <PnlControls
          dayStep={dayStep}
          onDayStep={setDayStep}
          strikeStep={strikeStep}
          onStrikeStep={setStrikeStep}
          loading={pnl.loading}
          onCalculate={calculate}
        />

        {error && (
          <div className="text-red-600 text-sm mb-4 p-3 bg-red-50 rounded">
            {error}
          </div>
        )}

        {plotTraces && <PnlChart traces={plotTraces.data} />}
      </div>
    </div>
  );
}
