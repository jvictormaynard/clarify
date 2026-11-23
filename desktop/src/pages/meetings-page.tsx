import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  ArrowLeft, AudioLines, CalendarDays, Check, ChevronRight, Circle, Copy, Download, MoreHorizontal,
  Pause, Pencil, Play, Plus, Search, Square, Trash2, X,
} from "lucide-react";
import { Button, Confirm, Input, TextArea } from "../components/ui";
import {
  Dialog, DialogDescription, DialogFooter, DialogHeader, DialogPopup, DialogTitle,
} from "../components/primitives/dialog";
import { Menu, MenuItem, MenuPopup, MenuSeparator, MenuTrigger } from "../components/primitives/menu";
import { uiLanguage } from "../i18n";
import { electron, isMacDesktop } from "../platform";
import {
  meetingCancelInstall, meetingCopy, meetingCreate, meetingDelete, meetingGet, meetingInstall, meetingInstallOverlap, meetingInstallSpeakers, meetingNameSpeaker,
  meetingList, meetingPause, meetingResume, meetingSave, meetingStart, meetingStop, meetingSummarize,
  LOCAL_MICROPHONE, SYSTEM_AUDIO, useMeetings, type Meeting, type MeetingEntry, type MeetingState, type TranscriptTurn,
} from "../meetings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";
import { meetingError, meetingText as m } from "./meetings-copy";
import "../styles/meetings.css";

type EditPatch = Partial<Pick<Meeting, "title" | "notes" | "summary">>;
type SaveListener = (saved?: Meeting, fields?: (keyof EditPatch)[]) => void;
type SaveQueue = {
  pending: EditPatch;
  failed: boolean;
  timer?: number;
  writing?: Promise<boolean>;
  listeners: Set<SaveListener>;
};

const saves = new Map<string, SaveQueue>();
const indexListeners = new Set<(meeting: Meeting) => void>();
const pageSize = 50;
const encoder = new TextEncoder();
const fieldLimits = {title: 800, notes: 64 * 1024, summary: 64 * 1024};

function fitsField(field: keyof EditPatch, value: string) {
  return !value.includes("\0") && encoder.encode(value).byteLength <= fieldLimits[field];
}

function publishDrafts() {
  const pending = Array.from(saves.values()).some(queue => Object.keys(queue.pending).length);
  void electron()?.window("meetingDraft", pending).catch(() => {});
}

export async function saveMeetingDrafts() {
  const results = await Promise.all(Array.from(saves, ([id, queue]) => flushEdits(id, queue)));
  return results.every(Boolean);
}

function queueFor(id: string): SaveQueue {
  const existing = saves.get(id);
  if (existing) return existing;
  const queue: SaveQueue = { pending: {}, failed: false, listeners: new Set() };
  saves.set(id, queue);
  return queue;
}

function releaseQueue(id: string, queue: SaveQueue) {
  if (!queue.listeners.size && !queue.writing && !Object.keys(queue.pending).length) saves.delete(id);
}

function flushEdits(id: string, queue: SaveQueue): Promise<boolean> {
  window.clearTimeout(queue.timer);
  queue.timer = undefined;
  if (queue.writing) return queue.writing;
  if (!Object.keys(queue.pending).length) return Promise.resolve(true);

  // One writer per meeting. Keep edits made during an accepted write in the next patch.
  const write = async () => {
    while (Object.keys(queue.pending).length) {
      const fields = (Object.keys(queue.pending) as (keyof EditPatch)[])
        .filter(field => fitsField(field, queue.pending[field]!));
      if (!fields.length) {
        queue.failed = true;
        return false;
      }
      const sent = Object.fromEntries(fields.map(field => [field, queue.pending[field]]));
      let saved: Meeting;
      try {
        saved = await meetingSave(id, sent);
      } catch {
        queue.failed = true;
        return false;
      }
      const remaining = { ...queue.pending };
      for (const field of fields) {
        if (remaining[field] === sent[field]) delete remaining[field];
      }
      queue.pending = remaining;
      queue.listeners.forEach(listener => listener(saved, fields));
      indexListeners.forEach(listener => listener(saved));
    }
    return true;
  };
  queue.failed = false;
  queue.writing = Promise.resolve().then(write).finally(() => {
    queue.writing = undefined;
    publishDrafts();
    queue.listeners.forEach(listener => listener());
    releaseQueue(id, queue);
  });
  queue.listeners.forEach(listener => listener());
  return queue.writing;
}

function queueEdit(id: string, field: keyof EditPatch, value: string) {
  const queue = queueFor(id);
  queue.pending = { ...queue.pending, [field]: value };
  publishDrafts();
  queue.failed = false;
  window.clearTimeout(queue.timer);
  if (!queue.writing) queue.timer = window.setTimeout(() => void flushEdits(id, queue), 400);
  queue.listeners.forEach(listener => listener());
}

function dateLabel(value: number, detailed = false) {
  return new Intl.DateTimeFormat(uiLanguage, {
    dateStyle: detailed ? "long" : "medium",
    timeStyle: detailed ? "short" : undefined,
  }).format(value);
}

function elapsed(value: number) {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  return [hours ? String(hours) : "", String(minutes).padStart(2, "0"), String(seconds % 60).padStart(2, "0")]
    .filter(Boolean).join(":");
}

function isCapturing(status: MeetingEntry["status"]) {
  return status === "starting" || status === "recording" || status === "paused" || status === "finalizing";
}

function range(segment: Meeting["segments"][number]) {
  const start = elapsed(segment.start);
  const end = segment.end === undefined ? start : elapsed(segment.end);
  return start === end ? start : `${start}–${end}`;
}

function exportText(meeting: Meeting) {
  const title = (meeting.title.trim() || m("untitled")).replace(/\s+/g, " ");
  return [
    `# ${title}`,
    meeting.notes.trim() && `## ${m("notes")}\n\n${meeting.notes}`,
    meeting.summary.trim() && `## ${m("summary")}\n\n${meeting.summary}`,
    meeting.segments.length && `## ${m("transcript")}\n\n${meeting.segments.map(segment => {
      const label = segment.speaker ? `${speakerLabel(segment.speaker, meeting.speakers)}: ` : "";
      return `${range(segment)}  ${label}${segment.text}`;
    }).join("\n\n")}`,
  ].filter(Boolean).join("\n\n") + "\n";
}

