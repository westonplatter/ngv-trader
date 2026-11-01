import { lazy, Suspense, useEffect } from "react";
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
import OrdersTable from "./components/OrdersTable";
import PositionsPage from "./components/positions/PositionsPage";
import StrategyPnlTable from "./components/StrategyPnlTable";
import TradebotChat from "./components/TradebotChat";
import StrategiesPage from "./components/strategies/StrategiesPage";
import TagsPage from "./components/TagsPage";
import TasksPage from "./components/TasksPage";
import TradesPage from "./components/trades/TradesPage";
import WatchListsPage from "./components/WatchListsPage";
import WorkerStatusLights from "./components/WorkerStatusLights";
import { PrivacyProvider } from "./contexts/PrivacyContext";
import { usePrivacy } from "./contexts/usePrivacy";
import { isDemoMode } from "./lib/demoMode";
import { NAV_ITEMS } from "./navItems";

// Plotly makes the pricing page the heaviest route by far; load it on demand
// so the other pages do not pay for it.
const PricingPage = lazy(() => import("./components/pricing/PricingPage"));

const DEMO_MODE = isDemoMode();

function PrivacyToggle() {
  const { privacyMode, togglePrivacy } = usePrivacy();
  return (
    <button
      type="button"
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
            end={item.end}
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
          <Route path="/positions" element={<PositionsPage />} />
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
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/strategies" element={<StrategiesPage />} />
          <Route path="/strategies/table" element={<StrategyPnlTable />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/watchlists" element={<WatchListsPage />} />
          <Route path="/market-data" element={<MarketDataPage />} />
          <Route
            path="/structures"
            element={
              <Suspense fallback={<p className="text-gray-500">Loading...</p>}>
                <PricingPage />
              </Suspense>
            }
          />
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
