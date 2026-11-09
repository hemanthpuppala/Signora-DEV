"use client";

import { Chip, ChipGroup } from "@/shared/ui";

import type { DraftPlace } from "./editor";

/**
 * A field's places as chips (Phase 6 §7.1): "1 · Page 1", "2 · Page 3", or a choice's own words.
 * The chosen one is filled; choosing one brings it into view on the PDF.
 */
export function PlaceChips({
  places,
  place,
  onPlace,
  choice,
}: {
  places: readonly Pick<DraftPlace, "id" | "page" | "option_text" | "option_value">[];
  place: number;
  onPlace: (place: number) => void;
  choice: boolean;
}) {
  return (
    <ChipGroup label="Places">
      {places.map((item, index) => {
        const words = choice ? item.option_text ?? item.option_value ?? `Option ${index + 1}` : `${index + 1} · Page ${item.page}`;
        return (
          <Chip
            key={item.id}
            selected={index === place}
            label={choice ? `${words}, page ${item.page}` : `Place ${index + 1}, page ${item.page}`}
            onClick={() => onPlace(index)}
          >
            {words}
          </Chip>
        );
      })}
    </ChipGroup>
  );
}
