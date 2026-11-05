# Worker 011 migration validation

The original v001 material archive verified under the isolated CPG 1.0.0 runtime and installed cleanly. Its declared availability check passed; functional status correctly remained `not_run`. This original artifact has no new publication qualification. Its bytes and original package/registry/index definitions are preserved.

## v002

Build `worker-011-v002` adds one separate functional check for the installed local reference reader. It exercises search and read for all four fixed reference entities and compares returned entity IDs, source paths, line numbers, exact original text, full source SHA-256, and immutable commit URLs. It also checks an absent query and path traversal rejection. It does not execute LLVM or MLIR, change the reference entities' historical qualifications, or add an upstream family.

The original 98-file payload, 1,622,103 bytes, remains byte-identical. The helper and recipes remain CPG workload integration code; the existing framework performs verification, packaging, installation, checks, inventory validation, and removal. Original entity IDs were added to the query-visible summary and examples so existing package discovery can locate their shared container.

## Executed validation

- Original 25-check offline reader suite passed, including real retrieval, all 37 sparse operation locators, damaged/missing/extra materials, index changes, links, inventory locks, invalid input, and offline consumption observations.
- Six new functional-gate regression tests passed, including six distinct nonempty-but-wrong search result cases and wrong read output.
- Two independent v002 installations each passed availability, functional, and installed-inventory verification. All 98 ordinary payload files have independent inodes and identical bytes.
- All four original entity IDs resolve to the one package through the current PackageManager query API.
- A deliberate A-prefix source mutation was rejected by both installed-inventory verification and the new declared functional check. B stayed verified. Restoring A passed fresh verification and checks; removing A left B functional. Both the failure and restored-success evidence remain available.

The v002 artifact is 287,072 bytes, SHA-256 `050720b9f7b9095d878996dc014f7ab68f411fe1f0be3e9695a19cad04c40b38`, manifest SHA-256 `7dce33d0f14b035b4d5325193e6427d333ff4cb848387ee5ef99aca84ec4a443`. `cpg/packaging-provenance.json` is the exact provenance supplied to the existing framework packer. Independent offline rebuild verification passed: the original builder regenerated all 98 payload files and the existing framework packer reproduced the exact v002 artifact size, SHA-256, and manifest digest. Remote upload verification is a separate root task.
