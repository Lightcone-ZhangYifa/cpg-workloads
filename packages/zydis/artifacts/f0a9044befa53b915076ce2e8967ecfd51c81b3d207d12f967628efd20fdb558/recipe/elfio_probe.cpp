#include <elfio/elfio.hpp>
#include <ario/ario.hpp>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

void need(bool yes, const char* why){if(!yes)throw std::runtime_error(why);}
std::string read(const char* p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){
 try{
  if(argc!=6)return 2;
  ELFIO::elfio elf;
  need(elf.load(argv[1]),"ELF input load");
  need(elf.get_class()==ELFIO::ELFCLASS64,"ELF class");
  auto *sym=elf.sections[".symtab"];
  need(sym!=nullptr,"symbol section");
  ELFIO::symbol_section_accessor symbols(elf,sym);
  bool found=false;
  for(ELFIO::Elf_Xword i=0;i<symbols.get_symbols_num();i++){
   std::string name;ELFIO::Elf64_Addr value;ELFIO::Elf_Xword size;unsigned char bind,type,other;ELFIO::Elf_Half index;
   need(symbols.get_symbol(i,name,value,size,bind,type,index,other),"get symbol");
   if(name=="transform")found=true;
  }
  need(found,"original symbol transform");
  auto *section=elf.sections.add(".cpg024");
  section->set_type(ELFIO::SHT_PROGBITS);section->set_addr_align(1);
  const std::string data("CPG024\0binary",13);section->set_data(data);
  ELFIO::string_section_accessor strs(elf.sections[sym->get_link()]);
  symbols.add_symbol(strs,"cpg_marker",0,6,ELFIO::STB_GLOBAL,ELFIO::STT_OBJECT,0,section->get_index());
  need(elf.save(argv[2]),"ELF save");
  ELFIO::elfio reread;need(reread.load(argv[2]),"ELF reread");
  need(reread.sections[".cpg024"]->get_size()==data.size(),"section size");
  need(std::string(reread.sections[".cpg024"]->get_data(),data.size())==data,"section bytes");
  ARIO::ario ar;ARIO::ario::Member a,b;
  a.name="member_with_a_long_filename_024.o";a.mode=0644;
  b.name="odd.txt";b.mode=0644;
  need(ar.add_member(a,read(argv[2])).ok(),"archive object add");
  need(ar.add_symbols_for_member(a,{"transform","cpg_marker"}).ok(),"archive symbols");
  need(ar.add_member(b,"abc").ok(),"archive odd add");
  need(!ar.add_member(b,"duplicate").ok(),"duplicate member rejected");
  need(ar.save(argv[3]).ok(),"archive save");
  ARIO::ario ar2;need(ar2.load(argv[3]).ok(),"archive reload");
  need(ar2.members.size()==2,"archive member count");
  need(ar2.members[0].data()==read(argv[2]),"archive object data");
  need(ar2.members[1].data()=="abc","odd member bytes");
  std::optional<std::reference_wrapper<const ARIO::ario::Member>> found_member;need(ar2.find_symbol("transform",found_member).ok(),"archive find symbol");
  need(found_member.has_value() && found_member->get().name==a.name,"symbol member binding");
  need(!ar2.find_symbol("absent",found_member).ok(),"missing symbol rejected");
  ARIO::ario bad;need(!bad.load(argv[4]).ok(),"invalid archive rejected");
  ELFIO::elfio badelf;need(!badelf.load(argv[4]),"invalid ELF rejected");
  ARIO::ario foreign;need(foreign.load(argv[5]).ok(),"GNU ar input load");
  bool target=false;for(const auto& member:foreign.members)if(member.name=="input.o")target=member.data()==read(argv[1]);
  need(target,"GNU ar member content");
  std::cout<<"{\"status\":\"passed\",\"elf_read_write\":true,\"archive_read_write\":true,\"negative_cases\":4}"<<std::endl;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
