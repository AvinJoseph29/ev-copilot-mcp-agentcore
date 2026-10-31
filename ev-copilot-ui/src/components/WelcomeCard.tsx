"use client";

import { BatteryIcon, BoltIcon, CloudIcon, CoffeeIcon, RouteIcon } from "./Icons";

/**
 * Landing content (replaces the reference `chainlit.md` welcome screen):
 * capabilities + example prompts that fill the composer.
 */

const CAPABILITIES = [
  {
    icon: RouteIcon,
    title: "Route + charging stops",
    text: "Plans the drive and picks charging stops that fit your car.",
  },
  {
    icon: BoltIcon,
    title: "Live charger availability",
    text: "Shows which connectors are free right now, with power and detour.",
  },
  {
    icon: BatteryIcon,
    title: "Battery at every stop",
    text: "Simulates charge per leg using elevation, speed and temperature.",
  },
  {
    icon: CloudIcon,
    title: "Weather & amenities",
    text: "Flags weather alerts and finds food or coffee near each stop.",
  },
];

export const EXAMPLE_PROMPTS = [
  "Plan a trip from Mumbai to Goa in my Tata Nexon EV 45, starting at 90% battery",
  "Find fast chargers with free connectors near me",
  "Bengaluru to Mysuru in a Hyundai Ioniq 5 — where can I charge and grab lunch?",
  "San Francisco to Los Angeles in a Tesla Model 3 Long Range, keep a 20% buffer",
];

interface WelcomeCardProps {
  compact: boolean;
  onPickExample: (text: string) => void;
}

export default function WelcomeCard({ compact, onPickExample }: WelcomeCardProps) {
  if (compact) {
    return (
      <div className="flex items-center gap-2 self-center rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-3">
        <BoltIcon size={12} className="text-accent" />
        EV Copilot — plans routes, chargers, battery and weather
      </div>
    );
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
      <div className="border-b border-line bg-linear-to-br from-accent-soft to-surface px-5 py-5">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-wide text-accent-ink uppercase">
          <BoltIcon size={14} />
          Welcome to EV Copilot
        </div>
        <h1 className="mt-1.5 text-lg font-semibold tracking-tight text-ink sm:text-xl">
          Your AI co-pilot for electric road trips
        </h1>
        <p className="mt-1 text-sm text-ink-2">
          Tell me where you&apos;re going and what you drive. I&apos;ll plan the route, choose charging stops with
          live availability and check your battery at every leg.
        </p>
      </div>

      <div className="grid gap-px bg-line sm:grid-cols-2">
        {CAPABILITIES.map(({ icon: Icon, title, text }) => (
          <div key={title} className="flex gap-3 bg-surface px-5 py-3.5">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
              <Icon size={16} />
            </span>
            <div>
              <div className="text-sm font-medium text-ink">{title}</div>
              <div className="text-xs leading-relaxed text-ink-3">{text}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-line px-5 py-4">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ink-3">
          <CoffeeIcon size={13} />
          Try asking
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onPickExample(prompt)}
              className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-left text-xs text-ink-2 transition hover:border-accent hover:bg-accent-soft hover:text-accent-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              {prompt}
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-ink-3">
          Your location is detected in the browser. To set it manually, type{" "}
          <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[11px]">!location &lt;latitude&gt; &lt;longitude&gt;</code>
        </p>
      </div>
    </section>
  );
}
