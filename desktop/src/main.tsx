import { createRoot } from "react-dom/client";
import { Pill } from "./pill";
import { App } from "./app";
import "./styles.css";

const pill = new URLSearchParams(location.search).get("surface") === "pill";
createRoot(document.getElementById("root")!).render(pill ? <Pill /> : <App />);
