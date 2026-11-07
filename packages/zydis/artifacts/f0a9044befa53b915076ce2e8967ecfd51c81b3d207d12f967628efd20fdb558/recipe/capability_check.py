#!/usr/bin/env python3
"""Offline, bounded functionality checks against independent tool/oracle outputs."""
import argparse, hashlib, importlib.metadata, io, json, os, pathlib, re, subprocess, sys, tempfile, zipfile

COMMANDS=[]
def run(argv, *, cwd=None, ok=True):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True,text=True,timeout=90)
    COMMANDS.append({'argv':[str(x) for x in argv],'returncode':p.returncode,'stdout':p.stdout[-12000:],'stderr':p.stderr[-12000:]})
    if ok and p.returncode:raise AssertionError(f'command failed {argv}: {p.stderr}')
    return p
def need(x,why):
    if not x:raise AssertionError(why)
def oracle(name,tmp):
    root=pathlib.Path(__file__).resolve().parent/'oracles'
    lock=json.loads((root/'lock.json').read_text())
    row=lock[name];p=root/row['filename']
    need(hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],'independent oracle wheel hash')
    out=tmp/('oracle-'+name);out.mkdir()
    with zipfile.ZipFile(p) as z:
        for item in z.infolist():
            q=pathlib.PurePosixPath(item.filename)
            need(not q.is_absolute() and '..' not in q.parts,'wheel safe path')
        z.extractall(out)
    sys.path.insert(0,str(out))
def capkey(ins):
    values=[]
    for o in ins.operands:
        if o.type==1:values.append(('reg',ins.reg_name(o.reg),o.size))
        elif o.type==2:values.append(('imm',o.imm,o.size))
        elif o.type==3:
            m=o.mem;values.append(('mem',ins.reg_name(m.segment),ins.reg_name(m.base),ins.reg_name(m.index),m.scale,m.disp,o.size))
        else:values.append(('other',o.type))
    return (ins.id,tuple(values))
def corpus():
    result=[(64,x) for x in ['4889d8','83c007','488b448b20','488d0510000000','0f57c0','c5fdefc0','62f17d48efc0','7505','ebf9','e8fb000000','c3']]
    for mode in [16,32]:result.extend((mode,x) for x in ['89d8','83c007','7505','ebf9','c3'])
    for imm in list(range(256))+[0x7fffffff,0x80000000,0xffffffff]:
        result.append((64,(b'\xb8'+imm.to_bytes(4,'little')).hex()))
    return result
def check_native(prefix,tmp,which):
    oracle('capstone',tmp)
    import capstone as cs
    exe=prefix/'bin'/('cpg-'+which+'-probe')
    tests=[]
    for mode,hexcode in corpus():
        raw=bytes.fromhex(hexcode);decoder=cs.Cs(cs.CS_ARCH_X86,{16:cs.CS_MODE_16,32:cs.CS_MODE_32,64:cs.CS_MODE_64}[mode]);decoder.detail=True
        before=list(decoder.disasm(raw,0x1000));need(len(before)==1 and before[0].size==len(raw),'oracle full original decode')
        data=json.loads(run([exe,mode,hexcode]).stdout)
        encoded=bytes.fromhex(data['encoded']);after=list(decoder.disasm(encoded,0x1000))
        need(data['length']==len(raw),'native decoder length disagrees with independent oracle')
        need(len(after)==1 and after[0].size==len(encoded),'oracle full encoded decode')
        need(capkey(before[0])==capkey(after[0]),f'native decode/encode operand semantics {hexcode} -> {encoded.hex()}')
        tests.append({'mode':mode,'input':hexcode,'encoded':encoded.hex(),'oracle':before[0].mnemonic+' '+before[0].op_str})
    for mode,h in [(64,'0f'),(32,'0f'),(16,'0f'),(64,'62')]:
        need(run([exe,mode,h],ok=False).returncode==2,'truncated instruction must be rejected')
    need(run([exe,8,'90'],ok=False).returncode==3,'invalid machine mode rejected')
    # A native independent binary tool also checks the fixed SIMD/branch corpus.
    raw=tmp/'instructions.bin';raw.write_bytes(bytes.fromhex('4889d883c007488b448b200f57c0c3'))
    s=run(['objdump','-D','-b','binary','-m','i386:x86-64','-M','intel',raw]).stdout
    need(all(x in s for x in ['mov','add','xorps','ret']),'GNU disassembler independent cross-check')
    return {'codec_cases':len(tests),'negative_cases':5,'cases':tests,'execution_scope':'encoding/decoding only; no SIMD or foreign-ISA execution claim','oracle':'exact original py.capstone 5.0.9 wheel and GNU objdump'}

