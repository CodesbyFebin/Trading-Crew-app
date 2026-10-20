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
- any path by which LLM output could influence orders, risk or modes;
- ways to change risk limits at runtime or mutate the append-only tables;
- ways to leave PAPER mode;
- secret leakage.

## Supported versions
Only the latest `main` is supported. This project is paper-only and contains no live trading code.
