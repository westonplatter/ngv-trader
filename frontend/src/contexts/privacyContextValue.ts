import { createContext } from "react";

export interface PrivacyContextValue {
  privacyMode: boolean;
  togglePrivacy: () => void;
}

export const PrivacyContext = createContext<PrivacyContextValue>({
  privacyMode: false,
  togglePrivacy: () => {},
});
