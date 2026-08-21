import { useEffect } from "react";
import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import AccountsTable from "./components/AccountsTable";
import FlexQueryTokensTable from "./components/FlexQueryTokensTable";
import MarketDataPage from "./components/MarketDataPage";
import PricingPage from "./components/PricingPage";
import OrdersTable from "./components/OrdersTable";
import PositionsTable from "./components/PositionsTable";
import TradebotChat from "./components/TradebotChat";
import TradeTaggingPage from "./components/TradeTaggingPage";
import TradesTable from "./components/TradesTable";
import WatchListsPage from "./components/WatchListsPage";
import WorkerStatusLights from "./components/WorkerStatusLights";
import { PrivacyProvider } from "./contexts/PrivacyContext";
import { usePrivacy } from "./contexts/usePrivacy";
import { isDemoMode } from "./lib/demoMode";

const DEMO_MODE = isDemoMode();

const NAV_ITEMS = [
  { label: "Accounts", path: "/accounts" },
  { label: "Orders", path: "/orders" },
  { label: "Positions", path: "/positions" },
  { label: "Trades", path: "/trades" },
  { label: "Strategies", path: "/strategies" },
  { label: "Watch Lists", path: "/watchlists" },
  { label: "Market Data", path: "/market-data" },
  { label: "Structures", path: "/structures" },
  { label: "Tradebot", path: "/tradebot" },
] as const;

function PrivacyToggle() {
  const { privacyMode, togglePrivacy } = usePrivacy();
  return (
    <button
      onClick={togglePrivacy}
      className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
        privacyMode
          ? "bg-gray-900 text-white"
          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
      }`}
      title={
        privacyMode
          ? "Privacy mode ON — dollar amounts & quantities hidden; P&L shown as % return"
          : "Privacy mode OFF — dollar amounts & quantities visible"
      }
    >
      <span>{privacyMode ? "🙈" : "👁"}</span>
      <span>Privacy</span>
    </button>
  );
}

function App() {
  const location = useLocation();

  useEffect(() => {
    // Root ("/") redirects to /tradebot; match on the resolved path.
    const path = location.pathname === "/" ? "/tradebot" : location.pathname;
    const item = NAV_ITEMS.find((navItem) => navItem.path === path);
    document.title = item ? `ngv-trader | ${item.label}` : "ngv-trader";
  }, [location.pathname]);

  const isTradebotPage = location.pathname === "/tradebot";
  const isStrategiesPage = location.pathname === "/strategies";
  const horizontalPaddingClass = isTradebotPage ? "px-2 md:px-3" : "px-6";
  const contentClass = isTradebotPage
    ? `${horizontalPaddingClass} py-3 flex-1 min-h-0 overflow-y-auto lg:overflow-hidden`
    : isStrategiesPage
      ? `${horizontalPaddingClass} py-6 flex-1 min-h-0 flex flex-col`
      : `${horizontalPaddingClass} py-6`;

  return (
    <div className="w-full min-h-screen flex flex-col">
      {DEMO_MODE && (
        <div className="flex items-center justify-center gap-2 border-b border-gray-200 bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-600">
          <span>● DEMO MODE</span>
          <span className="font-normal text-gray-500">
            Showing sample data — no live backend connected.
          </span>
        </div>
      )}
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
          <Route
            path="/accounts"
            element={
              <>
                <FlexQueryTokensTable />
                <h2 className="mb-2 text-base font-semibold text-gray-800">
                  Accounts
                </h2>
                <AccountsTable />
              </>
            }
          />
          <Route path="/orders" element={<OrdersTable />} />
          <Route path="/trades" element={<TradesTable />} />
          <Route path="/strategies" element={<TradeTaggingPage />} />
          <Route path="/watchlists" element={<WatchListsPage />} />
          <Route path="/market-data" element={<MarketDataPage />} />
          <Route path="/structures" element={<PricingPage />} />
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
