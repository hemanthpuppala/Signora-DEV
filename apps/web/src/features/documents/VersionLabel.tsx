import styles from "./document.module.css";

/** A version's short name, "V2", with a star when it is the current one (above the viewer and in the list). */
export function VersionLabel({ number, current }: { number: number; current: boolean }) {
  return (
    <span className={styles.versionLabel}>
      {`V${number}`}
      {current ? (
        <svg className={styles.star} width="12" height="12" viewBox="0 0 24 24" role="img" aria-label="Current">
          <title>Current</title>
          <path
            d="m12 2.5 2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8Z"
            fill="currentColor"
          />
        </svg>
      ) : null}
    </span>
  );
}
