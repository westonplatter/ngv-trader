import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import AccountsTable from "./components/AccountsTable";
import MarketDataPage from "./components/MarketDataPage";
import PricingPage from "./components/PricingPage";
import OrdersTable from "./components/OrdersTable";
import PositionsTable from "./components/PositionsTable";
import TradebotChat from "./components/TradebotChat";
import TradeTaggingPage from "./components/TradeTaggingPage";
import TradesTable from "./components/TradesTable";
import WatchListsPage from "./components/WatchListsPage";
import WorkerStatusLights from "./components/WorkerStatusLights";
import { PrivacyProvider, usePrivacy } from "./contexts/PrivacyContext";

const NAV_ITEMS = [
  { label: "Accounts", path: "/accounts" },
  { label: "Positions", path: "/positions" },
  { label: "Orders", path: "/orders" },
  { label: "Trades", path: "/trades" },
  { label: "Tagging", path: "/tagging" },
  { label: "Watch Lists", path: "/watchlists" },
  { label: "Market Data", path: "/market-data" },
  { label: "Pricing", path: "/pricing" },
  { label: "Tradebot", path: "/tradebot" },
] as const;

function PrivacyToggle() {
  const { privacyMode, togglePrivacy } = usePrivacy();
  return (
    <button
      onClick={togglePrivacy}
      className={`ml-auto flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
        privacyMode
          ? "bg-gray-900 text-white"
          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
      }`}
      title={
        privacyMode
          ? "Privacy mode ON — quantities hidden"
          : "Privacy mode OFF — quantities visible"
      }
    >
      <span>{privacyMode ? "🙈" : "👁"}</span>
      <span>Privacy</span>
    </button>
  );
}

function App() {
  const location = useLocation();
  const isTradebotPage = location.pathname === "/tradebot";
  const horizontalPaddingClass = isTradebotPage ? "px-2 md:px-3" : "px-6";
  const contentClass = isTradebotPage
    ? `${horizontalPaddingClass} py-3 flex-1 min-h-0 overflow-y-auto lg:overflow-hidden`
    : `${horizontalPaddingClass} py-6`;

  return (
    <div className="w-full min-h-screen flex flex-col">
      <nav
        className={`flex items-center gap-6 ${horizontalPaddingClass} py-3 border-b border-gray-200 bg-white`}
      >
        <span className="font-bold text-lg tracking-tight">ngv-trader</span>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `text-sm ${isActive ? "text-black font-semibold" : "text-gray-500 hover:text-gray-800"}`
            }
          >
            {item.label}
          </NavLink>
        ))}
        <WorkerStatusLights />
        <PrivacyToggle />
      </nav>
      <div className={contentClass}>
        <Routes>
          <Route path="/" element={<Navigate to="/tradebot" replace />} />
          <Route path="/positions" element={<PositionsTable />} />
          <Route path="/accounts" element={<AccountsTable />} />
          <Route path="/orders" element={<OrdersTable />} />
          <Route path="/trades" element={<TradesTable />} />
          <Route path="/tagging" element={<TradeTaggingPage />} />
          <Route path="/watchlists" element={<WatchListsPage />} />
          <Route path="/market-data" element={<MarketDataPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/tradebot" element={<TradebotChat />} />
          <Route path="*" element={<Navigate to="/tradebot" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default function AppWithProviders() {
  return (
    <PrivacyProvider>
      <App />
    </PrivacyProvider>
  );
}
