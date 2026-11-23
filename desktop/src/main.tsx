import { createRoot } from "react-dom/client";
import { Pill } from "./pill";
import { App } from "./app";
import { MeetingWindow } from "./meetings/window";
import "./styles.css";

const surface = new URLSearchParams(location.search).get("surface");
createRoot(document.getElementById("root")!).render(surface === "pill" ? <Pill /> : surface === "meeting" ? <MeetingWindow /> : <App />);
