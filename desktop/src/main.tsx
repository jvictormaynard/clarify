import { createRoot } from "react-dom/client";
import { Pill } from "./pill";
import { App } from "./app";
import { MeetingWindow } from "./meetings/window";
import { PermissionGuide } from "./components/dictation-permissions";
import { setUiLanguage } from "./i18n";
import { electron } from "./platform";
import "./styles.css";

const params = new URLSearchParams(location.search);
const surface = params.get("surface");
if (surface === "permission-guide") {
  document.documentElement.classList.add("permission-guide-surface");
  if (electron()?.dragInstalledApp) document.documentElement.classList.add("permission-guide-native");
  setUiLanguage(params.get("locale") ?? "en");
}
createRoot(document.getElementById("root")!).render(
  surface === "pill" ? <Pill /> : surface === "meeting" ? <MeetingWindow />
    : surface === "permission-guide" ? <PermissionGuide /> : <App />,
);
