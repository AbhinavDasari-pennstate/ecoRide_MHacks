import { cn } from "@/lib/utils";

/**
 * ERIDE wordmark: the continuous-line car stays exactly as drawn and
 * stands in for the R, flanked by plain "E" and "IDE" lettering —
 * E + car + IDE. No ring, no circling strokes.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 160 160" className={cn("inline-block", className)} aria-hidden>
      <g
        fill="none"
        stroke="#5C5F3D"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* the car, untouched: nose -> hood -> roof -> rear -> underside */}
        <path d="M 34 90 C 28 93 22 95 20 99 C 16 84 26 72 42 68 C 54 64 60 56 76 54 C 92 52 106 58 114 66 C 122 74 128 84 126 94 C 122 102 112 106 102 104 C 92 110 76 116 66 122" />
        {/* front underside */}
        <path d="M 20 100 C 26 108 34 111 42 109" />
        {/* wheels: open circles */}
        <path d="M 48 89 A 11 11 0 1 1 47.8 89" />
        <path d="M 112 89 A 11 11 0 1 1 111.8 89" />

        {/* front E: circles around the nose, ends kissing the headlight area */}
        <path d="M 44 118 C 24 122 8 110 8 92 C 8 74 22 62 38 62" />
        <path d="M 10 92 C 16 90 22 90 27 91" />

        {/* rear E: circles around the tail, mirrored so it reads as E */}
        <path d="M 116 118 C 136 122 152 110 152 92 C 152 74 138 62 122 62" />
        <path d="M 150 92 C 144 90 138 90 133 91" />
      </g>
      {/* leaf off the roofline, lighter green */}
      <g
        fill="none"
        stroke="#9FA571"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M 114 66 C 122 58 127 50 129 41" />
        <path d="M 129 41 C 120 43 114 51 116 60 C 125 58 131 50 129 41 Z" />
      </g>
    </svg>
  );
}

/** Header brand: E + car + IDE, with the car standing in for the R. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex select-none items-center", className)} aria-label="ERIDE">
      <span className="text-[1.9rem] font-extrabold leading-none tracking-tight text-forest">
        E
      </span>
      <LogoMark className="mx-1 size-12 shrink-0" />
      <span className="text-[1.9rem] font-extrabold leading-none tracking-tight text-forest">
        IDE
      </span>
    </span>
  );
}
