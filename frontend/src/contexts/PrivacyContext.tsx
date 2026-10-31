import { useEffect, useState, type ReactNode } from "react";
import { request } from "../lib/api";
import { PrivacyContext } from "./privacyContextValue";

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyMode] = useState(false);

  useEffect(() => {
    request<{ value?: unknown }>("GET", "/user-preferences/privacy_mode")
      .then((data) => {
        if (data?.value === true) setPrivacyMode(true);
      })
      .catch(() => {});
  }, []);

  const togglePrivacy = () => {
    const next = !privacyMode;
    setPrivacyMode(next);
    request("PUT", "/user-preferences/privacy_mode", { value: next }).catch(
      () => {},
    );
  };

  return (
    <PrivacyContext.Provider value={{ privacyMode, togglePrivacy }}>
      {children}
    </PrivacyContext.Provider>
  );
}