# Browser wallet hosting security headers

Status: deployment requirements for the static prototype; not evidence that a production wallet is ready.

The current `web-wallet/index.html` contains no JavaScript, images, network calls, or external resources. It now includes a restrictive meta Content Security Policy and a `no-referrer` policy. These controls reduce the prototype's browser capabilities; they do not make the page a secure wallet.

## Required HTTP response headers

The hosting layer should send these headers on every wallet response (including error responses):

```http
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Cross-Origin-Opener-Policy: same-origin
Strict-Transport-Security: max-age=31536000
```

The CSP above is a template for a future same-origin bundled application, not a policy to copy blindly into the current static page. The current page uses an inline style block and an inline color style, so its meta policy allows inline styles. Before adding scripts or a build pipeline, remove inline styles, serve only locally bundled assets, and tighten the HTTP CSP. Do not add `unsafe-eval), wildcard sources, runtime CDNs, or third-party analytics.

Only enable HSTS after the domain is permanently HTTPS-capable and all relevant subdomains are confirmed HTTPS-ready. Consider `includeSubDomains` only after validating every subdomain. Do not enable `preload` casually.

## Hosting and deployment checks

- Serve the wallet only over HTTPS; never ask users to open it from an untrusted mirror.
- Set `frame-ancestors 'none'` in the HTTP CSP; this directive is not enforced when delivered through a meta element.
- Ensure the hosting provider does not inject analytics, advertising, remote scripts, or third-party widgets.
- Do not expose API endpoints or connect permissions until a node API and its authentication/origin model have been reviewed.
- Verify actual response headers from the deployed origin; repository files alone cannot prove hosting configuration.
- Re-test CSP after every frontend change and inspect the built artifact for unexpected external URLs.

## Explicit limitation

These headers do not provide key custody, cryptographic correctness, a secure backup, a trusted node, consensus correctness, or transaction safety. The page remains a non-functional prototype. No private key, seed phrase, password, or real funds should be entered.