def fixture(tmp):
    src=tmp/'input.c'
    src.write_text('#include <stdio.h>\n__attribute__((noinline)) int transform(int x){return x*3+1;}\n__attribute__((noinline)) int answer(void){return 37;}\nint main(void){printf("%d %d\\n",answer(),transform(14));return 0;}\n')
    run(['gcc','-g','-gdwarf-4','-O0','-fno-pie','-c',src,'-o',tmp/'input.o'])
    run(['gcc','-g','-gdwarf-4','-O2','-fno-pie','-no-pie',src,'-o',tmp/'input'])
    return src,tmp/'input.o',tmp/'input'

def check_elfio(prefix,tmp):
    src,obj,exe=fixture(tmp)
    run(['ar','rcs',tmp/'gnu.a',obj]);(tmp/'invalid').write_bytes(b'not-elf-or-ar')
    data=json.loads(run([prefix/'bin/cpg-elfio-probe',obj,tmp/'rewritten.o',tmp/'written.a',tmp/'invalid',tmp/'gnu.a']).stdout)
    sections=run(['readelf','-SW',tmp/'rewritten.o']).stdout
    symbols=run(['readelf','-sW',tmp/'rewritten.o']).stdout
    need('.cpg024' in sections and 'cpg_marker' in symbols and 'transform' in symbols,'readelf section/symbol independent oracle')
    dumped=run(['readelf','-x','.cpg024',tmp/'rewritten.o']).stdout
    need('43504730' in dumped and 'binary' in dumped,'readelf verifies actual new section bytes')
    members=run(['ar','t',tmp/'written.a']).stdout.splitlines()
    need(members==['member_with_a_long_filename_024.o','odd.txt'],'GNU ar names/order')
    p=subprocess.run(['ar','p',str(tmp/'written.a'),members[0]],capture_output=True,timeout=30)
    need(p.returncode==0 and p.stdout==(tmp/'rewritten.o').read_bytes(),'GNU ar extracted bytes')
    p=subprocess.run(['ar','p',str(tmp/'written.a'),'odd.txt'],capture_output=True,timeout=30)
    need(p.returncode==0 and p.stdout==b'abc','GNU ar odd-size padding')
    need('transform' in run(['nm','-s',tmp/'written.a']).stdout,'GNU nm archive index')
    run(['gcc','-no-pie',tmp/'rewritten.o','-o',tmp/'rewritten'])
    need(run([tmp/'rewritten']).stdout=='37 43\n','rewritten ELF links and executes')
    return {'elf_section_symbol_roundtrip':True,'archive_long_name_odd_member_symbol_index':True,'independent_oracles':['GNU readelf','GNU ar','GNU nm','GCC relink and execution'],'negative_cases':data['negative_cases'],'runtime_output':'37 43'}

