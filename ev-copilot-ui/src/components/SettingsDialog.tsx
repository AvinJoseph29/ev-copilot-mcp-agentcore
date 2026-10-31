"use client";

import { useEffect, useRef, useState } from "react";

import { XIcon } from "./Icons";

interface SettingsDialogProps {
  open: boolean;
  initialName: string;
  onClose: () => void;
  onSave: (name: string) => void;
}

/** Settings panel (reference: Chainlit ChatSettings with a single "Your Name" text input). */
export default function SettingsDialog({ open, initialName, onClose, onSave }: SettingsDialogProps) {
  if (!open) return null;
  return <SettingsForm initialName={initialName} onClose={onClose} onSave={onSave} />;
}

function SettingsForm({ initialName, onClose, onSave }: Omit<SettingsDialogProps, "open">) {
  const [name, setName] = useState(initialName);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.select();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="w-full max-w-sm rounded-2xl border border-line bg-surface shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 id="settings-title" className="text-sm font-semibold">
            Settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 hover:bg-surface-3 hover:text-ink"
          >
            <XIcon size={16} />
          </button>
        </div>
        <form
          className="px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            onSave(name);
          }}
        >
          <label htmlFor="customer-name" className="text-xs font-medium text-ink-2">
            Your Name
          </label>
          <input
            ref={inputRef}
            id="customer-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter your name"
            maxLength={64}
            autoComplete="name"
            className="mt-1.5 w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none"
          />
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            EV Copilot remembers your vehicle and preferences under this name.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-2 hover:bg-surface-3 hover:text-ink"
            >
              Cancel
            </button>
            <button type="submit" className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white hover:bg-accent-strong">
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
