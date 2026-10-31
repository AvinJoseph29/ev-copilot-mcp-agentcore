"use client";

import { useLayoutEffect, useRef, type Ref } from "react";

import { SendIcon } from "./Icons";

interface ComposerProps {
  ref?: Ref<HTMLTextAreaElement>;
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  disabled: boolean;
  hasLocation: boolean;
}

const MAX_HEIGHT_PX = 180;

export default function Composer({ ref, value, onChange, onSend, disabled, hasLocation }: ComposerProps) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow the textarea up to MAX_HEIGHT_PX.
  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  const canSend = !disabled && value.trim().length > 0;

  const submit = () => {
    if (canSend) onSend(value);
  };

  return (
    <div className="shrink-0 border-t border-line bg-surface px-4 pt-3 pb-3 sm:px-6">
      <form
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-line bg-surface-2 p-1.5 pl-3.5 transition focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={(node) => {
            innerRef.current = node;
            if (typeof ref === "function") ref(node);
            else if (ref) (ref as { current: HTMLTextAreaElement | null }).current = node;
          }}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={hasLocation ? "Where are we driving? e.g. Pune to Goa in my Nexon EV" : "Type !location <lat> <lng> or allow location access"}
          aria-label="Message EV Copilot"
          className="max-h-[180px] min-h-[36px] flex-1 resize-none bg-transparent py-2 text-sm text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-white transition hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendIcon size={17} strokeWidth={2.2} />
        </button>
      </form>
      <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-ink-3">
        {disabled ? "EV Copilot is working on your trip…" : "Enter to send · Shift+Enter for a new line · Battery estimates are approximate"}
      </p>
    </div>
  );
}
