"use client";

import { TextButton } from "@/shared/ui";

import styles from "../fields.module.css";

/** "‹ Place 2 of 3 ›": steps through a field's places; the viewer follows. */
export function PlaceStepper({ place, places, onPlace }: { place: number; places: number; onPlace: (place: number) => void }) {
  return (
    <div className={styles.stepper}>
      <TextButton aria-label="Previous place" disabled={place <= 0} onClick={() => onPlace(place - 1)}>
        ‹
      </TextButton>
      <span>{`Place ${place + 1} of ${places}`}</span>
      <TextButton aria-label="Next place" disabled={place >= places - 1} onClick={() => onPlace(place + 1)}>
        ›
      </TextButton>
    </div>
  );
}
