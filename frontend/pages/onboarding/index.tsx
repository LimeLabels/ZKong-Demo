import Link from 'next/link';
import styles from './choose.module.css';

/**
 * Onboarding entry: choose POS provider (Square or Clover).
 * Square → /onboarding/square, Clover → /onboarding/clover.
 */
export default function OnboardingChooseProvider() {
  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <h1 className={styles.title}>Connect your POS</h1>
        <p className={styles.subtitle}>
          Choose your point-of-sale system to sync products and pricing with your ESL system
        </p>

        <div className={styles.cards}>
          <Link href="/onboarding/square" className={styles.card} data-provider="square">
            <div className={styles.cardLogo}>
              <svg width="48" height="48" viewBox="0 0 40 40" fill="none" aria-hidden>
                <rect width="40" height="40" rx="4" fill="#000000" />
                <path d="M12 12H28V28H12V12Z" fill="white" />
              </svg>
            </div>
            <h2 className={styles.cardTitle}>Square</h2>
            <p className={styles.cardDesc}>
              Connect your Square account to sync catalog and inventory
            </p>
            <span className={styles.cardCta}>Continue with Square →</span>
          </Link>

          <Link href="/onboarding/clover" className={styles.card} data-provider="clover">
            <div className={styles.cardLogo}>
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden>
                <rect width="48" height="48" rx="8" fill="#00A878" />
                <path
                  d="M24 14c-5.52 0-10 4.48-10 10s4.48 10 10 10 10-4.48 10-10-4.48-10-10-10zm0 17c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"
                  fill="white"
                />
              </svg>
            </div>
            <h2 className={styles.cardTitle}>Clover</h2>
            <p className={styles.cardDesc}>
              Connect your Clover account to sync items and pricing
            </p>
            <span className={styles.cardCta}>Continue with Clover →</span>
          </Link>
        </div>

        <p className={styles.footer}>
          You can connect one POS per store. Need help?{' '}
          <a href="/support" className={styles.link}>Contact Support</a>
        </p>
      </div>
    </div>
  );
}
