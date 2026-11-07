#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
#include <stdio.h>
int main(int argc,char **argv) {
  if(argc!=2)return 1;
  lua_State *L=luaL_newstate();if(!L)return 2;
  luaL_openlibs(L);
  if(luaL_dofile(L,argv[1])){fprintf(stderr,"%s\n",lua_tostring(L,-1));lua_close(L);return 3;}
  lua_close(L);return 0;
}
