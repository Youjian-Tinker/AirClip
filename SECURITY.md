# Security Policy

AirClip moves clipboard text between trusted Windows machines through a BLE
relay. Clipboard data can contain secrets, so treat every deployment as a
trusted local setup rather than an internet-facing service.

## Supported Versions

The project is currently pre-1.0. Security fixes are made on the default branch.

## Reporting a Vulnerability

Do not open public issues for vulnerabilities that expose clipboard data,
credentials, or private network details. Report privately to the repository
owner, including:

- affected component: desktop agent, firmware, installer, or protocol;
- reproduction steps;
- expected and actual behavior;
- whether clipboard data can be read, modified, replayed, or persisted.

## Deployment Notes

- Pair and run AirClip only on machines and ESP32 hardware you control.
- Avoid syncing password manager values, private keys, session cookies, and
  production credentials.
- The desktop agent keeps only local clipboard history. Review installation
  paths and startup shortcuts before deploying in managed environments.
