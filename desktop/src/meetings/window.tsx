import { useEffect, useState } from "react";
import { Button, Confirm } from "../components/ui";
import { setUiLanguage } from "../i18n";
import { MeetingEditor, saveMeetingDrafts } from "../pages/meetings-page";
import { meetingError, meetingText as m } from "../pages/meetings-copy";
import { electron } from "../platform";
import { meetingStopFromDock, useMeetings } from "./bridge";

export function MeetingQuitDialog() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => electron()?.onWindow(event => {
    if (event === "meetings-before-quit") {
      setError(false);
      setOpen(true);
    }
  }), []);

  const dismiss = () => {
    setOpen(false);
    void electron()?.window("meetingQuitCancelled").catch(() => {});
  };

  return <Confirm open={open} title={m("quitTitle")} description={m("quitDescription")}
    onOpenChange={next => { if (!busy && !next) dismiss(); }} error={error && m("saveError")}>
    <Button disabled={busy} onClick={dismiss}>{m("cancel")}</Button>
    <Button disabled={busy} onClick={() => void electron()?.window("meetingQuitAccepted", true).catch(() => setError(true))}>
      {m("quitDiscard")}
    </Button>
    <Button variant="primary" loading={busy} onClick={async () => {
      setBusy(true);
      setError(false);
      try {
        if (!await saveMeetingDrafts()) throw new Error();
        await electron()?.window("meetingQuitAccepted", false);
      } catch {
        setError(true);
      } finally {
        setBusy(false);
      }
    }}>{m("quitSave")}</Button>
  </Confirm>;
}

export function MeetingWindow() {
  const state = useMeetings();
  const [target, setTarget] = useState<string>();
  const [locale, setLocale] = useState<string>();
  const [error, setError] = useState("");
  useEffect(() => {
    const desktop = electron();
    const unsubscribe = desktop?.onWindow((event, value) => {
      if (event === "meeting-editor" && value) setTarget(value);
      if (event === "meeting-locale") {
        setUiLanguage(value);
        setLocale(value);
      }
      if (event === "meeting-stop" && value) {
        void meetingStopFromDock(value).catch(failure => {
          setError(failure instanceof Error ? failure.message : "capture_unavailable");
        });
      }
    });
    void desktop?.ready();
    return unsubscribe;
  }, []);

  return <main className="meetings-page meeting-window scroll-area" lang={locale}>
    {error && <p className="error" role="alert">{meetingError(error)}</p>}
    {target && state && <MeetingEditor key={target} id={target} state={state}
      onDeleted={id => {
        setTarget(current => current === id ? undefined : current);
        void electron()?.window("closeMeeting", id).catch(() => {});
      }}
      openModels={() => void electron()?.window("meetingModels").catch(() => setError("summary_setup"))} />}
    <MeetingQuitDialog />
  </main>;
}
