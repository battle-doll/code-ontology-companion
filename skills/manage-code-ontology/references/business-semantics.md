# Business knowledge overlay

Developer: battle-doll. This optional local layer describes business knowledge over one sealed source snapshot. It preserves source records and the existing source map. It does not execute the target program, write back to an application, approve an operational action or establish whole-policy completeness.

A concept has a scoped namespace, domain, kind and immutable concept key. Equal labels are not equal identities. Directed relations retain their subject, predicate, object, role and explicit cardinality; missing cardinality is UNKNOWN. Properties distinguish declared scalar types, quantity, unit, currency and time. Numeric types and names do not establish a business unit.

Policies retain subject scope, eligibility, exclusions, inputs, formula, constants, units, rounding stage, outcome, priority, exclusivity, stackability, caps/floors, effective interval, clock/timezone, conflicts and missing context. Unprovided or unsupported facets remain UNKNOWN with their original reason. Transitions retain source and target state, trigger, guard, effect, order and exceptional outcome. These descriptions are static knowledge: execution is NOT_OBSERVED and execution authorization is NOT_PROVIDED.

Source support and business approval are separate axes. A candidate is not verified meaning. A declared interpretation is not an implemented rule. Effective approval requires the authorized local review operation and its immutable receipt, and applies only to the knowledge statement. It never grants execution authority, proves runtime behavior or authorizes public disclosure. Source/spec/review changes require revalidation; approvals do not transfer automatically.

## Pinned local reads

Business reads require the exact source and business snapshot/digest pins. Resolve evidence through the sealed ontology reader, including actual record digests and inline pointers. Queries do not reread raw source. Retain unsupported items, rejected requests, omissions and processing failures in their selected denominators. Mixed or stale pins reject the read rather than choosing a latest snapshot.

The internal reader exposes evidence. Its consumer must authorize `read_policy`; per-file paths, source hashes, locations, review content and actor details require `read_evidence` independently. A request-provided role or domain is not authority. A workspace is the access boundary; fine-grained enterprise segregation is not implied.

## Offline human view and export

The business view is a separate five-language lens beside the original source map. It lists every selected business record with pagination, original JSON, source pins, evidence/lineage, support and approval, directed relationships and policy facets. UNKNOWN facets remain visible. Browser text is escaped and inert. Navigation uses relative local links, native keyboard-accessible controls and a mobile layout; no external fonts, network requests or target-code execution are needed. Keep the whole exported directory together.

An export requires `export_html` or `export_bundle` plus **all three** of `read_structure`, `read_policy` and `read_evidence`. The trusted process supplies authorization, an ACL publication lock, a current-profile check and a stable-snapshot check. Access revision and pins are checked during streaming and again under the publication lock. A changed profile, permission, snapshot, failed privacy check, cancellation or budget violation prevents publication. Export errors carry bounded reason codes and selected/processed counts without echoing source or review content.

Exports create a new private directory and never replace an existing destination. Files are private, links/reparse points are rejected, and an integrity manifest hashes the emitted files. Original JSON is retained for every record, including unsupported content and coverage metadata that passed privacy checks. The caller must combine source and business output within the existing total 1 GiB limit; passing the remaining budget does not raise the 32 MiB page, 512 KiB record, reader or canonical JSON limits. Budget failure does not shrink the denominator or turn an unprocessed item into success.

An exported copy carries export-time access. Later ACL or knowledge revocation changes future reads and child overlays; it cannot remotely erase or revoke bytes already exported. Treat exports as private copies, not approved publication.

## RDF 1.1, provenance and mapping loss

The export emits full-IRI Turtle using the RDF 1.1 N-Triples subset, PROV entity/derivation/revision links and a declared SHACL record shape. Each record has an opaque URI derived from its exact ID. Direct business relation endpoints resolve to actual exported IDs where present. Every source anchor and complete record is retained as canonical JSON literals and as original `records/*.json`; `lineage.ttl` binds the source/business pins and prior business snapshot.

This is a limited explicit mapping. `mapping-loss.json` lists actual unmapped semantic fields for each record and its retained JSON/RDF paths. Complex facets, units, interval boundaries, aliases, structured relationship values, limitations and extension fields are preserved as data; their domain meaning is not silently asserted as RDF axioms, OWL equivalence or executable policies. No reasoning, SHACL validation or runtime truth is inferred from serialization. Shape validation and native-browser verification remain NOT_RUN until independently performed. A shape pass would validate only its declared constraints, not the truth or completeness of business meaning.

## Integration API

