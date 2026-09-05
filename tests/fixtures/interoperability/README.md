# Interoperability fixtures

These files are independently authored synthetic examples. The repeated `a`
revision is invented test data, not a source commit or a production attestation.
No repository bodies, user decisions, credentials or real conversations are used.

`code-reference-source.json` exercises native Code export, unresolved external
references, privacy exclusions, immutable locators and Context reference handoff.
`contracts-code-reference-draft.json` exercises only the Contracts
`0.1.0-draft.1` code-reference profile with a complete synthetic source-located
subset. It is not a projection of an unverified real snapshot.

The optional external consumer tests load explicitly selected development
sources, do not modify those sources, and use temporary synthetic Context storage.
They distinguish `not_checked` external truth/authorization from schema validity.
Native Code import, full graph round trips and ChatGPT host authorization are
outside these tests.
