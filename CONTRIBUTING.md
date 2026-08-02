# Contributing

[English](CONTRIBUTING.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/CONTRIBUTING.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/CONTRIBUTING.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/CONTRIBUTING.md)

Contributions must preserve deterministic, local-first, least-privilege defaults.

## Documentation localization

Every change to a human-facing document must update the corresponding English,
Korean, Japanese, and Simplified Chinese documents in the same change. Run
`python3 scripts/validate_documentation.py` before submitting. Translations of
privacy, terms, trademark, notice, and third-party-notice material are
informational and must retain the shared English-authoritative marker. Do not
translate or replace `LICENSE` or vendored dependency license texts.

Before proposing a change:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

## Version and release record

Every tracked release change requires a new semantic version and a dated
`CHANGELOG.md` entry. Use a patch version by default; use a minor or major
version when the change expands capabilities or breaks compatibility.
CI compares pull requests with their base branch and main-branch pushes with
their previous revision; tracked changes fail unless the manifest version is
greater than that baseline and the new changelog entry is first.

Before publishing a release:

1. Synchronize the version in the plugin manifest, runtime constants, SBOM,
   evaluation metadata, release validators, CI artifact paths, tests, and
   current-version documentation.
2. Run the full test suite and package validator on the final source state.
3. Rebuild and validate both deterministic release profiles twice and confirm
   that their bytes and checksums match.
4. Refresh the registered self-ontology from the final committed source state,
   and append declared version-policy and validated release-evidence events to
   its lineage.
5. Create the release tag only after the final commit and required CI checks
   are complete. Never move or replace a published release tag.

Use only synthetic fixtures. Do not commit private repositories, third-party
source excerpts, credentials, real-project ontology artifacts, model weights,
or copied proprietary schemas.

Changes that add network access, target execution, package installation,
authentication, telemetry, persistent services, hooks, write-capable MCP,
external databases, or automatic model downloads require a separate design and
updated privacy, security, threat-model, tests, SBOM, and submission review.

By contributing, you represent that you have the right to license the work
under Apache-2.0.
