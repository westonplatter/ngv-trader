// The legs table and its Add Leg button.

import type { LegRow as LegRowData } from "../../lib/pricing/legs";
import type { ChainEntry } from "../../types/pricing";
import LegRow from "./LegRow";
import type { InstrumentData } from "./useInstrumentData";

const TH = "px-2 py-1.5 text-left";

export default function LegsTable({
  legs,
  instrumentData,
  onUpdate,
  onRemove,
  onAdd,
  onFetchPrice,
}: {
  legs: LegRowData[];
  instrumentData: InstrumentData;
  onUpdate: (id: string, updates: Partial<LegRowData>) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
  onFetchPrice: (legId: string, entry: ChainEntry) => void;
}) {
  return (
    // Column order: # | Type | Expiry | Strike | Qty | IV | IV End | Und | Bid
    // | Ask | Mid | Volume | OI | Con Id | x
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Legs
      </h2>
      <table className="text-sm border border-gray-200 rounded w-full">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-2 py-1.5 w-8"></th>
            <th className={`${TH} w-10`}>#</th>
            <th className={`${TH} w-20`}>Type</th>
            <th className={`${TH} w-52`}>Expiry</th>
            <th className={`${TH} w-36`}>Strike</th>
            <th className={`${TH} w-16`}>Qty</th>
            <th className={`${TH} w-20`}>IV</th>
            <th className={`${TH} w-20`}>IV End</th>
            <th className={`${TH} w-20`}>Und</th>
            <th className={`${TH} w-20`}>Bid</th>
            <th className={`${TH} w-20`}>Ask</th>
            <th className={`${TH} w-20`}>Mid</th>
            <th className={`${TH} w-24`}>Volume</th>
            <th className={`${TH} w-24`}>OI</th>
            <th className={`${TH} w-24`}>Con Id</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, idx) => (
            <LegRow
              key={leg.id}
              leg={leg}
              index={idx}
              availableOptions={instrumentData.availableOptions}
              futuresContracts={instrumentData.futuresContracts}
              optionsLoading={instrumentData.optionsLoading}
              futuresLoading={instrumentData.futuresLoading}
              onUpdate={onUpdate}
              onRemove={onRemove}
              onFetchPrice={onFetchPrice}
            />
          ))}
        </tbody>
      </table>
      <button
        type="button"
        onClick={onAdd}
        className="mt-2 text-sm text-blue-600 hover:text-blue-800 font-medium"
      >
        + Add Leg
      </button>
    </div>
  );
}
