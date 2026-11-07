import { useEffect, useRef, useState } from "../../vendor/react.js";
import { html } from "../lib/html.js";

const DELAY_MS = 250;

/**
 * Text input that keeps what the user typed and only reports it after a pause.
 * It re-syncs from `value` only when the parent changes it to something other
 * than what this input last reported, so in-flight keystrokes are never overwritten.
 */
export function DebouncedTextInput({ value, onChange, ...rest }) {
  const [local, setLocal] = useState(value);
  const lastReported = useRef(value);
  const timer = useRef(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (value !== lastReported.current) {
      lastReported.current = value;
      setLocal(value);
    }
  }, [value]);

  useEffect(() => () => clearTimeout(timer.current), []);

  return html`<input
    type="text"
    ...${rest}
    value=${local}
    onChange=${(e) => {
      const next = e.target.value;
      setLocal(next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        lastReported.current = next;
        onChangeRef.current(next);
      }, DELAY_MS);
    }}
  />`;
}
