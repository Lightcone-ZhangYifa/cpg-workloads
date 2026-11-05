# apt.time measurement integration

This adapter consumes output associated with the existing `apt.time`
definition, version `1.9-0.2build1`, build `2`. The canonical
package definition is `packages/apt.time/package.json` at repository root.

## Input contract

Run the existing GNU time executable with LC_ALL=C and one dedicated -o output file per process. Use the literal format CPG_TIME_V1\t%e\t%U\t%S\t%M\t%x. Preserve wall/user/system seconds and maximum RSS in KiB. Zero elapsed time means below report resolution and cannot imply infinite speedup. The exact 1.9 Texinfo is authoritative; the separately retained 1.10 live manual supplies supplementary context and the full GFDL text.

The parser is `parse_gnu_time` in the shared `src/measurement_reuse.py`.
Its 4 software-specific format tests use synthetic contracts;
they do not establish an installed software execution or a performance result.
See `integration.json` for exact test names and shared-code references.

## Reference material and examples

`source-lock.json` fixes every retained reference file's bytes and SHA-256,
records its original URL and retains failed URL attempts separately. Reference
licenses are `GFDL-1.3-or-later for manuals; GPL-3.0-or-later for source archive COPYING`; the complete associated notices are in
`reference/`. Examples are source entry points for a separately verified installed
package and remain unexecuted in the adapter validation.

This integration creates no software artifact and changes no existing package
identity or qualification. Downloads belong to the canonical software package
and its recorded package method.
