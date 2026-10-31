"use client";

import { useEffect, useRef, type RefObject } from "react";

import type { ChatMessage } from "@/lib/types";

import Composer from "./Composer";
import MessageBubble from "./MessageBubble";
import WelcomeCard from "./WelcomeCard";

interface ChatPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  hasLocation: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: (text: string) => void;
  onPickExample: (text: string) => void;
  composerRef: RefObject<HTMLTextAreaElement | null>;
}

/** Distance from the bottom (px) within which new content keeps the view pinned to the end. */
const STICK_THRESHOLD_PX = 120;

export default function ChatPanel({
  messages,
  isStreaming,
  hasLocation,
  draft,
  onDraftChange,
  onSend,
  onPickExample,
  composerRef,
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const lastCount = useRef(messages.length);

  // Auto-scroll while streaming unless the user scrolled up; always scroll on a new message.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const added = messages.length > lastCount.current;
    lastCount.current = messages.length;
    if (added || stickToBottom.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: added ? "smooth" : "auto" });
    }
  }, [messages]);

  const hasConversation = messages.some((m) => m.role === "user");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
        }}
        className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6"
        aria-live="polite"
        aria-busy={isStreaming}
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          <WelcomeCard compact={hasConversation} onPickExample={onPickExample} />
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>
      </div>

      <Composer
        ref={composerRef}
        value={draft}
        onChange={onDraftChange}
        onSend={onSend}
        disabled={isStreaming}
        hasLocation={hasLocation}
      />
    </div>
  );
}
