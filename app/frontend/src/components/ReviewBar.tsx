import styles from "./ReviewBar.module.css";

/** How much of a run is reviewed, split by verdict colour. */
export function ReviewBar({
  total,
  confirmed,
  rejected,
  unsure,
  thin,
}: {
  total: number;
  confirmed: number;
  rejected: number;
  unsure: number;
  thin?: boolean;
}) {
  const share = (n: number) => `${(n / Math.max(1, total)) * 100}%`;
  return (
    <div
      className={thin ? `${styles.bar} ${styles.thin}` : styles.bar}
      role="img"
      aria-label={`${confirmed + rejected + unsure} of ${total} reviewed`}
    >
      <i style={{ width: share(confirmed), background: "var(--green)" }} />
      <i style={{ width: share(rejected), background: "var(--red)" }} />
      <i style={{ width: share(unsure), background: "var(--orange)" }} />
    </div>
  );
}
