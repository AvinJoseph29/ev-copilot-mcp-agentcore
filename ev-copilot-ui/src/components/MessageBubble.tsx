"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessage } from "@/lib/types";

import { AlertIcon, BoltIcon } from "./Icons";
import ToolActivity from "./ToolActivity";

const markdownComponents: Components = {
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
};

const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-ink-3">
      <span className="flex gap-1" aria-hidden="true">
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent" />
      </span>
      {label}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-user px-4 py-2.5 text-sm whitespace-pre-wrap text-user-ink shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "notice") {
    return (
      <div className="rounded-xl border border-dashed border-line bg-surface-2 px-4 py-3 text-ink-2">
        <Markdown text={message.content} />
      </div>
    );
  }

  const streaming = message.status === "streaming";
  const tools = message.tools ?? [];
  const toolRunning = tools.some((t) => t.status === "running");
  const isProblem = message.status === "error" || message.status === "blocked";

  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
        <BoltIcon size={15} strokeWidth={2.2} />
      </span>
      <div
        className={`min-w-0 flex-1 rounded-2xl rounded-tl-md border px-4 py-3 shadow-sm ${
          isProblem
            ? message.status === "error"
              ? "border-bad/30 bg-bad/5"
              : "border-warn/40 bg-warn/5"
            : "border-line bg-surface"
        }`}
      >
        <ToolActivity tools={tools} active={streaming} />
        {isProblem && (
          <div className={`mb-1 flex items-center gap-1.5 text-xs font-medium ${message.status === "error" ? "text-bad" : "text-warn"}`}>
            <AlertIcon size={14} />
            {message.status === "error" ? "Something went wrong" : "Request blocked"}
          </div>
        )}
        {message.content ? (
          <Markdown text={message.content} />
        ) : streaming ? (
          <ThinkingIndicator label={toolRunning ? "Working on your trip…" : "Thinking…"} />
        ) : null}
      </div>
    </div>
  );
}

export default memo(MessageBubble);
