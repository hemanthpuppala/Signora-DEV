import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./typography.module.css";

type TextProps = {
  children: ReactNode;
  className?: string;
  as?: ElementType;
} & Omit<ComponentPropsWithoutRef<"p">, "className" | "children">;

function make(styleName: keyof typeof styles, defaultTag: ElementType) {
  function Text({ as: Tag = defaultTag, className, children, ...rest }: TextProps) {
    return (
      <Tag className={cx(styles[styleName], className)} {...rest}>
        {children}
      </Tag>
    );
  }
  Text.displayName = styleName;
  return Text;
}

/** Tracked uppercase micro-label used above headings and sections. */
export const Eyebrow = make("eyebrow", "p");
/** Uppercase caption, e.g. back links. */
export const Cap = make("cap", "span");
export const Display = make("display", "h1");
export const Heading1 = make("h1", "h1");
export const Heading2 = make("h2", "h2");
/** Italic serif subtitle under a heading. */
export const Sub = make("sub", "p");
export const BodyText = make("body", "p");
export const SmallText = make("small", "p");
export const Mono = make("mono", "span");
