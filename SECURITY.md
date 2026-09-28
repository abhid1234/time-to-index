# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

Fixes are made against `main` and released from the current minor line.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open
a public issue that contains exploit details, API keys, or provider payloads
you have not checked for personal data.

Please include the affected version or commit, the smallest safe
reproduction, the expected impact, and any suggested mitigation. Maintainers
will acknowledge a usable report, assess severity, and coordinate disclosure
after a fix is available.

## Security boundary

Time to Index calls third-party search APIs with keys you supply and stores
what they return. Keep keys in `.env` (ignored by git) or in repository
secrets for the scheduled workflows; never commit them, and never paste them
into issues, logs or pull requests. If a key is exposed, rotate it with the
provider first and report second.

The committed ledger contains provider responses to public questions about
public releases. Before you fork the project to probe other sources, check
that what you store and publish is yours to publish.
