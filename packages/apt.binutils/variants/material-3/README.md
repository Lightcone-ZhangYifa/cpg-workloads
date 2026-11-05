# GNU Binutils support material

Software `apt.binutils` version `2.42-4ubuntu2.10`; material build `3`.

## Download type and scope

This is a support-material variant for the existing software. The published build `2` APT wrapper, its source lock, target, dependencies and qualification are unchanged. This material installs files into its own prefix; it does not install the enclosed DEBs, invoke APT, compile examples, or execute the native tools. It is not a newly compiled binary/source package and introduces no new software family.

Bounded ELF, archive, relocation, disassembly and detached-debuglink examples using a separately prepared host GNU Binutils. No Binutils executable or upstream source is bundled.

The payload includes 0 unchanged DEB inputs and 0 corresponding source set(s), with exact URL/size/SHA256 locks. Source archives, Debian changes and preserved signatures retain their original bytes. A signature file's presence does not mean its trust chain was verified.

## Explicit offline use

`python3 -B <prefix>/scripts/replay.py --output /absolute/new/output` explicitly runs this software's bounded examples in a new directory outside the installed material. It uses the original relevant methods and unchanged oracles, with neutral fixture names and only this software's input subset. GNU fixture preparation remains an explicit prerequisite for the elfutils/libdwarf examples. Results of that preparation are separated from the requested software's capability record. There is no fixed promise of 66 commands for this smaller variant.

The runtime requires Linux x86_64, Python 3, the selected GNU host tools, libseccomp and suitable dynamic dependencies. It uses private `dpkg-deb -x` extraction where applicable and never executes package maintenance scripts or performs a system package installation. Material installation itself has no native software dependency requirement. The original wrapper's dependency list is retained in `metadata/software-identity.json` for explicit native preparation.

The network guard and debuginfod overrides remain enabled. Optional fetch scripts are preparation tools only: run them in a separate writable copy of the source master, never in an installed material prefix. They are not called by installation or replay. Corresponding-source preparation pins the initial DSC to its retained SHA256 and size before following its checksummed entries.

## Qualification and historical limits

The original frozen software identity is 2.42-4ubuntu2.10, while the historical host examples used 2.42-4ubuntu2.5. Those observations are not execution evidence for the frozen version or this new artifact.

This new material was packaged and statically reviewed only. Installation, replay, compilation, functional checks and signature verification are **not run**. The existing four trusted APT qualifications and formal M/F values are not promoted; Dataset remains null. The declared package check only compares the complete material inventory. Historical raw run logs and their private filesystem paths are retained in the original durable delivery, not copied into this new software artifact.

## Sources and licenses

Authored C examples and support scripts are in `examples/` and `scripts/`, under the retained MIT `LICENSE`. Each enclosed binary's original copyright notice and applicable GPL/LGPL texts are in `licenses/`; elfutils also retains its GFDL text. The complete corresponding source set is distributed alongside the binaries in `inputs/source/`. Source/signature byte locks are preserved without claiming native rebuild or signature verification.

The Git source master contains authored code, recipe, small control/notice files and complete input locks. The compressed DEB/source bytes live in this independently downloadable material artifact, rather than being duplicated in Git. `artifact-lock.json` and the frozen manifest bind the generated artifact.