function speakerLabel(speaker: number, names?: Meeting["speakers"]) {
  if (speaker === LOCAL_MICROPHONE) return m("localMicrophone");
  if (speaker === SYSTEM_AUDIO) return m("systemAudio");
  return names?.[speaker] || `${m("speaker")} ${speaker}`;
}

function findTranscript(meeting: Meeting, search: string) {
  const normalize = (text: string) => text.trim().replace(/\s+/g, " ").toLocaleLowerCase(uiLanguage);
  const query = normalize(search);
  if (!query) return meeting.segments;
  const bySource = new Map<TranscriptTurn["source"], TranscriptTurn[]>();
  for (const segment of meeting.segments) {
    const source = bySource.get(segment.source) ?? [];
    source.push(segment);
    bySource.set(segment.source, source);
  }
  const matching = new Set<TranscriptTurn>();
  for (const source of bySource.values()) {
    const parts = source.map(segment => normalize(segment.text));
    const text = parts.join(" ");
    let match = text.indexOf(query);
    let start = 0;
    for (const [index, segment] of source.entries()) {
      const end = start + parts[index].length;
      while (match !== -1 && match + query.length <= start) {
        match = text.indexOf(query, match + 1);
      }
      if (match !== -1 && match < end) matching.add(segment);
      start = end + 1;
    }
  }
  return meeting.segments.filter(segment => {
    const label = segment.speaker ? speakerLabel(segment.speaker, meeting.speakers) : "";
    return matching.has(segment) || normalize(label).includes(query);
  });
}

