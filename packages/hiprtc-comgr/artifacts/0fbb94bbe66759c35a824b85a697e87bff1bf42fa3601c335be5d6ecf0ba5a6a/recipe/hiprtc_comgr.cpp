#define __HIP_PLATFORM_AMD__
#include <hip/hiprtc.h>
#include <amd_comgr/amd_comgr.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

static void need(bool value, const char *message) {
  if (!value) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
static void hip(hiprtcResult status, const char *message) {
  if (status != HIPRTC_SUCCESS) {
    std::fprintf(stderr, "%s: %s\n", message, hiprtcGetErrorString(status)); std::exit(1);
  }
}
static void comgr(amd_comgr_status_t status, const char *message) {
  if (status != AMD_COMGR_STATUS_SUCCESS) {
    const char *text = nullptr; amd_comgr_status_string(status, &text);
    std::fprintf(stderr, "%s: %s\n", message, text ? text : "unknown"); std::exit(1);
  }
}
static void save(const std::string &path, const std::vector<char> &bytes) {
  std::ofstream f(path, std::ios::binary); f.write(bytes.data(), bytes.size());
  need(bool(f), "save compiler output");
}
static std::vector<char> compile(const char *source, const char *name, const char *arch,
                                 bool bitcode, bool negative=false) {
  const char *header = "#define SCALE 2.0f\n";
  const char *header_name = "values.h";
  hiprtcProgram program{};
  hip(hiprtcCreateProgram(&program, source, name, 1, &header, &header_name), "create program");
  std::string target = std::string("--gpu-architecture=")+arch;
  const char *options[] = {target.c_str(), "-O2", "-fgpu-rdc"};
  hiprtcResult result = hiprtcCompileProgram(program, bitcode ? 3 : 2, options);
  size_t logsize=0; hip(hiprtcGetProgramLogSize(program, &logsize), "log size");
  std::vector<char> log(logsize+1, 0); hip(hiprtcGetProgramLog(program, log.data()), "log");
  std::printf("compile %s target=%s status=%d diagnostic=%s\n",name,arch,int(result),log.data());
  if (negative) {
    need(result != HIPRTC_SUCCESS, "invalid source/target unexpectedly compiled");
    need(logsize > 1, "invalid compilation did not produce diagnostic");
    hip(hiprtcDestroyProgram(&program), "destroy negative program");
    return {};
  }
  hip(result, "compile");
  size_t size=0;
  hip(bitcode ? hiprtcGetBitcodeSize(program, &size) : hiprtcGetCodeSize(program, &size), "output size");
  need(size > 64, "compiler output is empty");
  std::vector<char> out(size);
  hip(bitcode ? hiprtcGetBitcode(program, out.data()) : hiprtcGetCode(program, out.data()), "output bytes");
  hip(hiprtcDestroyProgram(&program), "destroy program");
  if (bitcode) need(std::memcmp(out.data(), "BC\xc0\xde", 4) == 0, "LLVM bitcode magic");
  return out;
}
static std::string inspect_elf(const std::vector<char> &out, const char *arch) {
  need(out.size() > 64 && std::memcmp(out.data(), "\x7f" "ELF", 4) == 0, "ELF magic");
  need(static_cast<unsigned char>(out[4]) == 2 && static_cast<unsigned char>(out[5]) == 1, "ELF64 little-endian");
  need(static_cast<unsigned char>(out[18]) == 224 && out[19] == 0, "ELF AMDGPU machine");
  amd_comgr_data_t data{};
  comgr(amd_comgr_create_data(AMD_COMGR_DATA_KIND_EXECUTABLE,&data),"create code object");
  comgr(amd_comgr_set_data(data,out.size(),out.data()),"set code object");
  size_t size=0; comgr(amd_comgr_get_data_isa_name(data,&size,nullptr),"ISA length");
  std::vector<char> isa(size+1,0);comgr(amd_comgr_get_data_isa_name(data,&size,isa.data()),"ISA text");
  need(std::strstr(isa.data(),arch)!=nullptr,"code object ISA differs from explicit target");
  comgr(amd_comgr_release_data(data),"release code object");
  std::printf("code object bytes=%zu isa=%s\n",out.size(),isa.data());
  return isa.data();
}
static void add(amd_comgr_data_set_t set, const std::vector<char> &bytes, const char *name) {
  amd_comgr_data_t data{};comgr(amd_comgr_create_data(AMD_COMGR_DATA_KIND_BC,&data),"create bitcode");
  comgr(amd_comgr_set_data(data,bytes.size(),bytes.data()),"set bitcode");
  comgr(amd_comgr_set_data_name(data,name),"name bitcode");
  comgr(amd_comgr_data_set_add(set,data),"add bitcode");comgr(amd_comgr_release_data(data),"release bitcode ref");
}
static std::vector<char> first(amd_comgr_data_set_t set, amd_comgr_data_kind_t kind) {
  size_t count=0;comgr(amd_comgr_action_data_count(set,kind,&count),"count action results");
  need(count==1,"expected exactly one action result");
  amd_comgr_data_t data{};comgr(amd_comgr_action_data_get_data(set,kind,0,&data),"get action result");
  size_t size=0;comgr(amd_comgr_get_data(data,&size,nullptr),"result size");
  std::vector<char> result(size);comgr(amd_comgr_get_data(data,&size,result.data()),"result bytes");
  comgr(amd_comgr_release_data(data),"release result ref");return result;
}
static void action(amd_comgr_action_kind_t kind, amd_comgr_action_info_t info,
                    amd_comgr_data_set_t input, amd_comgr_data_set_t output) {
  auto status=amd_comgr_do_action(kind,info,input,output);
  if(status!=AMD_COMGR_STATUS_SUCCESS) {
    for(auto type:{AMD_COMGR_DATA_KIND_LOG,AMD_COMGR_DATA_KIND_DIAGNOSTIC}) {
      size_t count=0;amd_comgr_action_data_count(output,type,&count);
      for(size_t i=0;i<count;i++) {
        amd_comgr_data_t data{};amd_comgr_action_data_get_data(output,type,i,&data);
        size_t size=0;amd_comgr_get_data(data,&size,nullptr);
        std::vector<char> log(size+1,0);amd_comgr_get_data(data,&size,log.data());
        std::fprintf(stderr,"COMGR log: %s\n",log.data());amd_comgr_release_data(data);
      }
    }
  }
  comgr(status,"COMGR action");
}
int main(int argc,char **argv) {
  std::setvbuf(stdout,nullptr,_IONBF,0);
  need(argc==2,"output directory required");std::string outdir=argv[1];
  int major=0,minor=0;hip(hiprtcVersion(&major,&minor),"HIPRTC version");
  size_t cmajor=0,cminor=0;amd_comgr_get_version(&cmajor,&cminor);
  std::printf("HIPRTC API=%d.%d COMGR API=%zu.%zu\n",major,minor,cmajor,cminor);
  size_t count=0;comgr(amd_comgr_get_isa_count(&count),"ISA count");need(count>0,"empty ISA support");
  std::printf("COMGR supported ISA entries=%zu\n",count);
  const char *kernel="#include \"values.h\"\nextern \"C\" __global__ void saxpy(float*a,float*b,float*out){unsigned i=blockIdx.x*blockDim.x+threadIdx.x;out[i]=SCALE*a[i]+b[i];}";
  for(const char *arch:{"gfx90a","gfx1100"}) {
    auto elf=compile(kernel,"saxpy.hip",arch,false);inspect_elf(elf,arch);save(outdir+"/"+arch+".hsaco",elf);
  }
  compile("extern \"C\" __global__ void bad(float*out){out[0]=missing_identifier;}","bad.hip","gfx1100",false,true);
  auto bc1=compile("extern \"C\" __device__ float helper(float);extern \"C\" __global__ void pair(float*out){out[0]=helper(3.0f);}","pair.hip","gfx1100",true);
  auto bc2=compile("extern \"C\" __device__ float helper(float x){return x*2.0f;}","helper.hip","gfx1100",true);
  save(outdir+"/pair.bc",bc1);save(outdir+"/helper.bc",bc2);
  amd_comgr_action_info_t info{};comgr(amd_comgr_create_action_info(&info),"action info");
  comgr(amd_comgr_action_info_set_isa_name(info,"amdgcn-amd-amdhsa--gfx1100"),"explicit action ISA");
  comgr(amd_comgr_action_info_set_language(info,AMD_COMGR_LANGUAGE_HIP),"action language");
  amd_comgr_data_set_t input{},linked{},reloc{},executable{};
  for(auto ptr:{&input,&linked,&reloc,&executable})comgr(amd_comgr_create_data_set(ptr),"create dataset");
  add(input,bc1,"pair.bc");add(input,bc2,"helper.bc");
  action(AMD_COMGR_ACTION_LINK_BC_TO_BC,info,input,linked);
  auto linkedbc=first(linked,AMD_COMGR_DATA_KIND_BC);save(outdir+"/linked.bc",linkedbc);
  const char *opts[]={"-O2"};comgr(amd_comgr_action_info_set_option_list(info,opts,1),"codegen options");
  action(AMD_COMGR_ACTION_CODEGEN_BC_TO_RELOCATABLE,info,linked,reloc);
  comgr(amd_comgr_action_info_set_option_list(info,nullptr,0),"reset linker options");
  action(AMD_COMGR_ACTION_LINK_RELOCATABLE_TO_EXECUTABLE,info,reloc,executable);
  auto linkedelf=first(executable,AMD_COMGR_DATA_KIND_EXECUTABLE);inspect_elf(linkedelf,"gfx1100");
  save(outdir+"/linked.hsaco",linkedelf);
  for(auto set:{input,linked,reloc,executable})comgr(amd_comgr_destroy_data_set(set),"destroy dataset");
  comgr(amd_comgr_destroy_action_info(info),"destroy action info");
  std::puts("HIPRTC_COMGR_OFFLINE_OK; GPU execution not attempted");
}
