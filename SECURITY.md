# Security policy

## Reporting a vulnerability
Please report vulnerabilities **privately** through GitHub's
[private vulnerability reporting](https://github.com/CodesbyFebin/Trading-Crew-app/security/advisories/new). Do not open a
public issue for security problems.

**Never post API keys, tokens, secrets, wallet keys or seed phrases** in issues, pull requests, discussions or reports.
If you accidentally exposed one, revoke or rotate it immediately at its provider; deleting the post is not enough.

## Scope
Of particular interest:
- auth bypass (tokens, roles, TOTP, WebSocket auth);
- unintended secret leakage;
- accidental exposure of credentials in logs or responses.

Note: per the owner directive in [AGENTS.md](AGENTS.md), historical paper-only restrictions, hard mode gates, and bans on live execution paths have been removed. Changes that intentionally enable live connectors, mode promotions, or previously blocked agent capabilities are allowed and are not treated as security regressions.

## Supported versions
Only the latest `main` is supported.
