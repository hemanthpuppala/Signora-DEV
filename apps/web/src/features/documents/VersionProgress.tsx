import type { Version } from "./api";
import styles from "./document.module.css";
import type { Uploading } from "./NewVersion";

const STEPS = ["Upload", "Process", "Find fields", "Ready"] as const;

/**
 * Where a new version is on its way to ready, as one line of steps: uploading (with its share),
 * processing, finding fields. It stands until the version is ready; a version that stops on the
 * way (a password, scanned pages, a failure) says so in its own notice instead.
 */
export function VersionProgress({ uploading, version }: { uploading: Uploading | null; version: Version | undefined }) {
  const step = uploading ? 0 : version?.status === "processing" ? 1 : version?.status === "detecting" ? 2 : null;
  if (step === null) return null;
  return (
    <div className={styles.progress}>
      <span className={styles.detail}>{uploading ? uploading.name : `V${version?.number ?? ""}`}</span>
      <ol className={styles.train} aria-label={`New version: ${STEPS[step]}`}>
        {STEPS.map((label, index) => (
          <li key={label} className={index < step ? styles.stepDone : index === step ? styles.stepNow : styles.stepNext}>
            <span aria-hidden="true">{index < step ? "✓" : index === step ? "●" : "○"}</span>
            <span>{index === 0 && uploading ? `${label} ${Math.round(uploading.progress * 100)}%` : label}</span>
          </li>
        ))}
      </ol>
      {uploading ? <progress value={uploading.progress} max={1} aria-label={`Uploading ${uploading.name}`} /> : null}
    </div>
  );
}
