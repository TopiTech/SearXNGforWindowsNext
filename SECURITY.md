# Security Policy & Deployment Guidelines

This document outlines security considerations and best practices for deploying SearXNG for Windows.

---

## Current Security Profile

### ✅ Built-In Protections

**SSRF (Server-Side Request Forgery) Prevention** in `/scrape` endpoint:
- Strict URL scheme validation (HTTP/HTTPS only)
- IP address classification via `ipaddress` library
- Blocks all loopback addresses (127.0.0.0/8)
- Blocks all private/reserved ranges (RFC 1918, link-local, etc.)
- Rejects `file://` and other non-web schemes
- Returns HTTP 400 for blocked requests

**Content Sanitization** in extracted HTML:
- `trafilatura.extract()` removes scripts, style tags, comments
- No injection vector through /scrape responses (plain text only)
- Error messages truncated to 100 chars (no stack traces)

**Localhost-Only Binding** (by design):
- Server listens on `127.0.0.1:8888` (not `0.0.0.0`)
- No network exposure without explicit forwarding
- Safe from external MITM attacks

### ⚠️ Known Limitations

| Risk | Severity | Mitigation | Notes |
|------|----------|-----------|-------|
| **No Authentication** | MEDIUM | Add reverse proxy with auth (OAuth2, OIDC, Basic Auth) | All endpoints publicly accessible on localhost |
| **No Rate Limiting** | MEDIUM | Implement nginx/HAProxy rate limiting | Upstream engines have their own limits |
| **No TLS/HTTPS** | LOW | Add reverse proxy with TLS | Safe for localhost; needed for network exposure |
| **SSL verification** | LOW | Env `SEARXNG_SCRAPE_VERIFY_SSL` (default `true`) — set `false` only for localhost without CA | httpx verifies certs by default, trafilatura primary |
| **No CORS Controls** | MEDIUM | Configure CORS headers in reverse proxy | Not an issue for localhost use |
| **User-Agent Spoofing** | LOW | Legitimate UX enhancement (documented) | Used to bypass bot-detection, not malware |

---

## Secure Deployment Scenarios

### Scenario 1: Personal/Localhost Use ✅ **SAFE AS-IS**

```
┌─────────────────┐
│ Your Computer   │
│ • 127.0.0.1:8888│  ← SearXNG (localhost only, no network exposure)
│ • Browser       │
└─────────────────┘
```

**Requirements:**  
None. Run `SearXNG for Windows.bat` directly.

**Risks:**  
Minimal (only local user can access).

---

### Scenario 2: Local Network Access ⚠️ **REQUIRES HARDENING**

```
┌──────────────┐         ┌─────────────────┐
│ Other Machine│ 192.168 │ Your Computer   │
│ (trusted LAN)│◄────────┤ • nginx (reverse proxy with auth/TLS)
│              │         │ • 127.0.0.1:8888 (localhost SearXNG)
└──────────────┘         └─────────────────┘
```

**Requirements:**
1. **Reverse Proxy** (nginx/HAProxy) for authentication + TLS
2. **Rate Limiting** to prevent DoS
3. **HTTPS Certificate** (self-signed OK for internal networks)

**Example nginx Config:**
```nginx
upstream searxng {
    server 127.0.0.1:8888;
}

server {
    listen 8443 ssl;
    ssl_certificate /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;
    
    # Require HTTP Basic Auth (user:password)
    auth_basic "SearXNG";
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    # Rate limiting (10 req/sec for /search, 2 req/sec for /scrape)
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=scrape:10m rate=2r/s;
    
    location / {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://searxng;
    }
    
    location /scrape {
        limit_req zone=scrape burst=5 nodelay;
        proxy_pass http://searxng;
    }
}
```

**Setup Steps:**
```bash
# 1. Create htpasswd file
htpasswd -c /etc/nginx/.htpasswd username

# 2. Generate self-signed cert (7-year expiry)
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem \
    -days 2555 -nodes -subj "/CN=searxng.local"

# 3. Reload nginx
nginx -s reload
```

**Access:** `https://searxng.local:8443` (auth required)

---

### Scenario 3: Internet-Facing Deployment ⛔ **REQUIRES FULL SECURITY STACK**

```
┌─────────────────┐      ┌──────────────────┐       ┌─────────────┐
│ Internet Users  │◄─────┤ Reverse Proxy    │◄─────┤ SearXNG     │
│ (untrusted)     │ HTTPS │ (auth, TLS, DDoS│ TLS   │ (localhost) │
└─────────────────┘      │ protection)      │       └─────────────┘
                         └──────────────────┘
```