function downloadMeeting(meeting: Meeting, value: string) {
  const name = (meeting.title.trim() || m("untitled")).replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .slice(0, 100).replace(/[. ]+$/g, "");
  const url = URL.createObjectURL(new Blob([value], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name || m("meetings")}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function MeetingStatus({ status }: { status: MeetingEntry["status"] }) {
  return <span className="meeting-status" data-status={status}><span aria-hidden="true" />{m(status)}</span>;
}

type IndexPage = { query: string; rows: MeetingEntry[]; offset: number; more: boolean };
const emptyIndex: IndexPage = { query: "", rows: [], offset: 0, more: false };

type MeetingOpenRequest = { target?: string };

export function MeetingsPage({ controller, meetingOpen, acknowledgeMeetingOpen }: SettingsPageProps & {
  meetingOpen: MeetingOpenRequest | null;
  acknowledgeMeetingOpen: (request: MeetingOpenRequest) => void;
}) {
  const separateEditor = electron()?.separateMeetingWindow === true;
  const state = useMeetings();
  const ready = state !== null;
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState<IndexPage>(emptyIndex);
  const [listBusy, setListBusy] = useState(true);
  const [listError, setListError] = useState(false);
  const [createError, setCreateError] = useState(false);
  const [openError, setOpenError] = useState(false);
  const [selected, setSelected] = useState<{ id: string; initial?: Meeting } | null>(null);
  const [creating, setCreating] = useState(false);
  const createPending = useRef(false);
  const choice = useRef(0);
  const request = useRef(0);
  const loadingOffset = useRef<number | null>(null);
  const mounted = useRef(false);
  const queryRef = useRef(query);
  const selectedId = useRef(selected?.id);
  selectedId.current = selected?.id;
  const createButton = useRef<HTMLButtonElement>(null);
  const searchField = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<string | null>(null);
  const listRows = useRef(new Map<string, HTMLButtonElement>());
  queryRef.current = query;

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [search]);

  const load = useCallback(async (filter: string, offset = 0) => {
    if (!mounted.current) return;
    const ticket = ++request.current;
    loadingOffset.current = offset;
    const current = () => ticket === request.current && filter === queryRef.current;
    setListBusy(true);
    setListError(false);
    try {
      const rows = await meetingList(filter, offset);
      if (!current()) return;
      setIndex(previous => ({
        query: filter,
        rows: offset ? [...previous.rows, ...rows.filter(row => !previous.rows.some(old => old.id === row.id))] : rows,
        offset: offset + rows.length,
        more: rows.length === pageSize,
      }));
    } catch {
      if (current()) setListError(true);
    } finally {
      if (current()) {
        loadingOffset.current = null;
        setListBusy(false);
      }
    }
  }, []);

  const activeId = state?.active?.id;
  const meetingTarget = activeId ?? state?.interruptedId;
  const activeStatus = state?.active?.status;
  const generating = state?.generating;
  const summaryRevision = state?.summaryRevision;
  const libraryRevision = separateEditor ? state?.libraryRevision : undefined;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const firstSnapshot = useRef(true);
  useEffect(() => {
    if (!ready || !firstSnapshot.current) return;
    firstSnapshot.current = false;
    if (!separateEditor && meetingTarget && !selectedId.current) setSelected({ id: meetingTarget });
  }, [meetingTarget, ready, separateEditor]);
  useEffect(() => {
    if (!ready || !meetingOpen) return;
    const target = meetingOpen.target ?? meetingTarget;
    if (!separateEditor && target && selectedId.current !== target) {
      choice.current++;
      selectedId.current = target;
      setSelected({ id: target });
    }
    acknowledgeMeetingOpen(meetingOpen);
  }, [acknowledgeMeetingOpen, meetingOpen, meetingTarget, ready, separateEditor]);
  useEffect(() => {
    if (ready) void load(query);
    return () => { request.current++; };
  }, [load, query, ready, activeId, activeStatus, generating, summaryRevision, libraryRevision]);

  useLayoutEffect(() => {
    if (!selected && returnFocus.current !== null) {
      (listRows.current.get(returnFocus.current) ?? createButton.current)?.focus();
      returnFocus.current = null;
    }
  }, [selected]);

  const select = (id: string) => {
    choice.current++;
    if (separateEditor) {
      setOpenError(false);
      void electron()?.window("openMeeting", id).catch(() => setOpenError(true));
      return;
    }
    selectedId.current = id;
    setSelected(previous => previous?.id === id ? previous : { id });
  };

  const back = () => {
    choice.current++;
    returnFocus.current = selectedId.current ?? "";
    selectedId.current = undefined;
    setSelected(null);
  };

  const create = async () => {
    if (createPending.current) return;
    createPending.current = true;
    setCreating(true);
    setCreateError(false);
    const ticket = ++choice.current;
    try {
      const meeting = await meetingCreate();
      if (ticket === choice.current) {
        setSearch("");
        setQuery("");
        queryRef.current = "";
        if (separateEditor) select(meeting.id);
        else {
          selectedId.current = meeting.id;
          setSelected({ id: meeting.id, initial: meeting });
        }
      }
      void load(queryRef.current);
    } catch {
      setCreateError(true);
    } finally {
      createPending.current = false;
      setCreating(false);
    }
  };

  useEffect(() => {
    const saved = (meeting: Meeting) => {
      setIndex(previous => ({
        ...previous,
        rows: previous.rows.map(row => row.id === meeting.id
          ? { ...row, title: meeting.title, updatedAt: meeting.updatedAt }
          : row),
      }));
      if (queryRef.current || loadingOffset.current !== null) {
        void load(queryRef.current, queryRef.current ? 0 : loadingOffset.current ?? 0);
      }
    };
    indexListeners.add(saved);
    return () => { indexListeners.delete(saved); };
  }, [load]);

  const visible = index.query === query ? index.rows : [];
  const active = state?.active;
  const activeLink = active && active.id !== selected?.id ? (
    <Button className="meeting-active-link" onClick={() => select(active.id)}>
      <AudioLines aria-hidden="true" />
      <span>{m("active")} <small>{m(active.status)}</small></span>
      <ChevronRight aria-hidden="true" />
    </Button>
  ) : null;

  return <div className="meetings-page" data-hub={separateEditor}>
    <div className="meetings-layout" data-selected={selected !== null}>
      <section className="meetings-index" aria-label={m("meetings")}>
        <Button ref={createButton} className="meeting-new" variant="primary" loading={creating} disabled={!ready || (separateEditor && !!active)} onClick={() => void create()}>
          {!creating && <Plus aria-hidden="true" />}{m("create")}
        </Button>
        <div className="meeting-search">
          <Search size={15} aria-hidden="true" />
          <Input ref={searchField} type="search" aria-label={m("search")} placeholder={m("search")}
            maxLength={200} value={search} onChange={event => setSearch(event.target.value)}
            onKeyDown={event => { if (event.key === "Escape" && search) { event.stopPropagation(); setSearch(""); } }} />
          {search && <Button variant="ghost" className="meeting-search-clear" aria-label={m("clearSearch")} onClick={() => {
            setSearch("");
            searchField.current?.focus();
          }}><X aria-hidden="true" /></Button>}
        </div>
        {createError && <p className="error" role="alert">{m("createError")}</p>}
        {openError && <p className="error" role="alert">{m("loadError")}</p>}
        {activeLink}
        {visible.length > 0 && <ul className="meeting-list">
          {visible.map(entry => {
            const row = active?.id === entry.id ? { ...entry, status: active.status } : entry;
            const date = row.startedAt ?? row.createdAt;
            return <li key={row.id}>
              <Button ref={node => { if (node) listRows.current.set(row.id, node); else listRows.current.delete(row.id); }}
                variant="ghost" className="meeting-list-row" disabled={separateEditor && !!active && active.id !== row.id}
                aria-current={selected?.id === row.id ? "true" : undefined} onClick={() => select(row.id)}>
                <span className="meeting-row-title">{row.title.trim() || m("untitled")}</span>
                <span className="meeting-row-meta">
                  <time dateTime={new Date(date).toISOString()}>{dateLabel(date)}</time>
                  <MeetingStatus status={row.status} />
                </span>
              </Button>
            </li>;
          })}
        </ul>}
        {listBusy && !visible.length && <p className="meeting-hint" role="status">{m("loading")}</p>}
        {!listBusy && !listError && !visible.length && <p className="meeting-hint">{m(query ? "noResults" : "empty")}</p>}
        {listError && <div className="meeting-list-message">
          <p className="error" role="alert">{m("listError")}</p>
          <Button variant="text" onClick={() => void load(query)}>{m("retry")}</Button>
        </div>}
        {index.query === query && index.more && !listError &&
          <Button loading={listBusy} onClick={() => void load(query, index.offset)}>{m("more")}</Button>}
      </section>

      {selected && state ? <MeetingEditor key={selected.id} id={selected.id} initial={selected.initial}
        state={state} onBack={back} onDeleted={id => {
          if (id === selectedId.current) back();
          setIndex(previous => ({ ...previous, rows: previous.rows.filter(row => row.id !== id) }));
          void load(queryRef.current);
        }} activeLink={activeLink} openModels={() => void controller.navigate("models")} />
        : !separateEditor && <div className="meeting-placeholder">
          <CalendarDays size={22} aria-hidden="true" />
          <strong>{m(visible.length ? "select" : "empty")}</strong>
          <p className="meeting-hint">{m(visible.length ? "selectHint" : "emptyHint")}</p>
        </div>}
    </div>
  </div>;
}

type Template = Parameters<typeof meetingSummarize>[1];
type Source = MeetingEntry["source"];
const documentViews = ["notes", "transcript", "summary"] as const;
type DocumentView = (typeof documentViews)[number];
const errors = {
  capture: "captureError", install: "installError", cancelInstall: "installError",
  generate: "generateError", stopGenerate: "generateError", copy: "copyError", delete: "deleteError",
} as const;
type Action = keyof typeof errors;

export function MeetingEditor({ id, initial, state, onBack, onDeleted, activeLink, openModels }: {
  id: string;
  initial?: Meeting;
  state: MeetingState;
  onBack?: () => void;
  onDeleted: (id: string) => void;
  activeLink?: ReactNode;
  openModels: () => void;
}) {
  const compact = !onBack;
  const [meeting, setMeeting] = useState<Meeting | null | undefined>(initial);
  const [detailError, setDetailError] = useState(false);
  const [pending, setPending] = useState(() => saves.get(id)?.pending ?? {});
  const [saveFailed, setSaveFailed] = useState(() => saves.get(id)?.failed ?? false);
  const [source, setSource] = useState<Source | null>(null);
  const [recoverOverlap, setRecoverOverlap] = useState(false);
  const [view, setView] = useState<DocumentView>("notes");
  const [focusedView, setFocusedView] = useState<DocumentView | null>(null);
  const [template, setTemplate] = useState<Template>("brief");
  const [editSummary, setEditSummary] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "generate" | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [actionError, setActionError] = useState<(typeof errors)[Action] | "">("");
  const [reason, setReason] = useState("");
  const cancelStarting = useRef(false);
  const [copied, setCopied] = useState(false);
  const editor = useRef<HTMLElement>(null);
  const titleField = useRef<HTMLInputElement>(null);
  const capturePanel = useRef<HTMLElement>(null);
  const summaryPanel = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  const command = useRef<Action | null>(null);
  const mounted = useRef(false);
  const titleId = useId();
  const consentId = useId();
  const templateId = useId();
  const notesId = useId();
  const summaryId = useId();
  const documentId = useId();
  const tabs = useRef<HTMLDivElement>(null);
  const active = state.active?.id === id ? state.active : null;
  const activeStatus = active?.status;
  const generating = state.generating === id;
  const summaryPending = state.summaryPending === id;
  const summaryError = state.summaryError?.id === id ? state.summaryError.code : "";

  const read = useCallback(async () => {
    if (!mounted.current) return;
    const ticket = ++sequence.current;
    inFlight.current = true;
    try {
      const result = await meetingGet(id);
      if (ticket !== sequence.current) return;
      setDetailError(false);
      setMeeting(result);
    } catch {
      if (ticket === sequence.current) setDetailError(true);
    } finally {
      if (ticket === sequence.current) inFlight.current = false;
    }
  }, [id]);

  useLayoutEffect(() => {
    const target = initial ? titleField.current : editor.current;
    target?.focus({ preventScroll: true });
    if (initial) titleField.current?.select();
    editor.current?.closest(".scroll-area")?.scrollTo({ top: 0 });
  }, [initial]);
  useEffect(() => {
    mounted.current = true;
    const queue = queueFor(id);
    const changed: SaveListener = (saved, fields) => {
      setPending(queue.pending);
      setSaveFailed(queue.failed);
      if (saved && fields) {
        const confirmed: EditPatch = {};
        for (const field of fields) confirmed[field] = saved[field];
        setMeeting(previous => previous && { ...previous, ...confirmed });
        void read();
      }
    };
    queue.listeners.add(changed);
    changed();
    return () => {
      mounted.current = false;
      sequence.current++;
      queue.listeners.delete(changed);
      if (queue.timer !== undefined) void flushEdits(id, queue);
      releaseQueue(id, queue);
    };
  }, [id, read]);

  // Lifecycle changes refresh final segments and generated notes even without a new partial.
  useEffect(() => { void read(); }, [activeStatus, generating, summaryPending, state.summaryRevision, state.overlapRevision, read]);
  useEffect(() => {
    if (activeStatus !== "recording") return;
    const timer = window.setInterval(() => { if (!inFlight.current) void read(); }, 1500);
    return () => window.clearInterval(timer);
  }, [activeStatus, read]);

  const run = async (action: Action, operation: () => Promise<void>) => {
    if (command.current) return;
    command.current = action;
    const trigger = document.activeElement;
    setBusy(action);
    setActionError("");
    setReason("");
    setCopied(false);
    try {
      await operation();
      if (action === "copy") setCopied(true);
      if (action === "generate" || action === "delete") setConfirm(null);
    } catch (error) {
      if (!cancelStarting.current) {
        setActionError(errors[action]);
        setReason(error instanceof Error ? error.message : "");
      }
    } finally {
      if (action === "capture" || action === "generate" || action === "stopGenerate") await read();
      command.current = null;
      cancelStarting.current = false;
      setBusy(null);
      if (trigger && !trigger.isConnected && document.activeElement === document.body) {
        if (action === "capture") capturePanel.current?.focus({ preventScroll: true });
        if (action === "stopGenerate") summaryPanel.current?.focus({ preventScroll: true });
      }
    }
  };

  const flush = () => flushEdits(id, queueFor(id));
  const generate = () => void run("generate", async () => {
    if (!await flush()) throw new Error("meeting_edits_unsaved");
    await meetingSummarize(id, template);
  });
  const stopAndGenerate = () => void run("stopGenerate", async () => {
    if (!await flush()) throw new Error("meeting_edits_unsaved");
    await meetingStop(id, template);
  });
  const erase = () => void run("delete", async () => {
    // Finish an accepted write before deletion. A failed edit can be discarded here.
    await flush();
    await meetingDelete(id);
    saves.delete(id);
    publishDrafts();
    onDeleted(id);
  });

  const current = meeting && { ...meeting, ...pending };
  const status = activeStatus ?? current?.status;
  const duration = Math.max(active?.duration ?? 0, current?.duration ?? 0);
  const date = current ? current.startedAt ?? current.createdAt : 0;
  const selectedSource = source === "system" && !state.loopback ? null : source;
  const startable = status === "draft" || status === "interrupted";
  const needsModel = startable && state.supported && !state.installed;
  const canSetUpSpeakers = startable && state.installed && !state.active;
  const canStart = canSetUpSpeakers && state.supported && !generating;
  const canGenerate = current && !active && status && !isCapturing(status) &&
    (current.segments.length > 0 || !!current.notes.trim());
  const hasSummary = current && (current.hasSummary || !!current.summary || editSummary);
  const canStopAndGenerate = (activeStatus === "recording" || activeStatus === "paused") && !hasSummary;
  const summaryBusy = state.generating !== null || !!state.summaryPending;
  const actionLocked = busy !== null;
  const deleteDisabled = !!active || !!status && isCapturing(status) || generating || actionLocked;
  const confirmDelete = () => { setActionError(""); setConfirm("delete"); };
  const dialogError = confirm && actionError === (confirm === "delete" ? "deleteError" : "generateError");
  const flushOnBlur = () => { if (saves.get(id)?.timer !== undefined) void flush(); };
  const invalidFields = (Object.keys(pending) as (keyof EditPatch)[])
    .filter(field => !fitsField(field, pending[field]!));
  const moveTabFocus = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = documentViews.length - 1;
    const targets: Record<string, number> = {
      ArrowLeft: index === 0 ? last : index - 1,
      ArrowRight: index === last ? 0 : index + 1,
      Home: 0,
      End: last,
    };
    const target = targets[event.key];
    if (typeof target !== "number") return;
    event.preventDefault();
    tabs.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[target]?.focus();
  };

  return <section className="meeting-editor" tabIndex={-1} aria-label={m("title")} ref={editor}>
    {onBack && <Button variant="ghost" className="meeting-back" onClick={onBack}><ArrowLeft aria-hidden="true" />{m("back")}</Button>}
    {activeLink && <div className="meeting-editor-active">{activeLink}</div>}
    {detailError && <div className="meeting-message">
      <p className="error" role="alert">{m("loadError")}</p>
      <Button variant="text" onClick={() => void read()}>{m("retry")}</Button>
    </div>}
    {current ? <>
      <header className="meeting-editor-header">
        <div className="meeting-title-row">
          <label className="sr-only" htmlFor={titleId}>{m("title")}</label>
          <Input ref={titleField} id={titleId} unstyled shellClassName="meeting-title-field" placeholder={m("untitled")} value={current.title}
            readOnly={confirm === "delete"} onBlur={flushOnBlur} onChange={event => queueEdit(id, "title", event.target.value)} />
          {compact && <Menu>
            <MenuTrigger aria-label={m("moreActions")} title={m("moreActions")}
              render={<Button variant="ghost" />}><MoreHorizontal aria-hidden="true" /></MenuTrigger>
            <MenuPopup>
              <MenuItem disabled={actionLocked} onClick={() => void run("copy", () => meetingCopy(exportText(current)))}>
                <Copy aria-hidden="true" />{m("copy")}
              </MenuItem>
              <MenuItem onClick={() => downloadMeeting(current, exportText(current))}><Download aria-hidden="true" />{m("export")}</MenuItem>
              <MenuSeparator />
              <MenuItem variant="destructive" disabled={deleteDisabled} onClick={confirmDelete}><Trash2 aria-hidden="true" />{m("delete")}</MenuItem>
            </MenuPopup>
          </Menu>}
        </div>
        <div className="meeting-heading-meta">
          <time dateTime={new Date(date).toISOString()}>{!compact && <CalendarDays size={14} aria-hidden="true" />}{dateLabel(date, !compact)}</time>
          <span className={compact && !Object.keys(pending).length ? "sr-only" : "meeting-save-state"} role="status">
            {saveFailed ? "" : Object.keys(pending).length ? m("saving") : <><Check size={13} aria-hidden="true" />{m("saved")}</>}
          </span>
        </div>
        {(saveFailed || invalidFields.length > 0) && <div className="meeting-message">
          <p className="error" role="alert">{invalidFields.length
            ? invalidFields.map(field => m(field === "title" ? "titleTooLong" : field === "notes" ? "notesTooLong" : "summaryTooLong")).join(" ")
            : m("saveError")}</p>
          {!invalidFields.length && <Button variant="text" onClick={() => void flush()}>{m("retry")}</Button>}
        </div>}
      </header>

      {(!compact || startable || active) && <section className="meeting-capture" tabIndex={-1} aria-label={m("capture")} ref={capturePanel}>
        <div className="meeting-capture-heading">
          {!compact && <span className="meeting-capture-icon"><AudioLines size={19} aria-hidden="true" /></span>}
          <div className="meeting-capture-title">
            {(!compact || !active) && <h2>{m(compact ? "source" : "capture")}</h2>}
            <div className="meeting-capture-meta">
              {status && (!compact || active) && <div role="status"><MeetingStatus status={status} /></div>}
              {(active || current.startedAt !== null) && <span className="meeting-clock">{elapsed(duration)}</span>}
            </div>
            {compact && active && <span className="meeting-input-label">
              {m(active.source)}
              {active.status === "recording" && active.source === "system" && active.systemAudio && <span className="sr-only"> {m("systemSignal")}</span>}
            </span>}
          </div>
          {active && (active.status === "recording" || active.status === "paused") &&
            <div className="meeting-capture-actions">
              <Button disabled={actionLocked || state.releasing} onClick={() => void run("capture", () => active.status === "paused" ? meetingResume(id) : meetingPause(id))}>
                {active.status === "paused" ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
                {m(active.status === "paused" ? "resume" : "pause")}
              </Button>
              <Button className="meeting-destructive" aria-label={m("stop")} disabled={actionLocked} onClick={() => void run("capture", () => meetingStop(id))}>
                <Square aria-hidden="true" />{m(compact ? "stopShort" : "stop")}
              </Button>
            </div>}
          {active?.status === "starting" && <Button onClick={() => {
            cancelStarting.current = true;
            void meetingStop(id).catch(error => {
              setActionError("captureError");
              setReason(error instanceof Error ? error.message : "");
            });
          }}><Square aria-hidden="true" />{m("cancelStart")}</Button>}
        </div>
        {(current.startedAt !== null || active) && <div className="meeting-capture-meta meeting-capture-detail">
          {!compact && current.startedAt !== null && <span>{m(active?.source ?? current.source)}</span>}
          {!compact && active?.microphone && <span>{active.microphone}</span>}
          {active?.status === "recording" && active.source === "system" && (!compact || !active.systemAudio) &&
            <span role="status">{m(active.systemAudio ? "systemSignal" : isMacDesktop() ? "systemSilentMac" : "systemSilent")}</span>}
        </div>}
        {active?.lightMode && <p className="meeting-hint" role="status">{m("lightMode")}</p>}
        {state.releasing && <p className="meeting-hint" role="status">{m("releasing")}</p>}
        {active?.recoveringOverlap && <p className="meeting-hint" role="status">{m("overlapWorking")}</p>}
        {(active?.error || current.error) && <p className="error" role="alert">{meetingError(active?.error || current.error)}</p>}
        {startable && !state.supported && <p className="meeting-hint">{m("unavailable")}</p>}
        {(needsModel || canSetUpSpeakers) && <div className="meeting-capture-setup">
          {needsModel && <div className="meeting-install">
            <p className="meeting-hint" role="status">{m(state.installing ? "installing" : "installHint")}</p>
            {state.installing && <progress aria-label={m("installing")} max={100} value={state.installProgress > 0 ? state.installProgress : undefined} />}
            <div className="meeting-actions">
              {state.installing
                ? <Button loading={busy === "cancelInstall"} onClick={() => void run("cancelInstall", meetingCancelInstall)}>{m("cancelInstall")}</Button>
                : <Button variant="primary" loading={busy === "install"} onClick={() => void run("install", meetingInstall)}>{m("install")}</Button>}
              <Button variant="ghost" onClick={openModels}>{m("models")}</Button>
            </div>
          </div>}
          {canStart && <div className="meeting-start">
            <fieldset aria-describedby={consentId} disabled={actionLocked}>
              <legend className="sr-only">{m("source")}</legend>
              {(state.loopback ? ["mic", "system"] as const : ["mic"] as const).map(option =>
                <label className="meeting-source-option" key={option}>
                  <input type="radio" name={consentId} value={option} checked={selectedSource === option} onChange={() => setSource(option)} />
                  <span><strong>{m(option)}</strong><span className="meeting-hint">{m(option === "mic" ? "micHint" : "systemHint")}</span></span>
                </label>)}
            </fieldset>
            {selectedSource === "system" && state.overlapSupported && state.speakersInstalled &&
              <div className="meeting-speaker-setup">
                <p className="meeting-hint" id={`${consentId}-overlap`}>{m("overlapHint")}</p>
                {state.overlapInstalled ? <label className="meeting-source-option">
                  <input type="checkbox" checked={recoverOverlap} disabled={actionLocked || state.installing}
                    aria-describedby={`${consentId}-overlap`} onChange={event => setRecoverOverlap(event.target.checked)} />
                  <strong>{m("overlapOption")}</strong>
                </label> : state.installingOverlap ? <>
                  <progress max={100} value={state.installProgress} aria-label={m("overlapDownload")} />
                  <Button variant="ghost" onClick={() => void run("cancelInstall", meetingCancelInstall)}>{m("cancelInstall")}</Button>
                </> : <Button variant="ghost" disabled={actionLocked || state.installing}
                  onClick={() => void run("install", meetingInstallOverlap)}>{m("overlapDownload")}</Button>}
              </div>}
            <div className="meeting-start-footer">
              <p id={consentId} className="meeting-hint">{m("consent")}</p>
              <Button variant="primary" disabled={!selectedSource || actionLocked || state.releasing || state.installing} loading={busy === "capture"}
                onClick={() => { if (selectedSource) void run("capture", () =>
                  meetingStart(id, selectedSource, selectedSource === "system" && !!state.overlapInstalled && recoverOverlap)); }}>
                {busy !== "capture" && <Circle fill="currentColor" aria-hidden="true" />}{m("start")}
              </Button>
            </div>
          </div>}
          {canSetUpSpeakers && (!compact || !state.speakersInstalled) && <div className="meeting-speaker-setup">
            {state.speakersInstalled ? <span className="meeting-hint"><Check size={14} aria-hidden="true" />{m("speakerReady")}</span> :
              <>
                <p className="meeting-hint">{m("speakerDownloadHint")}</p>
                {state.installingSpeakers && <progress max={100} value={state.installProgress}
                  aria-label={m("speakerDownload")} />}
                {state.installingSpeakers
                  ? <Button variant="ghost" onClick={() => void run("cancelInstall", meetingCancelInstall)}>{m("cancelInstall")}</Button>
                  : <Button variant="ghost" disabled={actionLocked || state.installing}
                    onClick={() => void run("install", meetingInstallSpeakers)}>{m("speakerDownload")}</Button>}
              </>}
          </div>}
        </div>}
      </section>}
      {state.error && state.error !== current.error && state.error !== active?.error && <div className="meeting-actions">
        <p className="error" role="alert">{meetingError(state.error)}</p>
      </div>}
      {(actionError === "captureError" || actionError === "installError") && !current.error &&
        <p className="error" role="alert">{meetingError(reason, actionError)}</p>}

      <div className="meeting-workspace">
        <div className="meeting-tabs" role="tablist" aria-label={m("meetings")} ref={tabs}
          onBlur={event => {
            if (!event.currentTarget.contains(event.relatedTarget)) setFocusedView(null);
          }}>
          {documentViews.map((section, index) => <Button key={section} variant="ghost" role="tab"
            id={`${documentId}-tab-${section}`} aria-controls={`${documentId}-${section}`}
            aria-selected={view === section} tabIndex={(focusedView ?? view) === section ? 0 : -1}
            onFocus={() => setFocusedView(section)} onClick={() => setView(section)}
            onKeyDown={event => moveTabFocus(event, index)}>
            {m(compact && section === "notes" ? "notesTab" : section)}
            {section === "transcript" && activeStatus === "recording" && <span className="meeting-live-dot" aria-hidden="true" />}
          </Button>)}
        </div>
        <div role="tabpanel" id={`${documentId}-notes`} aria-labelledby={`${documentId}-tab-notes`} hidden={view !== "notes"}>
          <label className="sr-only" htmlFor={notesId}>{m("notes")}</label>
          <TextArea id={notesId} unstyled shellClassName="meeting-notes" value={current.notes}
            placeholder={m("notesHint")} readOnly={confirm === "delete"}
            onBlur={flushOnBlur} onChange={event => queueEdit(id, "notes", event.target.value)} />
        </div>

        <div role="tabpanel" tabIndex={0} id={`${documentId}-transcript`}
          aria-labelledby={`${documentId}-tab-transcript`} hidden={view !== "transcript"}>
          <MeetingTranscript meeting={current} partial={activeStatus === "recording" ? state.partial : ""}
            partialTurns={activeStatus === "recording" ? state.partialTurns : undefined}
            projectedPartial={activeStatus === "recording" && current.overlapRevision === state.overlapRevision
              ? state.projectedPartial : undefined}
            shown={view === "transcript"} recording={activeStatus === "recording"} labeling={!!active?.speakerLabels}
            revising={!!active?.liveSpeakerLabels} generating={generating}
            onNamed={() => void read()} />
        </div>

        <div role="tabpanel" tabIndex={0} ref={summaryPanel} id={`${documentId}-summary`}
          aria-labelledby={`${documentId}-tab-summary`} hidden={view !== "summary"}>
          <section className="meeting-document">
            {(summaryPending || generating) ? <p className="meeting-hint" role="status">
              {m(summaryPending ? "summaryFinalizing" : "generating")}
            </p> : (!compact || !hasSummary) && <p className="meeting-hint">
              {(!state.summaryAvailable && (canGenerate || canStopAndGenerate))
                ? meetingError("summary_setup")
                : m(canStopAndGenerate ? "stopGenerateHint" : canGenerate ? "summaryHint" : active ? "summaryAfterRecording" : "summaryUnavailable")}
            </p>}
            {summaryError && <p className="error" role="alert">{meetingError(summaryError, "generateError")}</p>}
            {actionError === "generateError" && !dialogError &&
              <p className="error" role="alert">{meetingError(reason, "generateError")}</p>}
            {hasSummary && <>
              {editSummary ? <>
                <label className="sr-only" htmlFor={summaryId}>{m("markdown")}</label>
                <TextArea id={summaryId} className="meeting-markdown" value={current.summary}
                  readOnly={generating || busy === "generate" || confirm !== null} onBlur={flushOnBlur}
                  onChange={event => queueEdit(id, "summary", event.target.value)} />
              </> : <SummaryPreview source={current.summary} />}
              <div><Button variant="text" disabled={generating} aria-expanded={editSummary}
                onClick={() => setEditSummary(value => !value)}>{m(editSummary ? "previewSummary" : "editSummary")}</Button></div>
            </>}
            {(canGenerate || canStopAndGenerate) && <div className="meeting-actions meeting-summary-actions">
              {state.summaryAvailable ? <>
                <label htmlFor={templateId}>{m("template")}</label>
                <select id={templateId} disabled={summaryBusy || actionLocked} value={template}
                  onChange={event => setTemplate(event.target.value as Template)}>
                  {(["brief", "decisions", "followup"] as const).map(option => <option key={option} value={option}>{m(option)}</option>)}
                </select>
                {canStopAndGenerate ? <Button disabled={summaryBusy || actionLocked}
                  loading={busy === "stopGenerate"} onClick={stopAndGenerate}>{m("stopGenerate")}</Button>
                  : <Button disabled={summaryBusy || actionLocked} loading={generating || busy === "generate"} onClick={() => {
                    setActionError("");
                    if (hasSummary) setConfirm("generate");
                    else generate();
                  }}>{m(generating || busy === "generate" ? "generating" : hasSummary ? "regenerate" : "generate")}</Button>}
              </> : <Button variant="ghost" onClick={openModels}>{m("models")}</Button>}
            </div>}
          </section>
        </div>
      </div>

      {(!compact || actionError === "copyError" || copied) && <footer className="meeting-editor-footer">
        {!compact && <>
        <div className="meeting-actions">
          <Button loading={busy === "copy"} disabled={actionLocked} onClick={() => void run("copy", () => meetingCopy(exportText(current)))}>
            <Copy aria-hidden="true" />{m("copy")}
          </Button>
          <Button onClick={() => downloadMeeting(current, exportText(current))}><Download aria-hidden="true" />{m("export")}</Button>
        </div>
        <Button variant="ghost" className="meeting-destructive" disabled={deleteDisabled}
          onClick={confirmDelete}><Trash2 aria-hidden="true" />{m("delete")}</Button>
        </>}
        {actionError === "copyError" && <p className="error" role="alert">{m(actionError)}</p>}
        {copied && <span role="status" className="meeting-copied">{m("copied")}</span>}
      </footer>}
    </> : !detailError && <p role="status" className="meeting-hint">{m(meeting === null ? "missing" : "loading")}</p>}

    <Confirm open={confirm !== null} onOpenChange={open => {
      if (!open && !command.current) {
        setConfirm(null);
        setActionError("");
      }
    }} title={m(confirm === "generate" ? "replaceTitle" : "delete")}
      description={m(confirm === "generate" ? "replaceHint" : "deleteHint")}
      error={dialogError && actionError && meetingError(reason, actionError)}>
      <Button disabled={actionLocked} onClick={() => { setConfirm(null); setActionError(""); }}>{m("cancel")}</Button>
      {confirm === "generate"
        ? <Button variant="primary" loading={busy === "generate"} disabled={summaryBusy || !state.summaryAvailable} onClick={generate}>{m("replace")}</Button>
        : <Button className="meeting-destructive" loading={busy === "delete"} disabled={!!active || generating} onClick={erase}>{m("delete")}</Button>}
    </Confirm>
  </section>;
}

function SummaryPreview({source}: {source: string}) {
  const inline = (text: string) => text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4
      ? <strong key={index}>{part.slice(2, -2)}</strong> : part
  );
  const blocks: ReactNode[] = [];
  const lines = source.split(/\r?\n/);
  let index = 0;
  while (index < lines.length) {
    const number = index;
    const line = lines[index++].trim();
    if (!line) continue;
    const heading = /^#{1,6}\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push(<h3 key={number}>{inline(heading[1])}</h3>);
    } else if (/^[-*+]\s+/.test(line)) {
      const items = [line.slice(2)];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) items.push(lines[index++].trim().slice(2));
      blocks.push(<ul key={number}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ul>);
    } else {
      blocks.push(<p key={number}>{inline(line)}</p>);
    }
  }
  return <div className="meeting-summary-preview">{blocks}</div>;
}

