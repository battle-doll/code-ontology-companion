# Contributing

Contributions must preserve deterministic, local-first, least-privilege defaults.

Before proposing a change:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

Use only synthetic fixtures. Do not commit private repositories, third-party
source excerpts, credentials, real-project ontology artifacts, model weights,
or copied proprietary schemas.

Changes that add network access, target execution, package installation,
authentication, telemetry, persistent services, hooks, write-capable MCP,
external databases, or automatic model downloads require a separate design and
updated privacy, security, threat-model, tests, SBOM, and submission review.

By contributing, you represent that you have the right to license the work
under Apache-2.0.
