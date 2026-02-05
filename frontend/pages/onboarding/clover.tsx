import { useState } from 'react';
import Link from 'next/link';
import styles from './clover.module.css';

const COMMON_TIMEZONES = [
  { value: 'America/New_York', label: 'Eastern Time (US & Canada)' },
  { value: 'America/Chicago', label: 'Central Time (US & Canada)' },
  { value: 'America/Denver', label: 'Mountain Time (US & Canada)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (US & Canada)' },
  { value: 'America/Anchorage', label: 'Alaska' },
  { value: 'Pacific/Honolulu', label: 'Hawaii' },
  { value: 'America/Phoenix', label: 'Arizona' },
  { value: 'Europe/London', label: 'London' },
  { value: 'Europe/Paris', label: 'Paris' },
  { value: 'Asia/Tokyo', label: 'Tokyo' },
  { value: 'Australia/Sydney', label: 'Sydney' },
  { value: 'UTC', label: 'UTC' },
];

export default function CloverOnboarding() {
  const [hipoinkStoreCode, setHipoinkStoreCode] = useState('');
  const [storeName, setStoreName] = useState('');
  const [timezone, setTimezone] = useState('America/New_York');
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validateForm = () => {
    const newErrors: { [key: string]: string } = {};

    if (!hipoinkStoreCode.trim()) {
      newErrors.hipoinkStoreCode = 'Store code is required';
    } else if (!/^[A-Za-z0-9_-]+$/.test(hipoinkStoreCode.trim())) {
      newErrors.hipoinkStoreCode = 'Only letters, numbers, hyphens, and underscores allowed';
    }

    if (!timezone) {
      newErrors.timezone = 'Please select a timezone';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);

    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    const params = new URLSearchParams({
      hipoink_store_code: hipoinkStoreCode.trim(),
      timezone: timezone,
    });

    if (storeName.trim()) {
      params.append('store_name', storeName.trim());
    }

    window.location.href = `${backendUrl}/auth/clover?${params.toString()}`;
  };

  return (
    <div className={styles.onboarding}>
      <div className={styles.container}>
        <div className={styles.back}>
          <Link href="/onboarding">← Choose another POS</Link>
        </div>

        <div className={styles.logo}>
          <svg width="40" height="40" viewBox="0 0 48 48" fill="none" aria-hidden>
            <rect width="48" height="48" rx="8" fill="#00A878" />
            <path
              d="M24 14c-5.52 0-10 4.48-10 10s4.48 10 10 10 10-4.48 10-10-4.48-10-10-10zm0 17c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"
              fill="white"
            />
          </svg>
        </div>

        <h1 className={styles.title}>Connect to Clover</h1>
        <p className={styles.subtitle}>
          Connect your Clover account to sync products and pricing with your ESL system
        </p>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.formGroup}>
            <label htmlFor="hipoinkStoreCode" className={styles.label}>
              Store Code <span className={styles.required}>*</span>
            </label>
            <input
              id="hipoinkStoreCode"
              type="text"
              className={`${styles.input} ${errors.hipoinkStoreCode ? styles.inputError : ''}`}
              value={hipoinkStoreCode}
              onChange={(e) => setHipoinkStoreCode(e.target.value)}
              placeholder="e.g., ST-7842"
              disabled={isSubmitting}
            />
            {errors.hipoinkStoreCode && (
              <span className={styles.errorText}>{errors.hipoinkStoreCode}</span>
            )}
            <span className={styles.helpText}>
              Your unique store identifier for the ESL system
            </span>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="storeName" className={styles.label}>
              Store Name <span className={styles.optional}>(optional)</span>
            </label>
            <input
              id="storeName"
              type="text"
              className={styles.input}
              value={storeName}
              onChange={(e) => setStoreName(e.target.value)}
              placeholder="e.g., Downtown Location"
              disabled={isSubmitting}
            />
            <span className={styles.helpText}>
              A friendly name to identify this location
            </span>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="timezone" className={styles.label}>
              Timezone <span className={styles.required}>*</span>
            </label>
            <select
              id="timezone"
              className={`${styles.select} ${errors.timezone ? styles.inputError : ''}`}
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              disabled={isSubmitting}
            >
              {COMMON_TIMEZONES.map((tz) => (
                <option key={tz.value} value={tz.value}>
                  {tz.label}
                </option>
              ))}
            </select>
            {errors.timezone && (
              <span className={styles.errorText}>{errors.timezone}</span>
            )}
            <span className={styles.helpText}>
              Used for scheduling price changes
            </span>
          </div>

          <button
            type="submit"
            className={styles.button}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className={styles.spinner}></span>
                Connecting...
              </>
            ) : (
              'Connect to Clover'
            )}
          </button>

          <p className={styles.privacyNotice}>
            By connecting, you authorize this application to access your Clover account data.
            You can revoke access at any time from your Clover Dashboard.
          </p>
        </form>
      </div>
    </div>
  );
}
