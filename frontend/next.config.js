/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000',
    NEXT_PUBLIC_ESL_DASHBOARD_LINK: process.env.NEXT_PUBLIC_ESL_DASHBOARD_LINK || 'http://208.167.248.129/',
  },
}

module.exports = nextConfig