Load `business_export.py` through the verified bundled sibling loader and inject dependencies explicitly:

```python
business_export.configure(privacy_guard=guard, canonical=semantics.canonical)
result = business_export.export_business(
    reader, new_business_directory,
    pins=exact_business_pins, profile=private_profile,
    authorize=trusted_authorize,
    publication_guard=trusted_snapshot_acl_lock,
    check_profile=current_profile_unchanged,
    check_snapshot=pinned_reader_stable,
    export_action="export_html",  # or export_bundle
    max_output_bytes=remaining_source_and_business_budget,
    source_entries=None,
)
```

`reader.metadata` and `iter_records(page_size=100)` are the only knowledge inputs. All eight implementation-contract pins must exactly match metadata. `authorize(action)` returns the trusted allow decision and integer ACL revision. `publication_guard()` must use the same lock as ACL updates. Profile and stable-reader callbacks return `True` only after revalidation. The caller owns the reader context and must wait for its successful exit before publishing a containing source bundle.

Optional `source_entries` contains all five locales with the exact relative path `../../<locale>/index.html`, for a business child directory beside the source locale directories. Arbitrary paths or external URLs are rejected. The exporter returns selected/delivered counts, file hashes/bytes, mapping-loss path, pins and explicit unrun browser/shape statuses. Default source-only query schemas and the existing 3D source view remain separate.

## Optional explicit business contracts

property_type preserves precision/scale/rounding, unit, currency and time metadata. formula_mapping requires current source pins, actual rule digest, exact property IDs, parameter/return types and /program plus /returnType anchors; names never establish a mapping. policy_composition selects at most16 distinct members with explicit priority order/exclusivity/onConflict. Equal priorities are preserved as a partial order; no identity or array-order tiebreaker selects a member. Explicit first_applicable or at_most_one may omit stacking because the existing compatibility constraint uniquely entails none; all must still declare stacking. The original DECLARED value and review digest stay unchanged. Server-derived canonicalContracts records CONSTRAINT_ENTAILED separately and is recomputed/checked on stored reads; missing, forged or stale metadata fails closed. Review inputs cannot supply that metadata. Missing/conflicted/revoked/incomparable members remain UNKNOWN. Only computation reference cycles and duplicates are rejected; ordinary business graph cycles are permitted. Eligibility and exclusions currently require explicit NOT_APPLICABLE.

Temporal decisions require an explicit aware as_of and matching clock/timezone/bounds. UTC/fixed offsets are supported; IANA/DST is UNKNOWN, and wall clock is never used. finite_contexts must exactly match up to100 reviewed typed contexts. A finite best is never a global maximum or execution authorization. Existing no-contract one-source-function behavior remains unchanged.

Original failure/omission denominators are always preserved. business-build --processing-outcomes and review processingContract optionally retain accepted input indices for business coverage_view=processing. Terminal accepted/unsupported/rejected/conflicted/duplicate/omitted outcomes are separate from revoked/invalidated events. Unrecorded historical scope remains UNKNOWN. Accounting is not business completeness. JSON/RDF retain canonical typed contracts; RDF asserts no business truth.

Optional tags use existing facets: business_property.scalar_type=property_type; business_policy.inputs=formula_mapping; priority=policy_composition; clock_timezone=clock_basis; missing_context=finite_contexts. The schema lists all required closed fields. The shared semantic validator also checks exact decimal digits/scale, current source roles and reference closure. No implicit rounding or unit/currency conversion is performed. Decimal precision is at most100 digits, mappings at most16 inputs and composition at most16 members.

For detailed review accounting add processingContract with schemaVersion=1 and scope=original_selected_inputs to the explicit review manifest. Use the existing ontology_pipeline_coverage tool with current business pins, knowledge_view=business and coverage_view=processing; follow every nextOffset. Without accepted input indices, historical accounting remains UNKNOWN.

Time-valued or unknown-dimension property evaluation is unsupported and remains UNKNOWN; time metadata is retained. Existing exclusivity/stackability facets must agree with a new composition contract. Partitioned exports retain one global paged processing ledger at the root; each part references its original scope, pins and manifest hash while retaining its own record-subset denominator.

The read_policy projection removes sourcePins, sourceRuleDigest and numericContextDigest from formula_mapping values recursively, including nested sequence values. It preserves the business input/output mapping and opaque sourceRuleId. read_evidence responses and canonical exports retain the full contract. A projected mapping is presentation data, not a valid review/provenance manifest. Each composition level applies the same eligibility/exclusion gates as its leaves. Business as_of timestamps are not truncated into dates: for source functions without date validity bounds, only the business temporal gate uses the aware instant; a bounded source date interval requires an explicit clock mapping and otherwise remains UNKNOWN. Legacy date-only source evaluation is unchanged.

