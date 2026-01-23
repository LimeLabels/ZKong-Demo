import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import styles from './success.module.css';

export default function SquareOnboardingSuccess() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);

  // Wait for router to be ready before showing content
  useEffect(() => {
    if (router.isReady) {
      setTimeout(() => setIsLoading(false), 500);
    }
  }, [router.isReady]);

  const merchantId = (router.query.merchant_id as string) || '';
  const hipoinkStoreCode = (router.query.hipoink_store_code as string) || '';
  const locationName = router.query.location_name
    ? decodeURIComponent(router.query.location_name as string)
    : 'Unknown';

  if (isLoading || !router.isReady) {
    return (
      <div className={styles.success}>
        <div className={styles.container}>
          <div className={styles.loadingSpinner}></div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.success}>
      <div className={styles.container}>
        {/* Success Icon */}
        <div className={styles.icon}>
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="32" r="32" fill="#000000" />
            <path
              d="M20 32L28 40L44 24"
              stroke="white"
              strokeWidth="4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        {/* Success Message */}
        <h1 className={styles.title}>Connected to Square!</h1>
        <p className={styles.subtitle}>
          Your Square account has been successfully connected to the ESL system
        </p>

        {/* Connection Details */}
        <div className={styles.details}>
          <div className={styles.detailItem}>
            <span className={styles.detailLabel}>Location</span>
            <span className={styles.detailValue}>{locationName}</span>
          </div>

          <div className={styles.detailItem}>
            <span className={styles.detailLabel}>Store Code</span>
            <span className={styles.detailValue}>
              {hipoinkStoreCode === 'none' ? 'Not set' : hipoinkStoreCode}
            </span>
          </div>

          {merchantId && (
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Merchant ID</span>
              <span className={`${styles.detailValue} ${styles.detailMono}`}>{merchantId}</span>
            </div>
          )}
        </div>

        {/* What's Next */}
        <div className={styles.next}>
          <h3 className={styles.nextTitle}>What&apos;s next?</h3>
          <ul className={styles.list}>
            <li>Your products will automatically sync from Square</li>
            <li>Price changes will update on your ESL displays</li>
            <li>Inventory levels will stay in sync</li>
          </ul>
        </div>

        {/* Action Buttons */}
        <div className={styles.actions}>
          <button
            className={styles.buttonPrimary}
            onClick={() => (window.location.href = process.env.NEXT_PUBLIC_ESL_DASHBOARD_LINK || '/dashboard')}
          >
            Go to ESL Dashboard
          </button>

          <button
            className={styles.buttonSecondary}
            onClick={() => (window.location.href = 'https://squareupsandbox.com/dashboard')}
          >
            Open Square Dashboard
          </button>
        </div>

        {/* Help Text */}
        <p className={styles.help}>
          Need help? <a href="/support" className={styles.link}>Contact Support</a>
        </p>
      </div>
    </div>
  );
}