**Requirements:**
1. ✅ **TLS Certificate** (valid CA, auto-renewal via Let's Encrypt)
2. ✅ **Authentication** (OAuth2, OIDC, SAML)
3. ✅ **Rate Limiting** (aggressive for /scrape)
4. ✅ **DDoS Protection** (Cloudflare, Akamai, or WAF rules)
5. ✅ **Web Application Firewall** (blocked patterns, SQL injection, XSS)
6. ✅ **Logging & Monitoring** (fail2ban, Prometheus, ELK stack)
7. ✅ **Content Security Policy** (CSP headers)

**Example Production nginx Config:**
```nginx
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=1r/s;
limit_req_zone $binary_remote_addr zone=scrape:10m rate=0.2r/s;
limit_conn_zone $binary_remote_addr zone=addr:10m;

upstream searxng {
    server 127.0.0.1:8888;
    keepalive 32;
}

server {
    listen 80;
    server_name searxng.example.com;
    return 301 https://$server_name$request_uri;  # Redirect HTTP → HTTPS
}

server {
    listen 443 ssl http2;
    server_name searxng.example.com;
    
    # TLS Configuration
    ssl_certificate /etc/letsencrypt/live/searxng.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/searxng.example.com/privkey.pem;
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_stapling on;
    ssl_stapling_verify on;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'" always;
    
    # OAuth2 authentication (using oauth2-proxy or similar)
    auth_request /oauth2/auth;
    error_page 401 = /oauth2/sign_in;
    
    # Rate limiting
    limit_req zone=api burst=10 nodelay;
    limit_conn addr 10;
    
    # Request size limits
    client_max_body_size 1m;
    proxy_read_timeout 30s;
    
    location / {
        limit_req zone=api burst=10;
        proxy_pass http://searxng;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /scrape {
        limit_req zone=scrape burst=3;
        proxy_pass http://searxng;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    
    location /oauth2/ {
        proxy_pass http://oauth2-proxy:4180;
    }
    
    # Deny access to sensitive paths
    location ~ /\.well-known/ {
        allow all;
    }
    
    location ~ /\. {
        deny all;
    }
}
```

**Installation:** Use cloud-native solutions:
- **Cloud Provider:** AWS ELB/ALB, Google Cloud Load Balancer, Azure App Gateway
- **Container:** Docker + Kubernetes with Ingress (TLS, auth, rate limiting)
- **Shared Hosting:** Cloudflare reverse proxy + authentication

---

## Incident Response

### If /scrape Endpoint Is Abused

**Symptom:** Spike in 4XX errors or /scrape requests

**Response:**
1. **Immediate:** Disable /scrape endpoint in nginx config:
   ```nginx
   location /scrape {
       return 403 "Endpoint temporarily disabled";
   }
   ```
2. **Investigate:** Check logs for attack pattern
3. **Mitigate:** Tighten rate limits for that IP
4. **Long-term:** Add IP reputation checks (Abuseipdb, etc.)

### If Upstream Patch Fails

**Symptom:** `apply-windows-patches.ps1` returns ERROR

**Response:**
1. **Check:** UPSTREAM_VERSION.txt for commit hash
2. **Review:** Upstream code for structural changes
3. **Update:** Regex anchors in apply-windows-patches.ps1
4. **Test:** Run smoke-test.ps1 to verify patches work

### If Requirements.txt Conflicts

**Symptom:** `install-requirements.ps1` fails with version conflict

**Response:**
1. **Check:** Required version constraints
2. **Decide:** Pin old version or adopt new version
3. **Update:** config/requirements.txt
4. **Test:** Run smoke-test.ps1

---

## Compliance & Audit

### Data Privacy

- **No user authentication built-in** → SearXNG doesn't track users by default
- **Search queries visible to upstream engines** → See `config/settings.yml` for engine selection
- **No logging by default** → Add logging middleware if required for compliance

### Regulatory Compliance

| Regulation | Requirement | Implementation |
|-----------|-------------|-----------------|
| **GDPR** | Data deletion, consent, privacy policy | Configure privacy settings in settings.yml |
| **HIPAA** | Encryption at rest/transit, access controls | Add TLS + reverse proxy auth |
| **SOC 2** | Logging, monitoring, incident response | Add ELK, audit trails |
| **PCI DSS** | Network segmentation, TLS, monitoring | Isolate from payment systems |

---

## Checklist: Before Production Deployment

- [ ] Reverse proxy deployed (nginx/HAProxy)
- [ ] TLS certificate installed (valid CA, not self-signed)
- [ ] Authentication layer active (OAuth2, OIDC, etc.)
- [ ] Rate limiting configured (/search, /scrape)
- [ ] Web Application Firewall (WAF) rules applied
- [ ] Logging & monitoring enabled (Prometheus, ELK, Splunk)
- [ ] Firewall rules restrict access (whitelist IPs if possible)
- [ ] Security headers configured (CSP, HSTS, etc.)
- [ ] Smoke tests pass (./tools/smoke-test.ps1)
- [ ] Incident response plan documented
- [ ] Backup & disaster recovery tested
- [ ] Security audit completed

---

## Resources

- **SSRF Prevention:** https://owasp.org/www-community/attacks/Server-Side_Request_Forgery
- **Rate Limiting:** https://nginx.org/docs/http/ngx_http_limit_req_module.html
- **TLS Best Practices:** https://ssl-config.mozilla.org/
- **OAuth2 Proxy:** https://github.com/oauth2-proxy/oauth2-proxy
- **OWASP Top 10:** https://owasp.org/www-project-top-ten/

---

**Last Updated:** 2026-05-02  
**Questions?** See DEVELOPMENT.md for architecture details
