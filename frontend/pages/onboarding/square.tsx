import { useState } from 'react';
import styles from './square.module.css';

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

export default function SquareOnboarding() {
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

    // Build backend OAuth URL
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    const params = new URLSearchParams({
      hipoink_store_code: hipoinkStoreCode.trim(),
      timezone: timezone,
    });

    if (storeName.trim()) {
      params.append('store_name', storeName.trim());
    }

    // Redirect to backend OAuth endpoint
    window.location.href = `${backendUrl}/auth/square?${params.toString()}`;
  };

  return (
    <div className={styles.onboarding}>
      <div className={styles.container}>
        {/* Square Logo */}
        <div className={styles.logo}>
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <rect width="40" height="40" rx="4" fill="#000000" />
            <path d="M12 12H28V28H12V12Z" fill="white" />
          </svg>
        </div>

        {/* Header */}
        <h1 className={styles.title}>Connect to Square</h1>
        <p className={styles.subtitle}>
          Connect your Square account to sync products and pricing with your ESL system
        </p>

        {/* Form */}
        <form onSubmit={handleSubmit} className={styles.form}>
          {/* Hipoink Store Code */}
          <div className={styles.formGroup}>
            <label htmlFor="hipoinkStoreCode" className={styles.label}>
              Store Code <span className={styles.required}>*</span>
            </label>
            <input
              id="hipoinkStoreCode"
              type="text"
              className={`${styles.input} ${errors.hipoinkStoreCode ? styles.error : ''}`}
              value={hipoinkStoreCode}
              onChange={(e) => setHipoinkStoreCode(e.target.value)}
              placeholder="e.g., 001"
              disabled={isSubmitting}
            />
            {errors.hipoinkStoreCode && (
              <span className={styles.errorText}>{errors.hipoinkStoreCode}</span>
            )}
            <span className={styles.helpText}>
              Your unique store identifier for the ESL system
            </span>
          </div>

          {/* Store Name (Optional) */}
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

          {/* Timezone */}
          <div className={styles.formGroup}>
            <label htmlFor="timezone" className={styles.label}>
              Timezone <span className={styles.required}>*</span>
            </label>
            <select
              id="timezone"
              className={`${styles.select} ${errors.timezone ? styles.error : ''}`}
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

          {/* Submit Button - Square Style */}
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
              <>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" style={{ marginRight: '8px' }}>
                  <rect width="20" height="20" rx="2" fill="white" />
                </svg>
                Connect to Square
              </>
            )}
          </button>

          {/* Privacy Notice */}
          <p className={styles.privacyNotice}>
            By connecting, you authorize this application to access your Square account data.
            You can revoke access at any time from your Square Dashboard.
          </p>
        </form>
      </div>
    </div>
  );
}