def check_capstone(prefix,tmp):
    import capstone as cs
    oracle('keystone-engine',tmp)
    import keystone as ks
    vectors=[
      ('x86-64',ks.KS_ARCH_X86,ks.KS_MODE_64,cs.CS_ARCH_X86,cs.CS_MODE_64,'mov rax, rbx','4889d8','mov'),
      ('arm',ks.KS_ARCH_ARM,ks.KS_MODE_ARM,cs.CS_ARCH_ARM,cs.CS_MODE_ARM,'add r0, r1, #5','050081e2','add'),
      ('aarch64',ks.KS_ARCH_ARM64,ks.KS_MODE_LITTLE_ENDIAN,cs.CS_ARCH_ARM64,cs.CS_MODE_ARM,'add x0, x1, #5','20140091','add'),
      ('mips32le',ks.KS_ARCH_MIPS,ks.KS_MODE_MIPS32|ks.KS_MODE_LITTLE_ENDIAN,cs.CS_ARCH_MIPS,cs.CS_MODE_MIPS32|cs.CS_MODE_LITTLE_ENDIAN,'addiu $t0, $t1, 5','05002825','addiu'),
      ('ppc32be',ks.KS_ARCH_PPC,ks.KS_MODE_PPC32|ks.KS_MODE_BIG_ENDIAN,cs.CS_ARCH_PPC,cs.CS_MODE_32|cs.CS_MODE_BIG_ENDIAN,'addi 3, 4, 5','38640005','addi'),
      ('sparc32be',ks.KS_ARCH_SPARC,ks.KS_MODE_SPARC32|ks.KS_MODE_BIG_ENDIAN,cs.CS_ARCH_SPARC,cs.CS_MODE_BIG_ENDIAN,'add %g1, 5, %g2','84006005','add')]
    details=[]
    for name,ka,km,ca,cm,asm,golden,mnem in vectors:
        raw=bytes(ks.Ks(ka,km).asm(asm,0x1000)[0]);need(raw.hex()==golden,'independent assembler byte oracle '+name)
        dec=cs.Cs(ca,cm);dec.detail=True;ins=list(dec.disasm(raw,0x1000));need(len(ins)==1 and ins[0].size==len(raw),'full instruction '+name)
        need(ins[0].mnemonic==mnem and len(ins[0].operands)>0,'mnemonic/operand details '+name)
        details.append({'isa':name,'bytes':golden,'instruction':ins[0].mnemonic+' '+ins[0].op_str,'operands':len(ins[0].operands)})
    md=cs.Cs(cs.CS_ARCH_X86,cs.CS_MODE_64);md.detail=True
    jump=list(md.disasm(bytes.fromhex('7505'),0x1000))[0]
    need(jump.operands[0].imm==0x1007,'PC relative branch target')
    need(not list(md.disasm(b'\x0f',0)),'invalid/truncated rejected')
    try: cs.Cs(0x7fffffff,0)
    except cs.CsError: pass
    else: raise AssertionError('invalid architecture must fail')
    return {'distribution_version':importlib.metadata.version('capstone'),'module_reported_version':cs.__version__,'isa_cases':details,'negative_cases':2,'scope':'instruction decoding and operand metadata only; foreign code not executed'}

def check_iced(prefix,tmp):
    import iced_x86 as ix
    oracle('capstone',tmp);import capstone as cs
    n=0
    for bits,h in corpus():
        raw=bytes.fromhex(h);ins=ix.Decoder(bits,raw,ip=0x1000).decode();need(not ins.is_invalid,'iced original decode')
        enc=ix.Encoder(bits);enc.encode(ins,0x1000);new=enc.take_buffer()
        md=cs.Cs(cs.CS_ARCH_X86,{16:cs.CS_MODE_16,32:cs.CS_MODE_32,64:cs.CS_MODE_64}[bits]);md.detail=True
        a=list(md.disasm(raw,0x1000));b=list(md.disasm(new,0x1000))
        need(len(a)==len(b)==1 and capkey(a[0])==capkey(b[0]),'iced encoding independent operand oracle')
        n+=1
    rel=[]
    for raw,expected in [(bytes.fromhex('e8fb000000'),0x1100),(bytes.fromhex('488b0510000000'),0x1017)]:
        instructions=list(ix.Decoder(64,raw,ip=0x1000));enc=ix.BlockEncoder(64);enc.add_many(instructions);new=enc.encode(0x2000)
        got=ix.Decoder(64,new,ip=0x2000).decode();target=got.near_branch_target if raw[0]==0xe8 else got.ip_rel_memory_address
        need(target==expected,'relocated external branch/data target')
        md=cs.Cs(cs.CS_ARCH_X86,cs.CS_MODE_64);md.detail=True;o=list(md.disasm(new,0x2000))[0]
        independent=o.operands[0].imm if raw[0]==0xe8 else o.address+o.size+o.operands[1].mem.disp
        need(independent==expected,'Capstone relocation target independent oracle')
        rel.append({'original':raw.hex(),'relocated':new.hex(),'source_ip':0x1000,'destination_ip':0x2000,'target':target})
    raw=bytes.fromhex('7505b807000000c3');instructions=list(ix.Decoder(64,raw,ip=0x1000));enc=ix.BlockEncoder(64);enc.add_many(instructions);new=enc.encode(0x8000)
    moved=list(ix.Decoder(64,new,ip=0x8000));need(moved[0].near_branch_target==moved[-1].ip,'internal branch follows block relocation')
    bad=ix.Decoder(64,b'\x0f').decode();need(bad.is_invalid,'truncated iced decode')
    try: ix.Encoder(64).encode(bad,0)
    except ValueError: pass
    else:raise AssertionError('invalid encoding accepted')
    return {'roundtrip_cases':n,'relocations':rel,'internal_branch_relocation':True,'negative_cases':2,'oracle':'Capstone original frozen wheel'}

