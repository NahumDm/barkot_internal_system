import type { CSSProperties } from "react";

/**
 * The two official Barkot logos, served verbatim from `public/brand/`.
 *
 * Both source files are used as-is and unmodified; only the rendered size is
 * chosen by the caller. `variant="compact"` is the short mark for the sidebar,
 * `variant="full"` is the full logo for the auth screens. The artwork is theirs
 * — this component only handles pointing at it and describing it.
 */

const SOURCES = {
  compact: "/brand/rlogo-design.jpg",
  full: "/brand/barkot%20logo.png",
} as const;

export function BarkotLogo({
  variant,
  className,
  style,
}: Readonly<{
  variant: keyof typeof SOURCES;
  className?: string;
  style?: CSSProperties;
}>) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- local static brand art
    <img
      src={SOURCES[variant]}
      alt="Barkot"
      width={4397}
      height={2400}
      className={className}
      style={style}
    />
  );
}