function MeetingTranscript({ meeting, partial, partialTurns, projectedPartial, shown, recording, labeling, revising, generating, onNamed }: {
  meeting: Meeting;
  partial: string;
  partialTurns?: TranscriptTurn[];
  projectedPartial?: TranscriptTurn[] | null;
  shown: boolean;
  recording: boolean;
  labeling: boolean;
  revising: boolean;
  generating: boolean;
  onNamed: () => void;
}) {
  const heading = useId();
  const speakerInput = useId();
  const searchInput = useRef<HTMLInputElement>(null);
  const searchButton = useRef<HTMLButtonElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [searching, setSearching] = useState(false);
  const [search, setSearch] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [renameError, setRenameError] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const {speakers, originalSegments} = meeting;
  const segments = showOriginal && originalSegments ? originalSegments : meeting.segments;
  const liveTurns = showOriginal ? partialTurns : projectedPartial ?? partialTurns;
  const liveText = !showOriginal && projectedPartial
    ? projectedPartial.map(turn => turn.text).join(" ") : partial;
  const query = search.trim().toLocaleLowerCase(uiLanguage);
  const assigned = segments.some(segment => segment.speaker != null);
  const visible = findTranscript({ ...meeting, segments }, search);
  useLayoutEffect(() => {
    if (searching) searchInput.current?.focus();
  }, [searching]);
  useLayoutEffect(() => {
    if (shown && recording && !query && follow.current && scroll.current) {
      scroll.current.scrollTop = scroll.current.scrollHeight;
    }
  }, [segments.length, liveText, liveTurns, recording, query, shown]);

  const saveName = async () => {
    if (renaming === null || saving) return;
    setSaving(true);
    setRenameError(false);
    try {
      await meetingNameSpeaker(meeting.id, renaming, name);
      setRenaming(null);
      onNamed();
    } catch {
      setRenameError(true);
    } finally {
      setSaving(false);
    }
  };
  const closeSearch = () => {
    setSearch("");
    setSearching(false);
    searchButton.current?.focus();
  };

  return <section className="meeting-document" aria-labelledby={heading}>
    <h2 id={heading} className="sr-only">{m("transcript")}</h2>
    {(segments.length > 0 || originalSegments || (recording && labeling)) && <div className="meeting-transcript-tools">
      {recording && labeling && <p className="meeting-hint">{m(revising ? "speakerRevisionHint" : "speakerLiveHint")}</p>}
      {originalSegments && <label className="meeting-source-option">
        <input type="checkbox" checked={showOriginal} onChange={event => setShowOriginal(event.target.checked)} />
        {m("overlapOriginal")}
      </label>}
      {segments.length > 0 && <Button ref={searchButton} className="meeting-find" variant="ghost"
        aria-expanded={searching} onClick={() => { if (searching) closeSearch(); else setSearching(true); }}>
        <Search aria-hidden="true" />{m("findTranscript")}
      </Button>}
    </div>}
    {searching && <Input ref={searchInput} type="search" aria-label={m("findTranscript")} placeholder={m("findTranscript")}
      value={search} onChange={event => setSearch(event.target.value)}
      onKeyDown={event => { if (event.key === "Escape") closeSearch(); }} />}
    {segments.length || recording ? <div className="meeting-transcript" ref={scroll} tabIndex={0}
      role="region" aria-labelledby={heading} onScroll={event => {
        const box = event.currentTarget;
        if (box.clientHeight) follow.current = box.scrollHeight - box.scrollTop - box.clientHeight <= 32;
      }}>
      <ol>
        {visible.map(segment => <li key={JSON.stringify([segment.start, segment.end, segment.source, segment.overlap, segment.text])}>
          <div className="meeting-turn">
            <div className="meeting-turn-meta">
              {segment.speaker === LOCAL_MICROPHONE || segment.speaker === SYSTEM_AUDIO ? <strong>{speakerLabel(segment.speaker)}</strong> : segment.speaker ? <Button variant="text" className="meeting-speaker-name" title={m("renameSpeaker")} aria-description={m("renameSpeaker")}
                disabled={generating} onClick={() => {
                  setRenameError(false);
                  setName(speakers?.[segment.speaker!] ?? "");
                  setRenaming(segment.speaker!);
                }}><span>{speakerLabel(segment.speaker, speakers)}</span><Pencil size={12} aria-hidden="true" /></Button>
                : !segment.overlap && assigned && <span className="meeting-hint">{m("unknownSpeaker")}</span>}
              {segment.overlap && <span className={segment.speaker ? "meeting-hint" : undefined}>{m("overlapTurn")}</span>}
              <span className="meeting-clock">{range(segment)}</span>
            </div>
            <div>{segment.text}</div>
          </div>
        </li>)}
      </ol>
      {query && !visible.length && <p className="meeting-hint" role="status">{m("noTranscriptMatches")}</p>}
      {recording && !query && <div className="meeting-partial">
        <div className="meeting-partial-status">
          <span className="meeting-live-dot" aria-hidden="true" />{m(liveText ? "partial" : "listening")}
        </div>
        {liveText && (liveTurns?.length ? liveTurns.map((turn, index) => <div className="meeting-turn" key={index}>
          <div className="meeting-turn-meta">
            <strong>{turn.speaker ? speakerLabel(turn.speaker, speakers) : m("unknownSpeaker")}</strong>
            <span className="meeting-clock">{range(turn)}</span>
          </div>
          <div>{turn.text}</div>
        </div>) : <div>{liveText}</div>)}
      </div>}
    </div> : <p className="meeting-hint">{m(meeting.startedAt !== null ? "noSpeech" : "transcriptEmpty")}</p>}
    <Dialog open={renaming !== null} onOpenChange={open => { if (!open && !saving) setRenaming(null); }}>
      <DialogPopup>
        <DialogHeader>
          <DialogTitle>{m("renameSpeaker")}</DialogTitle>
          <DialogDescription>{m("renameHint")}</DialogDescription>
        </DialogHeader>
        <div className="meeting-rename-body">
          <label className="sr-only" htmlFor={speakerInput}>{m("speakerName")}</label>
          <Input id={speakerInput} placeholder={m("speakerName")} maxLength={80} value={name} disabled={saving}
            onChange={event => setName(event.target.value)} onKeyDown={event => {
              if (event.key === "Enter") { event.preventDefault(); void saveName(); }
            }} />
          {renameError && <p className="error" role="alert">{m("renameFailed")}</p>}
        </div>
        <DialogFooter>
          <Button disabled={saving} onClick={() => setRenaming(null)}>{m("cancel")}</Button>
          <Button variant="primary" loading={saving} onClick={() => void saveName()}>{m("saveSpeaker")}</Button>
        </DialogFooter>
      </DialogPopup>
    </Dialog>
  </section>;
}
