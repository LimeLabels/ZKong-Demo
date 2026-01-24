import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import styles from './success.module.css';

export default function SquareOnboardingSuccess() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);
  const [syncStatus, setSyncStatus] = useState<'pending' | 'syncing' | 'complete' | 'failed'>('pending');
  const [syncStats, setSyncStats] = useState<{
    total_products: number;
    queued_for_sync: number;
    total_items?: number;
    products_created?: number;
    products_updated?: number;
    errors?: number;
  } | null>(null);

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

  // Poll sync status
  useEffect(() => {
    if (!merchantId || !router.isReady) return;

    let intervalId: NodeJS.Timeout | null = null;
    let isMounted = true;

    const checkSyncStatus = async () => {
      if (!isMounted) return;

      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
        const response = await fetch(
          `${backendUrl}/api/auth/square/sync-status?merchant_id=${merchantId}`
        );
        
        if (response.ok && isMounted) {
          const data = await response.json();
          setSyncStatus(data.status || 'pending');
          if (data.stats) {
            setSyncStats(data.stats);
          }
          
          // Stop polling if sync is complete or failed
          if ((data.status === 'complete' || data.status === 'failed') && intervalId) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }
      } catch (error) {
        console.error('Failed to check sync status', error);
      }
    };

    // Check immediately
    checkSyncStatus();

    // Poll every 5 seconds
    intervalId = setInterval(() => {
      checkSyncStatus();
    }, 5000);

    return () => {
      isMounted = false;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [merchantId, router.isReady]);

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

        {/* Sync Status */}
        {syncStatus !== 'pending' && (
          <div className={styles.syncStatus}>
            <h3 className={styles.syncTitle}>Product Sync Status</h3>
            {syncStatus === 'syncing' && (
              <div className={styles.syncing}>
                <div className={styles.spinner}></div>
                <p>Syncing products from Square...</p>
                {syncStats && (
                  <p className={styles.syncDetails}>
                    {syncStats.total_products} products found
                    {syncStats.queued_for_sync > 0 && ` • ${syncStats.queued_for_sync} queued for sync`}
                  </p>
                )}
              </div>
            )}
            {syncStatus === 'complete' && syncStats && (
              <div className={styles.complete}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ marginRight: '8px' }}>
                  <circle cx="12" cy="12" r="12" fill="#10B981" />
                  <path d="M8 12L11 15L16 9" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div>
                  <p className={styles.syncComplete}>Sync completed successfully!</p>
                  <p className={styles.syncDetails}>
                    {syncStats.products_created || syncStats.total_products} products synced
                    {syncStats.errors && syncStats.errors > 0 && ` • ${syncStats.errors} errors`}
                  </p>
                </div>
              </div>
            )}
            {syncStatus === 'failed' && (
              <div className={styles.failed}>
                <p>Sync encountered an error. Products may still be syncing in the background.</p>
              </div>
            )}
          </div>
        )}

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
            onClick={() => {
              // Use production by default, or sandbox if NEXT_PUBLIC_SQUARE_ENVIRONMENT is set to 'sandbox'
              const squareEnv = process.env.NEXT_PUBLIC_SQUARE_ENVIRONMENT || 'production';
              const dashboardUrl = squareEnv === 'sandbox' 
                ? 'https://squareupsandbox.com/dashboard'
                : 'https://squareup.com/dashboard';
              window.location.href = dashboardUrl;
            }}
          >
            Open Square Dashboard
          </button>

          <button
            className={styles.buttonSecondary}
            onClick={() => (window.location.href = process.env.NEXT_PUBLIC_ESL_DASHBOARD_LINK || '/dashboard')}
          >
            Go to ESL Dashboard
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
