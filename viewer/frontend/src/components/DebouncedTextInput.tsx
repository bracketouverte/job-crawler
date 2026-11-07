import { useEffect, useState } from "react";

import { useDebouncedCallback } from "../hooks/useDebouncedCallback";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  "aria-label"?: string;
  disabled?: boolean;
}

export function DebouncedTextInput({ value, onChange, disabled, ...rest }: Props) {
  const [local, setLocal] = useState(value);
  const debouncedOnChange = useDebouncedCallback(onChange, 250);

  useEffect(() => setLocal(value), [value]);

  return (
    <input
      type="text"
      value={local}
      disabled={disabled}
      onChange={(e) => {
        setLocal(e.target.value);
        debouncedOnChange(e.target.value);
      }}
      {...rest}
    />
  );
}
