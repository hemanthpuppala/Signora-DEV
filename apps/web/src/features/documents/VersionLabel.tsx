import { Icon, Tooltip } from "@/shared/ui";

import styles from "./document.module.css";

/** A version's short name, "V2", with a star when it is the current one (beside the name and in the list). */
export function VersionLabel({ number, current }: { number: number; current: boolean }) {
  return (
    <span className={styles.versionLabel}>
      {`V${number}`}
      {current ? (
        <Tooltip label="Current version">
          <span className={styles.star} role="img" aria-label="Current">
            <Icon name="star" size={12} filled />
          </span>
        </Tooltip>
      ) : null}
    </span>
  );
}
