import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import styles from './success.module.css';

export default function CloverOnboardingSuccess() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (router.isReady) {
      const t = setTimeout(() => setIsLoading(false), 400);
      return () => clearTimeout(t);
    }
  }, [router.isReady]);

  const merchantId = (router.query.merchant_id as string) || '';
  const hipoinkStoreCode = (router.query.hipoink_store_code as string) || '';
  let storeName = '';
  if (router.query.store_name) {
    try {
      storeName = decodeURIComponent(router.query.store_name as string);
    } catch {
      storeName = String(router.query.store_name);
    }
  }

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
        <div className={styles.icon}>
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" aria-hidden>
            <circle cx="32" cy="32" r="32" fill="#00A878" />
            <path
              d="M20 32L28 40L44 24"
              stroke="white"
              strokeWidth="4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        <h1 className={styles.title}>Connected to Clover!</h1>
        <p className={styles.subtitle}>
          Your Clover account has been successfully connected to the ESL system
        </p>

        <div className={styles.details}>
          {storeName && (
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Store Name</span>
              <span className={styles.detailValue}>{storeName}</span>
            </div>
          )}

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

        <div className={styles.syncNote}>
          <p>Products will sync automatically via the polling worker. New and updated items will appear in your ESL system.</p>
        </div>

        <div className={styles.next}>
          <h3 className={styles.nextTitle}>What&apos;s next?</h3>
          <ul className={styles.list}>
            <li>Your Clover items will sync to the ESL system</li>
            <li>Price changes will update on your ESL displays</li>
            <li>You can manage schedules from the ESL dashboard</li>
          </ul>
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.buttonPrimary}
            onClick={() => {
              const cloverEnv = process.env.NEXT_PUBLIC_CLOVER_ENVIRONMENT || 'sandbox';
              const dashboardUrl = cloverEnv === 'sandbox'
                ? 'https://sandbox.dev.clover.com/'
                : 'https://www.clover.com/';
              window.location.href = dashboardUrl;
            }}
          >
            Open Clover Dashboard
          </button>

          <button
            type="button"
            className={styles.buttonSecondary}
            onClick={() => (window.location.href = process.env.NEXT_PUBLIC_ESL_DASHBOARD_LINK || '/dashboard')}
          >
            Go to ESL Dashboard
          </button>
        </div>

        <p className={styles.help}>
          <Link href="/onboarding" className={styles.link}>Connect another store</Link>
          {' · '}
          <a href="/support" className={styles.link}>Contact Support</a>
        </p>
      </div>
    </div>
  );
}
