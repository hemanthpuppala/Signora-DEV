"use client";

import { useEffect, useId, useRef, useState } from "react";

import { TextButton } from "./Button";
import styles from "./clamped.module.css";

/**
 * Small secondary text (e.g. a description) shown on one line. When it does not fit, "More" opens
 * it to about four lines in a scrollable box, so long text never pushes the page down; "Less"
 * closes it. The button only appears when the text actually overflows.
 */
export function ClampedText({ children }: { children: string }) {
  const id = useId();
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || expanded) return undefined;
    const measure = () => setOverflows(element.scrollWidth > element.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [children, expanded]);

  return (
    <div className={expanded ? styles.open : styles.closed}>
      <p
        id={id}
        ref={ref}
        className={expanded ? styles.expanded : styles.collapsed}
        // Focusable while open, so keyboard users can scroll a long description.
        {...(expanded ? { tabIndex: 0 } : {})}
      >
        {children}
      </p>
      {overflows || expanded ? (
        <TextButton aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Less" : "More"}
        </TextButton>
      ) : null}
    </div>
  );
}
