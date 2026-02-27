import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const API_BASE_URL = "http://localhost:8000/api/v1";

interface PrivacyContextValue {
  privacyMode: boolean;
  togglePrivacy: () => void;
}

const PrivacyContext = createContext<PrivacyContextValue>({
  privacyMode: false,
  togglePrivacy: () => {},
});

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyMode] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE_URL}/user-preferences/privacy_mode`)
      .then((res) => {
        if (!res.ok) return;
        return res.json();
      })
      .then((data) => {
        if (data?.value === true) setPrivacyMode(true);
      })
      .catch(() => {});
  }, []);

  const togglePrivacy = () => {
    const next = !privacyMode;
    setPrivacyMode(next);
    fetch(`${API_BASE_URL}/user-preferences/privacy_mode`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: next }),
    }).catch(() => {});
  };

  return (
    <PrivacyContext.Provider value={{ privacyMode, togglePrivacy }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function usePrivacy() {
  return useContext(PrivacyContext);
}
