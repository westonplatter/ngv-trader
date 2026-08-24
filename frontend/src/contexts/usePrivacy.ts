import { useContext } from "react";
import { PrivacyContext } from "./privacyContextValue";

export function usePrivacy() {
  return useContext(PrivacyContext);
}
