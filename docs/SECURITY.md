# Security

YouCommander is a single-user local tool. It binds to `127.0.0.1` and has no authentication; do not expose it to a network.

Report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab) rather than a public issue.

Areas of interest: path handling in the import and audio endpoints, SQL construction, and anything that could send data off the machine.
