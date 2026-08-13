# Security Policy

## Supported Versions

Only the latest release on the `main` branch receives security updates.

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please **do not** open a public issue.

**Report responsibly:**
1. **Email:** [sean.balbale@astrapheai.com](mailto:sean.balbale@astrapheai.com)
2. Include a description of the vulnerability and steps to reproduce.
3. Include the potential impact and severity.
4. Allow 72 hours for an initial response.

**What to expect:**
- We will acknowledge receipt within 48 hours.
- We will provide an estimated timeline for a fix (usually 2–4 weeks).
- We will credit reporters who disclose responsibly (unless they prefer anonymity).
- We will notify reporters when the vulnerability is patched.

## Scope

The following are in scope for security reports:
- Backend API endpoints (authentication, authorization, data access)
- Database schema and RLS policies
- Mobile app data handling and storage
- CI/CD pipeline and secret management

## Known Security Measures

- All database tables with user data enforce PostgreSQL Row Level Security (RLS).
- Authentication uses Supabase Auth with access token validation on every protected route.
- API rate limiting is enforced per-IP and per-athlete via Redis (or process-local fallback).
- Debug/admin endpoints are disabled in production.
- Secrets are managed via environment variables or cloud secret managers.
- Security headers (CSP, HSTS, X-Frame-Options, etc.) are applied to all responses.

## What to Avoid

- Do not attempt to test against the production environment.
- Do not share or exploit discovered vulnerabilities publicly before a patch is released.
- Do not scan or probe third-party API endpoints (Strava, WHOOP, Garmin) beyond normal usage.

## Disclosure Policy

We follow a 90-day coordinated disclosure timeline. If the reporter does not respond within 30 days of our initial notification, we may publicly disclose the vulnerability with credit to the reporter.
