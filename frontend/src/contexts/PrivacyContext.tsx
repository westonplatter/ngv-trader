import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { PrivacyContext } from "./privacyContextValue";

const PREF_PATH = "/user-preferences/privacy_mode";

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyMode] = useState(false);

  useEffect(() => {
    api
      .get<{ value?: unknown } | null>(PREF_PATH)
      .then((data) => {
        if (data?.value === true) setPrivacyMode(true);
      })
      .catch(() => {});
  }, []);

  const togglePrivacy = () => {
    const next = !privacyMode;
    setPrivacyMode(next);
    api.put(PREF_PATH, { value: next }).catch(() => {});
  };

  return (
    <PrivacyContext.Provider value={{ privacyMode, togglePrivacy }}>
      {children}
    </PrivacyContext.Provider>
  );
}