def check_keystone(prefix,tmp):
    import keystone as ks
    oracle('capstone',tmp);import capstone as cs
    cases=[]
    for mode,cm in [(ks.KS_MODE_16,cs.CS_MODE_16),(ks.KS_MODE_32,cs.CS_MODE_32),(ks.KS_MODE_64,cs.CS_MODE_64)]:
        reg='ax' if mode==ks.KS_MODE_16 else 'eax'
        for imm in [-128,-1,0,1,7,127,128,255,32767]:
            text=f'mov {reg}, {imm}; add {reg}, 7; ret';raw=bytes(ks.Ks(ks.KS_ARCH_X86,mode).asm(text,0x1000)[0]);md=cs.Cs(cs.CS_ARCH_X86,cm);md.detail=True;seq=list(md.disasm(raw,0x1000))
            need([x.mnemonic for x in seq]==['mov','add','ret'],'Keystone independent sequence')
            need(seq[0].operands[0].reg==seq[1].operands[0].reg and seq[1].operands[1].imm==7,'Keystone operand values')
            need((seq[0].operands[1].imm&((1<<(16 if mode==ks.KS_MODE_16 else 32))-1))==(imm&((1<<(16 if mode==ks.KS_MODE_16 else 32))-1)),'Keystone immediate semantics')
            cases.append({'mode':mode,'assembly':text,'bytes':raw.hex()})
    for ka,km,ca,cm,asm,mnem in [(ks.KS_ARCH_ARM,ks.KS_MODE_ARM,cs.CS_ARCH_ARM,cs.CS_MODE_ARM,'add r0, r1, #5','add'),(ks.KS_ARCH_ARM64,ks.KS_MODE_LITTLE_ENDIAN,cs.CS_ARCH_ARM64,cs.CS_MODE_ARM,'add x0, x1, #5','add'),(ks.KS_ARCH_MIPS,ks.KS_MODE_MIPS32|ks.KS_MODE_LITTLE_ENDIAN,cs.CS_ARCH_MIPS,cs.CS_MODE_MIPS32|cs.CS_MODE_LITTLE_ENDIAN,'addiu $t0, $t1, 5','addiu')]:
        raw=bytes(ks.Ks(ka,km).asm(asm)[0]);seq=list(cs.Cs(ca,cm).disasm(raw,0));need(len(seq)==1 and seq[0].mnemonic==mnem,'non-x86 assembly independent disassembly');cases.append({'assembly':asm,'bytes':raw.hex(),'decoded':seq[0].op_str})
    for text in ['not_an_instruction rax, rbx','mov no_such_register, 7']:
        try:ks.Ks(ks.KS_ARCH_X86,ks.KS_MODE_64).asm(text)
        except ks.KsError:pass
        else:raise AssertionError('invalid assembly accepted')
    return {'assembly_cases':len(cases),'cases':cases,'negative_cases':2,'scope':'encoding with independent decoder; no foreign-ISA execution'}

