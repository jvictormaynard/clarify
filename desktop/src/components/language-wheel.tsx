import { useEffect, useId, useRef } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./ui";

import { interfaceLanguages as languages } from "../settings/interface-languages";
import { LanguageMark } from "./language-mark";

/** Interface language only. Spoken and output languages have separate controls. */
export function LanguageWheel({ value, onChange, disabled }: { value: string; onChange: (value: string) => void; disabled: boolean }) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y: number; id?: string } | null>(null);
  const scroll = useRef({ amount: 0, last: 0 });
  const index = Math.max(0, languages.findIndex(item => value.startsWith(item.id)));
  const move = (direction: number) => { if (!disabled) onChange(languages[(index + direction + languages.length) % languages.length].id); };
  // A non-passive listener lets the wheel own its input without scrolling the page.
  useEffect(() => {
    const node = root.current;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      if (disabled) return;
      const now = performance.now();
      if (now - scroll.current.last < 180) return;
      scroll.current.amount += event.deltaY * (event.deltaMode === 1 ? 16 : 1);
      if (Math.abs(scroll.current.amount) >= 30) {
        move(Math.sign(scroll.current.amount));
        scroll.current = { amount: 0, last: now };
      }
    };
    node?.addEventListener("wheel", wheel, { passive: false });
    return () => node?.removeEventListener("wheel", wheel);
  });
  return <div className="setup-language-wheel">
    <div ref={root} role="listbox" tabIndex={disabled ? -1 : 0} aria-label={t("setup_interface_language")}
      aria-disabled={disabled} aria-activedescendant={`${id}-${languages[index].id}`} className="setup-language-options"
      onKeyDown={event => {
        if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          if (!disabled) event.key === "Home" ? onChange(languages[0].id) : event.key === "End" ? onChange(languages[languages.length - 1].id) : move(event.key === "ArrowDown" ? 1 : -1);
        }
      }}
      onPointerDown={event => { if (!disabled) { drag.current = { y: event.clientY, id: (event.target as HTMLElement).closest<HTMLElement>('[role="option"]')?.dataset.language }; event.currentTarget.setPointerCapture(event.pointerId); event.currentTarget.focus(); } }}
      onPointerUp={event => { if (drag.current !== null) { if (Math.abs(event.clientY - drag.current.y) > 25) move(event.clientY < drag.current.y ? 1 : -1); else if (!disabled && drag.current.id) onChange(drag.current.id); } drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}>
      {languages.map((item, itemIndex) => {
        const offset = (itemIndex - index + languages.length + 2) % languages.length - 2;
        return <div id={`${id}-${item.id}`} key={item.id} role="option" aria-selected={itemIndex === index}
          data-offset={offset} data-language={item.id}><LanguageMark code={item.id} /><span>{item.label}</span></div>;
      })}
    </div>
    <div className="setup-language-arrows">
      <Button variant="text" aria-label={t("setup_previous_language")} disabled={disabled} onClick={() => move(-1)}><ChevronUp aria-hidden="true" /></Button>
      <Button variant="text" aria-label={t("setup_next_language")} disabled={disabled} onClick={() => move(1)}><ChevronDown aria-hidden="true" /></Button>
    </div>
  </div>;
}
