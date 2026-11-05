#include <expat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int starts, ends, names, attrs; char text[128]; size_t used; } State;
static void start(void *data, const XML_Char *name, const XML_Char **attrs) {
    State *s = data; s->starts++;
    if (!strcmp(name, "urn:test|root") || !strcmp(name, "urn:test|child")) s->names++;
    for (; attrs && attrs[0]; attrs += 2) if (!strcmp(attrs[0], "id") && !strcmp(attrs[1], "7")) s->attrs++;
}
static void end(void *data, const XML_Char *name) { (void)name; ((State *)data)->ends++; }
static void chars(void *data, const XML_Char *value, int length) {
    State *s = data; if (length < 0 || s->used+(size_t)length >= sizeof(s->text)) exit(70);
    memcpy(s->text+s->used, value, length); s->used += length; s->text[s->used] = 0;
}
static void require(int test, const char *message) { if (!test) { fprintf(stderr,"%s\n",message); exit(1); } }
int main(void) {
    int checks=0, rejected=0; const char *document="<root xmlns='urn:test' id='7'><child>caf\xc3\xa9 &amp; x</child></root>";
    const int chunks[]={1,2,7,4096};
    for (size_t c=0;c<sizeof(chunks)/sizeof(chunks[0]);c++) {
        XML_Parser p=XML_ParserCreateNS(NULL,'|'); State s={0}; require(p!=NULL,"parser creation");
        XML_SetUserData(p,&s); XML_SetElementHandler(p,start,end); XML_SetCharacterDataHandler(p,chars);
        size_t length=strlen(document);
        for (size_t offset=0;offset<length;) {
            size_t count=length-offset; if (count>(size_t)chunks[c]) count=chunks[c];
            require(XML_Parse(p,document+offset,(int)count,offset+count==length)==XML_STATUS_OK,"chunk parse"); offset+=count;
        }
        require(s.starts==2 && s.ends==2,"balanced elements"); checks++;
        require(s.names==2,"namespace-qualified names"); checks++;
        require(s.attrs==1,"attribute result"); checks++;
        require(!strcmp(s.text,"caf\xc3\xa9 & x"),"UTF-8/entity result"); checks++;
        require(XML_GetCurrentByteIndex(p)==(XML_Index)length,"exact parse byte count"); checks++;
        require(XML_ParserReset(p,NULL)==XML_TRUE,"reset parser"); checks++;
        XML_ParserFree(p);
    }
    const char *bad[]={"<a></b>","<a x='1' x='2'/>","<a>"};
    for (int i=0;i<3;i++) {
        XML_Parser p=XML_ParserCreate(NULL); require(p!=NULL,"negative parser creation");
        require(XML_Parse(p,bad[i],(int)strlen(bad[i]),XML_TRUE)==XML_STATUS_ERROR,"invalid XML accepted");
        require(XML_GetErrorCode(p)!=XML_ERROR_NONE && XML_ErrorString(XML_GetErrorCode(p))!=NULL,"error diagnostics absent");
        rejected++; checks++; XML_ParserFree(p);
    }
    const char *dtd="<!DOCTYPE root [<!ENTITY known 'payload'>]><root>&known;</root>";
    XML_Parser p=XML_ParserCreate(NULL); State s={0}; require(p!=NULL,"DTD parser creation");
    XML_SetUserData(p,&s); XML_SetCharacterDataHandler(p,chars);
    require(XML_Parse(p,dtd,(int)strlen(dtd),XML_TRUE)==XML_STATUS_OK,"internal entity parse");
    require(!strcmp(s.text,"payload"),"internal entity output"); checks++; XML_ParserFree(p);
    XML_Expat_Version v=XML_ExpatVersionInfo();
    printf("{\"version\":\"%d.%d.%d\",\"checks\":%d,\"invalid_inputs_rejected\":%d}\n",v.major,v.minor,v.micro,checks,rejected);
    return 0;
}
