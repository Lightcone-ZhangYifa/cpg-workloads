"""Generate reviewed GNU/Linux copies; never edit the pinned Intel originals."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

ORIGINALS = {
    "posix/ittnotify.f90": "20a53e54cd7b2f08cff43252ed098c3b7a6afb34fe0a0b64d44cad130c2e3a8f",
    "advisor_annotate.f90": "80a23213ac961a3012768ac8abc0094dfc71f15957242dfef551e3a6f154ecc4",
}


def linux_branches(text):
    """Resolve only the four known Intel condition expressions, all false here."""
    known = {"defined(use_initialized_proc_ptrs)", "defined(_win32)",
             "defined(win32) .or. defined(_win32)", "defined(__apple__)"}
    stack, output, active = [], [], True
    for line in text.splitlines(keepends=True):
        match = re.match(r"\s*!dec\$\s*(if|else if|else|endif)\b(.*)", line, re.I)
        if match:
            operator, expression = match.group(1).lower(), match.group(2).strip().lower()
            if operator in {"if", "else if"} and expression not in known:
                raise ValueError("Unreviewed Intel conditional: " + expression)
            if operator == "if":
                stack.append((active, False))
                active = False
            elif operator == "else if":
                if not stack:
                    raise ValueError("Unbalanced Intel conditional")
                active = False
            elif operator == "else":
                parent, seen_else = stack[-1]
                if seen_else:
                    raise ValueError("Duplicate Intel else")
                stack[-1] = (parent, True)
                active = parent
            else:
                active, _ = stack.pop()
        elif active:
            output.append(line)
    if stack:
        raise ValueError("Unclosed Intel conditional")
    return "".join(output)


def generate(originals: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for relative, expected in ORIGINALS.items():
        original = originals / relative
        raw = original.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("GNU adaptation must be reviewed for changed upstream source: " + relative)
        text = raw.decode()
        changes = []
        if relative.startswith("posix/"):
            text = text.replace("C_LOC, C_ASSOCIATED", "C_LOC, C_ASSOCIATED, C_INTPTR_T, C_NULL_PTR", 1)
            text = text.replace("int_ptr_kind()", "C_INTPTR_T", 1)
            pattern = (r"    type\(C_FUNPTR\) :: (\w+)\n"
                       r"    !DEC\$ ATTRIBUTES C, EXTERN, ALIAS:'([^']+)' :: \1")
            aliases = re.findall(pattern, text)
            if len(aliases) != 23:
                raise ValueError("Expected exactly 23 upstream C pointer aliases")
            text = re.sub(pattern, lambda m: f'    type(C_FUNPTR), bind(C, name="{m[2]}") :: {m[1]}', text)
            # Upstream's three-argument Fortran wrapper omitted C's objtype.
            old = "subroutine itt_proc_create(addr, objname, attribute) bind(C)\n          import\n"
            new = "subroutine itt_proc_create(addr, objtype, objname, attribute) bind(C)\n          import\n          type(C_PTR), intent(in), value :: objtype\n"
            if text.count(old) != 1 or text.count("call sync_create_ptr(addr, objnametmp, attribute)") != 1:
                raise ValueError("The reviewed sync_create ABI changed")
            text = text.replace(old, new).replace("call sync_create_ptr(addr, objnametmp, attribute)",
                                                  "call sync_create_ptr(addr, C_NULL_PTR, objnametmp, attribute)")
            changes = ["Use ISO_C_BINDING C_INTPTR_T instead of Intel int_ptr_kind().",
                       "Bind all 23 function-pointer globals to their exact upstream C names with BIND(C).",
                       "Pass C_NULL_PTR for the missing C sync_create objtype parameter; preserve the public Fortran signature."]
        else:
            text = linux_branches(text)
            text = text.replace("C_LOC, C_ASSOCIATED", "&\n        C_LOC, C_ASSOCIATED, C_INTPTR_T, C_SIZE_T, C_NULL_PTR, C_SIZEOF", 1)
            text = text.replace("integer(kind=C_INT), intent(in), value :: len", "integer(kind=C_SIZE_T), intent(in), value :: len")
            text = text.replace("integer(kind=C_INT), intent(in), value :: size", "integer(kind=C_SIZE_T), intent(in), value :: size")
            text = re.sub(r"len\((site_name|task_name)\)", r"len(\1, kind=C_SIZE_T)", text)
            text = text.replace("complex(kind=16)", "complex(kind=8)")
            text = re.sub(r"(call (?:induction|reduction|observe|clear)_uses\(C_LOC\(x\), )\d+(\))", r"\1C_SIZEOF(x)\2", text)
            begin = text.index("    subroutine annotate_induction_uses_c8(x)")
            end = text.index("    end subroutine annotate_induction_uses_c8", begin)
            text = text[:begin] + text[begin:end].replace("call reduction_uses", "call induction_uses") + text[end:]
            # Public integer IDs/counts stay source-compatible. The C interfaces
            # receive their actual pointer/size_t widths, not 32-bit stand-ins.
            text = text.replace("call lock_acquire_2(lock_id)", "call lock_acquire_2(transfer(int(lock_id, C_INTPTR_T), C_NULL_PTR))")
            text = text.replace("call lock_release_2(lock_id)", "call lock_release_2(transfer(int(lock_id, C_INTPTR_T), C_NULL_PTR))")
            text = text.replace("call aggregate_task(count)", "call aggregate_task(int(count, C_SIZE_T))")
            extra = ("        subroutine itt_proc_with_pointer(address) bind(C)\n"
                     "            import\n            type(C_PTR), value :: address\n"
                     "        end subroutine itt_proc_with_pointer\n"
                     "        subroutine itt_proc_with_size(count) bind(C)\n"
                     "            import\n            integer(C_SIZE_T), value :: count\n"
                     "        end subroutine itt_proc_with_size\n")
            text = text.replace("    end interface\n", extra + "    end interface\n", 1)
            text = re.sub(r"procedure\(itt_proc_with_int\),(\s*)pointer :: (lock_acquire_2|lock_release_2)",
                          r"procedure(itt_proc_with_pointer),\1pointer :: \2", text)
            text = re.sub(r"procedure\(itt_proc_with_int\),(\s*)pointer :: aggregate_task",
                          r"procedure(itt_proc_with_size),\1pointer :: aggregate_task", text)
            text = re.sub(r"(lock_(?:acquire|release)_2\s*=> )itt_proc_with_int_stub", r"\1itt_proc_with_pointer_stub", text)
            text = re.sub(r"(aggregate_task\s*=> )itt_proc_with_int_stub", r"\1itt_proc_with_size_stub", text)
            stubs = ("    subroutine itt_proc_with_pointer_stub(address) bind(C)\n"
                     "        type(C_PTR), value :: address\n    end subroutine itt_proc_with_pointer_stub\n"
                     "    subroutine itt_proc_with_size_stub(count) bind(C)\n"
                     "        integer(C_SIZE_T), value :: count\n    end subroutine itt_proc_with_size_stub\n")
            text = text.replace("    subroutine itt_proc_stub() bind(C)", stubs + "    subroutine itt_proc_stub() bind(C)", 1)
            text, strings = re.subn(r'("[^"\n]*")C\b', r'\1//C_NULL_CHAR', text)
            if strings != 15:
                raise ValueError("Expected exactly 15 Linux Intel C-string literals")
            # Initialize the existing no-op fallback first. A collector may exist
            # without the legacy Advisor symbols; do not call a NULL dlsym result.
            start = text.index("        if (C_ASSOCIATED(library)) then")
            end = text.index("        initialized = .true.", start)
            block = text[start:end]
            calls = re.findall(r'call C_F_PROCPOINTER\(get_library_entry\(library, ("[^"]+"//C_NULL_CHAR)\),\s*(\w+)\)', block)
            fallback = block.split("        else\n", 1)[1].split("        end if", 1)[0]
            if len(calls) != 14:
                raise ValueError("Expected exactly 14 legacy Advisor function pointers")
            replacement = fallback + "        if (C_ASSOCIATED(library)) then\n"
            for symbol, variable in calls:
                replacement += (f"            entry = get_library_entry(library, {symbol})\n"
                                f"            if (C_ASSOCIATED(entry)) call C_F_PROCPOINTER(entry, {variable})\n")
            replacement += "        end if\n\n"
            text = text[:start] + replacement + text[end:]
            text = text.replace("        type(C_PTR) :: library\n", "        type(C_PTR) :: library\n        type(C_FUNPTR) :: entry\n", 1)
            changes = ["Select the original non-initialized-procedure-pointer GNU/Linux branches of Intel conditional comments.",
                       "Replace 15 Intel C-string literals with standard C_NULL_CHAR concatenation.",
                       "Match the pinned C API's size_t lengths/sizes/count and void* lock identity types; public integer lock IDs/counts remain unchanged.",
                       "Correct complex(kind=8) overloads and use C_SIZEOF for all 28 typed memory notifications; route complex induction to induction.",
                       "Keep original no-op stubs when a loaded collector lacks one of the 14 legacy Advisor model functions."]
        # Lines shortened only for GNU free-form source; comments remain intact.
        if relative.startswith("posix/"):
            text = text.replace("C_ASSOCIATED, C_INTPTR_T, C_NULL_PTR", "&\n        C_ASSOCIATED, C_INTPTR_T, C_NULL_PTR", 1)
        output = destination / Path(relative).name
        output.write_text(text)
        rows.append({"original": relative, "original_sha256": expected,
                     "generated": output.name, "generated_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                     "changes": changes})
    report = {"schema_version": 1, "target": "GNU Fortran 13 / Linux x86_64", "files": rows,
              "source_originals_preserved": True,
              "limits": ["GNU .mod files are compiler-specific; rebuild for other compilers or incompatible module ABIs.",
                         "The reference collector has no legacy Advisor __itt_model_* implementation; the Advisor ABI fixture is not a profiler.",
                         "Instrumentation without a supporting collector is intentionally a no-op, not evidence of event delivery."]}
    (destination / "adaptation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
