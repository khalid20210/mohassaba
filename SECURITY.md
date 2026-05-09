# Security Policy

## Supported Versions

The `master` branch is the only supported production branch.
Security fixes are applied to `master` first.

## Reporting a Vulnerability

Please do not open public issues for sensitive vulnerabilities.

Use one of the following secure channels:
- GitHub private security advisory (preferred)
- Direct email to repository owner

When reporting, include:
- Affected endpoint/module
- Reproduction steps
- Impact assessment
- Suggested remediation (if available)

## Response Targets

- Initial acknowledgement: within 24 hours
- Triage decision: within 72 hours
- Critical fix target: within 7 days
- High fix target: within 14 days

## Disclosure Policy

- Coordinated disclosure is required.
- Public disclosure is allowed only after fix release or explicit owner approval.

## Hard Requirements

- No direct commits to `master`
- Pull request + required checks must pass
- Signed commits required on protected branch
- Secret scanning and dependency audit must stay enabled
