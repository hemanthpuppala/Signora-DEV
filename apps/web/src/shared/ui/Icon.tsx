import type { ReactNode } from "react";

/** The interface's icons: line drawings in the text colour, one home for each shape. */
const SHAPES = {
  download: (
    <>
      <path d="M12 4v11" />
      <path d="m7 10.5 5 5 5-5" />
      <path d="M5 19.5h14" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  chevron: <path d="m9 6 6 6-6 6" />, // points right; turned to point down when open
  close: <path d="M6 6l12 12M18 6 6 18" />,
  // A paper plane: send for signature.
  send: (
    <>
      <path d="M20.5 3.5 3.5 10.5l7 3 3 7Z" />
      <path d="m10.5 13.5 10-10" />
    </>
  ),
  // Two sheets: something on every page.
  pages: (
    <>
      <path d="M8 3.5h8.5l3 3V17H8Z" />
      <path d="M5 7v13.5h11" />
    </>
  ),
  // One box becoming two: make a place its own field.
  split: (
    <>
      <path d="M4 5h7v6H4Z" />
      <path d="M13 13h7v6h-7Z" />
      <path d="m14 5 5 0M19 5v5" />
    </>
  ),
  trash: (
    <>
      <path d="M4.5 6.5h15" />
      <path d="M9.5 6.5V4.5h5v2" />
      <path d="M6.5 6.5 7.5 19.5h9l1-13" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </>
  ),
  star: <path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8Z" />,
  upload: (
    <>
      <path d="M12 15.5V4.5" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 19.5h14" />
    </>
  ),
  edit: (
    <>
      <path d="M15.5 5.5 18.5 8.5" />
      <path d="M4.5 19.5 5.3 15.7 16 5a2.1 2.1 0 0 1 3 3L8.3 18.7Z" />
    </>
  ),
  archive: (
    <>
      <path d="M4 5h16v4H4Z" />
      <path d="M5.5 9v10h13V9" />
      <path d="M10 13h4" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof SHAPES;

/**
 * An icon, hidden from assistive technology: whatever it sits in carries the words. ``filled``
 * fills the shape (a star that is on).
 */
export function Icon({
  name,
  size = 16,
  filled = false,
  className,
}: {
  name: IconName;
  size?: number;
  filled?: boolean | undefined;
  className?: string | undefined;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {SHAPES[name]}
    </svg>
  );
}
