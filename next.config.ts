import type { NextConfig } from 'next';
const config: NextConfig = { async rewrites() { return [{source:'/api/v1/:path*',destination:`${process.env.API_URL || 'http://127.0.0.1:8010'}/api/v1/:path*`}]; } };
export default config;

