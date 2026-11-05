from elftools.elf.elffile import ELFFile
import sys
with open(sys.executable,'rb') as f:
    elf=ELFFile(f)
    assert elf.header.e_ident.EI_MAG == [127,69,76,70]
    assert elf.num_segments()>0
print('CPG_FUNCTIONAL_OK:pyelftools:actual-elf-parsing')