def check_lief(prefix,tmp):
    import lief
    src,obj,exe=fixture(tmp);need(run([exe]).stdout=='37 43\n','original program output')
    binary=lief.parse(str(exe));need(binary is not None,'LIEF original parse')
    symbol=binary.get_symbol('answer');need(symbol is not None,'answer symbol')
    start=bytes(binary.get_content_from_virtual_address(symbol.value,10));skip=4 if start.startswith(bytes.fromhex('f30f1efa')) else 0
    original=bytes(binary.get_content_from_virtual_address(symbol.value+skip,6));need(original==bytes.fromhex('b825000000c3'),'explicit x86 fixture encoding precondition')
    binary.patch_address(symbol.value+skip,list(bytes.fromhex('b85b000000c3')))
    section=lief.ELF.Section('.cpg024');section.content=list(b'CPG024-METADATA');section.type=lief.ELF.Section.TYPE.PROGBITS
    binary.add(section,loaded=False);out=tmp/'rewritten';binary.write(str(out));out.chmod(0o755)
    need(run([out]).stdout=='91 43\n','rewritten ELF actually executes changed answer')
    need('.cpg024' in run(['readelf','-SW',out]).stdout,'readelf new section')
    need('CPG024' in run(['readelf','-p','.cpg024',out]).stdout,'readelf metadata bytes')
    reread=lief.parse(str(out));need(bytes(reread.get_section('.cpg024').content)==b'CPG024-METADATA','LIEF roundtrip metadata')
    need('0x5b' in run(['objdump','-d','-M','intel','--disassemble=answer',out]).stdout,'GNU objdump rewritten immediate oracle')
    invalid=tmp/'invalid';invalid.write_bytes(b'not an ELF')
    need(lief.parse(str(invalid)) is None,'malformed input rejected')
    return {'original_output':'37 43','rewritten_output':'91 43','code_patch':'mov eax,37 -> mov eax,91','new_section':'.cpg024','negative_cases':1,'scope':'Linux x86_64 ELF executable rewriting; not PE/Mach-O execution'}

def check_pyelftools(prefix,tmp):
    from elftools.elf.elffile import ELFFile
    from elftools.common.exceptions import ELFError
    src,obj,exe=fixture(tmp)
    with exe.open('rb') as f:
        elf=ELFFile(f);need(elf.elfclass==64 and elf.little_endian,'ELF class/endianness')
        sym=elf.get_section_by_name('.symtab').get_symbol_by_name('transform')[0]
        value=sym['st_value'];need(sym['st_size']>0,'ELF symbol size')
        need(elf.has_dwarf_info(),'DWARF presence');dwarf=elf.get_dwarf_info();cus=list(dwarf.iter_CUs());need(len(cus)==1,'one compilation unit')
        top=cus[0].get_top_DIE();need(top.attributes['DW_AT_name'].value.decode().endswith('input.c'),'DWARF source name')
        functions=[d for d in cus[0].iter_DIEs() if d.tag=='DW_TAG_subprogram' and d.attributes.get('DW_AT_name') and d.attributes['DW_AT_name'].value==b'transform']
        need(len(functions)==1,'DWARF transform subprogram')
        entries=[e.state for e in dwarf.line_program_for_CU(cus[0]).get_entries() if e.state and not e.state.end_sequence]
        need(any(e.line==2 for e in entries),'source line table contains transform line')
    oracle_symbols=run(['readelf','-sW',exe]).stdout
    need(re.search(r'\b'+f'{value:016x}'+r'\b.*\btransform$',oracle_symbols,re.M),'readelf symbol value independent match')
    dwarf_text=run(['readelf','--debug-dump=info',exe]).stdout
    need('transform' in dwarf_text and 'input.c' in dwarf_text,'readelf DWARF independent match')
    for raw in [b'not-ELF',b'\x7fELF']:
        try:ELFFile(io.BytesIO(raw))
        except (ELFError,ValueError):pass
        else:raise AssertionError('invalid/truncated ELF accepted')
    return {'ELF_symbols':True,'DWARF_compilation_units':len(cus),'DWARF_line_entries':len(entries),'independent_oracle':'GNU readelf','negative_cases':2,'provider_identity':'py.pyelftools; apt.python3-pyelftools is an alternate provider, not another upstream family'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--resource',required=True);p.add_argument('--prefix',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path);a=p.parse_args()
    funcs={'elfio':check_elfio,'py.capstone':check_capstone,'py.iced-x86':check_iced,'py.keystone-engine':check_keystone,'py.lief':check_lief,'py.pyelftools':check_pyelftools}
    with tempfile.TemporaryDirectory(prefix='cpg-worker024-check-') as d:
        t=pathlib.Path(d)
        result=check_native(a.prefix,t,a.resource) if a.resource in ('intel-xed','zydis') else funcs[a.resource](a.prefix,t)
    report={'schema_version':1,'resource_id':a.resource,'status':'passed','functional_scope':result,'commands':COMMANDS}
    text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text)
    print(text)
if __name__=='__main__':main()