### Exact dimensions and contributing policies

Explicit quantity/money contracts can bind a source `int` without changing its type. Dimensional wire values remain strings; only exact whole-number spellings are accepted for `int`. Fractions, decimal spellings such as `2.0`, floats, overflow and mismatched precision/scale remain unsupported; nothing is rounded. Money may retain both an explicitly reviewed unit and currency. The unit is an opaque declared dimension, not an inferred price convention or currency conversion. Existing declared facets must agree exactly.

`selectedPolicyIds` remains the full dependency inventory. `activeMemberPolicyIds` lists applicable direct members; `selectedMemberPolicyIds` lists direct members contributing to the result after priority/stacking. `contributingPolicyIds` and `contributingSourceRuleIds` identify contributing leaves and their exact source rules. Min/max retain all equal contributors; nested selections and each winning finite context retain their own provenance. Unresolved or conflicting selection returns null contributor lists, never a fabricated winner. Original member/context denominators and `globalOptimum=UNKNOWN` remain intact.

Review budget omissions are counted in both the top coverage summary and the original input receipt; unprocessed inputs remain in the denominator.

## Explicit business-only export and current-review diagnostics

The `business-html` CLI uses `projection="business_only"` in `pipeline_access.export_business_view` and `business_export.export_business`; the Python default remains `full`. The new `companion.business-only-export.v1` artifact contains projected JSON, five-language HTML and projected-byte hashes. It never contains original pins/digests, source anchors, source-generated candidates, private review basis, original processing ledgers or source RDF. Source traceability stays UNKNOWN. Every selected business inventory record is counted as exported or withheld. Source-supported facets and executable source mappings carry explicit projection loss. This artifact cannot be imported as an approval or source-provenance manifest. The ordinary record/byte bounds remain enforced; oversize requests fail without a partial publication.

Original pins remain bound in `business-export-bindings/<projection-id>/binding.json` under the private workspace. This immutable receipt says `binding_only_publication_not_attested`: it can remain after a failed publication and is never publication-success evidence. The trusted `read_business_export_binding` API requires read_policy, read_structure, read_evidence and export_html before returning it. This API is not exposed as an MCP tool. Both minimal export grants, current source/business pins, snapshot stability, required profile and ACL revision are checked during writes and under the publication lock. No extra grants are inferred. Old full export behavior and exported-copy revocation warnings remain.

Review rejection remains rejection. A bounded sealed current-review diagnostic summary identifies original rejected input indices and attempted business identities. A priority tie, missing stacking declaration, contradictory modes and other schema rejection have distinct closed codes. None proves an executable conflict or selects a member. Missing policy queries return UNKNOWN only after normal ACL and snapshot integrity checks; duplicate attempted identities are ambiguous. Historical rejection evidence is not reused for a replacement review. Source anchors in diagnostics require read_evidence; policy-only responses omit them.

Administrator knowledge approval permits policy-authorized readers to see otherwise unclassified business text. Personal information and registered protected values remain non-overridable hard denies, including nested DECLARED values, aliases and private basis. Source string equality does not itself classify a secret. This does not authorize Internet publication or imply universal privacy clearance.


### Context-bound conflict evidence

Every composition member is evaluated through its current source-bound mapping before a positive conflict proof. Missing context or any unknown member remains partial_composition, conflictProven=false/conflictAssessment=UNDETERMINED; original member/context/dependency denominators remain. With all members evaluated, multiple applicable members violate at_most_one. For first_applicable, at least two applicable members at the best declared priority prove priority_selection_ambiguity. Both return UNKNOWN, conflictProven=true with bounded actual leaf/source witnesses and static_supplied_context_only scope; selected/value/contributing/finiteBest fields remain null. Inactive or lower-priority ties alone prove no selection conflict. Equal values do not authorize an arbitrary tied member. all-mode aggregation keeps its exact existing unit/numeric rules.

Policy-only queries preserve closed canonical basis and opaque source/member IDs, while source path/span/anchor digests/private review basis still require read_evidence. Rejected review diagnostics are configuration observations, not conflict proofs. Runtime remains NOT_OBSERVED, execution authorization NOT_PROVIDED, and full policy completeness/global optimum UNKNOWN. Source-producer/analysisSpec bytes are unchanged; a changed businessSpecHash requires a fresh business build and explicit review, not automatic approval transfer.
