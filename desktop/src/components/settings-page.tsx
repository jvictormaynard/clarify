import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/utils";
import "../styles/settings-page.css";

function Root({ className, ...props }: ComponentProps<"div">) {
  return <div {...props} className={cn("settings-page", className)} data-slot="settings-page" />;
}

function Intro({ children }: { children: ReactNode }) {
  return <p className="settings-page-intro hint">{children}</p>;
}

function Body({ children }: { children: ReactNode }) {
  return <div className="settings-page-body" data-slot="settings-page-body">{children}</div>;
}

function Actions({ status, children }: { status?: ReactNode; children: ReactNode }) {
  return <footer className="settings-page-actions" data-slot="settings-page-actions">
    {status && <div className="settings-page-status" role="status">{status}</div>}
    <div className="settings-page-buttons">{children}</div>
  </footer>;
}

export const SettingsPage = { Root, Intro, Body, Actions };
