import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import AccountsTable from "./components/AccountsTable";
import OrdersTable from "./components/OrdersTable";
import PositionsTable from "./components/PositionsTable";
import TradebotChat from "./components/TradebotChat";
import WatchListsPage from "./components/WatchListsPage";
import WorkerStatusLights from "./components/WorkerStatusLights";

const NAV_ITEMS = [
  { label: "Accounts", path: "/accounts" },
  { label: "Positions", path: "/positions" },
  { label: "Orders", path: "/orders" },
  { label: "Watch Lists", path: "/watchlists" },
  { label: "Tradebot", path: "/tradebot" },
] as const;

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
        <span className="font-bold text-lg">ngtrader</span>
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
      </nav>
      <div className={contentClass}>
        <Routes>
          <Route path="/" element={<Navigate to="/tradebot" replace />} />
          <Route path="/positions" element={<PositionsTable />} />
          <Route path="/accounts" element={<AccountsTable />} />
          <Route path="/orders" element={<OrdersTable />} />
          <Route path="/watchlists" element={<WatchListsPage />} />
          <Route path="/tradebot" element={<TradebotChat />} />
          <Route path="*" element={<Navigate to="/tradebot" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default App;
