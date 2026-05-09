# Branch Protection Setup (GitHub)

Repository: khalid20210/mohassaba
Branch: master

Use GitHub Settings UI:
1. Open repository settings.
2. Navigate to Branches.
3. Add a branch protection rule for master.
4. Enable:
   - Require a pull request before merging.
   - Require approvals (minimum 1).
   - Require status checks to pass before merging.
   - Do not allow bypassing for admins (recommended).
5. Select required checks:
   - Python package
   - Test Report
   - Security Gates
   - CodeQL / Analyze (Python)

Optional hardening:
- Require signed commits.
- Require linear history.
- Restrict force pushes and branch deletions.

CLI alternative (if gh auth is available):
- gh api --method PUT repos/khalid20210/mohassaba/branches/master/protection ...

Note:
This repository-side config cannot be fully enforced from local code edits alone without GitHub admin permissions.
