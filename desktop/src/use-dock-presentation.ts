import { useEffect, useRef, useState } from 'react';
import { electron } from './platform';

/** Presentation only. Workflow, native focus and mouse capture keep their owners. */
export function useDockPresentation(closeMenus: () => void) {
  const [expanded, setExpanded] = useState(false);
  const inside = useRef(false);
  const pressed = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const close = useRef(closeMenus);
  close.current = closeMenus;
  const clear = () => { clearTimeout(timer.current); timer.current = undefined; };
  const collapse = () => { clear(); close.current(); setExpanded(false); };
  const enter = () => { inside.current = true; clear(); setExpanded(true); };
  const leave = () => {
    inside.current = false; clear();
    timer.current = setTimeout(() => {
      if (!inside.current && !pressed.current) collapse();
    }, 300);
  };
  const release = () => { pressed.current = false; if (!inside.current) leave(); };
  useEffect(() => {
    const off = electron()?.onWindow(event => {
      if (event === 'pointer-enter') enter();
      else if (event === 'pointer-leave') leave();
      else if (event === 'dock-expand') { clear(); setExpanded(true); }
      else if (event === 'dock-collapse') collapse();
      else if (event === 'dock-toggle') { clear(); close.current(); setExpanded(value => !value); }
    });
    document.addEventListener('pointerup', release);
    document.addEventListener('pointercancel', release);
    return () => {
      clear(); off?.();
      document.removeEventListener('pointerup', release);
      document.removeEventListener('pointercancel', release);
    };
  }, []);
  return {
    expanded, collapse, workflowChanged: () => { clear(); close.current(); setExpanded(inside.current); }, expand: () => { clear(); setExpanded(true); },
    pointerEnter: () => { if (!electron()) enter(); },
    pointerLeave: () => { if (!electron()) leave(); },
    press: () => { pressed.current = true; clear(); },
    release,
  };
}
