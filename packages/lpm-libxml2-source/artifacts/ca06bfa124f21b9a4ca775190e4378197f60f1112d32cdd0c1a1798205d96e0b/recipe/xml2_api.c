#include <libxml/parser.h>
#include <libxml/tree.h>
#include <libxml/xpath.h>
#include <libxml/xmlreader.h>
#include <libxml/xmlschemas.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void require(int test,const char *message) { if(!test) { fprintf(stderr,"%s\n",message); exit(1); } }
static xmlDocPtr parse(const char *text) { return xmlReadMemory(text,(int)strlen(text),"local.xml",NULL,XML_PARSE_NONET|XML_PARSE_NOBLANKS|XML_PARSE_NOERROR|XML_PARSE_NOWARNING); }
int main(void) {
    int checks=0,rejected=0;
    const char *text="<root><n id='a'>3</n><n id='b'>4</n><word>caf\xc3\xa9</word></root>";
    xmlDocPtr document=parse(text); require(document!=NULL,"parse"); checks++;
    require(xmlStrEqual(xmlDocGetRootElement(document)->name,BAD_CAST "root"),"root element"); checks++;
    xmlXPathContextPtr context=xmlXPathNewContext(document); require(context!=NULL,"XPath context");
    xmlXPathObjectPtr value=xmlXPathEvalExpression(BAD_CAST "sum(/root/n)",context);
    require(value!=NULL && value->type==XPATH_NUMBER && value->floatval==7.0,"known XPath sum"); checks++; xmlXPathFreeObject(value);
    value=xmlXPathEvalExpression(BAD_CAST "/root/n[@id='b']",context);
    require(value!=NULL && value->nodesetval!=NULL && value->nodesetval->nodeNr==1,"XPath selection"); checks++;
    xmlChar *content=xmlNodeGetContent(value->nodesetval->nodeTab[0]); require(xmlStrEqual(content,BAD_CAST "4"),"node value"); checks++;
    xmlFree(content); xmlXPathFreeObject(value); xmlXPathFreeContext(context);
    xmlChar *serialized=NULL; int size=0; xmlDocDumpFormatMemoryEnc(document,&serialized,&size,"UTF-8",1);
    require(serialized!=NULL && size>0,"serialization"); checks++;
    xmlDocPtr roundtrip=xmlReadMemory((char *)serialized,size,"roundtrip.xml",NULL,XML_PARSE_NONET|XML_PARSE_NOBLANKS);
    require(roundtrip!=NULL,"serialized parse"); checks++; xmlFree(serialized); xmlFreeDoc(roundtrip);
    xmlParserCtxtPtr push=xmlCreatePushParserCtxt(NULL,NULL,NULL,0,"push.xml"); require(push!=NULL,"push parser");
    for(size_t i=0;i<strlen(text);i++) require(xmlParseChunk(push,text+i,1,0)==0,"incremental byte parse");
    require(xmlParseChunk(push,NULL,0,1)==0 && push->wellFormed && push->myDoc!=NULL,"incremental completion"); checks++;
    xmlFreeDoc(push->myDoc); push->myDoc=NULL; xmlFreeParserCtxt(push);
    xmlTextReaderPtr reader=xmlReaderForMemory(text,(int)strlen(text),"reader.xml",NULL,XML_PARSE_NONET); require(reader!=NULL,"reader");
    int elements=0,rc;
    while((rc=xmlTextReaderRead(reader))==1) if(xmlTextReaderNodeType(reader)==XML_READER_TYPE_ELEMENT) elements++;
    require(rc==0 && elements==4,"reader element count"); checks++; xmlFreeTextReader(reader);
    const char *bad[]={"<root>","<root></other>","<root a='1' a='2'/>"};
    for(int i=0;i<3;i++) { xmlDocPtr d=parse(bad[i]); require(d==NULL,"bad XML accepted"); rejected++; checks++; }
    const char *xsd="<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'><xs:element name='n' type='xs:integer'/></xs:schema>";
    xmlSchemaParserCtxtPtr sp=xmlSchemaNewMemParserCtxt(xsd,(int)strlen(xsd)); require(sp!=NULL,"schema parser");
    xmlSchemaPtr schema=xmlSchemaParse(sp); require(schema!=NULL,"schema compile"); checks++;
    xmlSchemaValidCtxtPtr valid=xmlSchemaNewValidCtxt(schema); require(valid!=NULL,"schema context");
    xmlDocPtr good=parse("<n>42</n>"),wrong=parse("<n>not-an-integer</n>"); require(good && wrong,"schema documents");
    require(xmlSchemaValidateDoc(valid,good)==0,"valid schema rejected"); checks++;
    require(xmlSchemaValidateDoc(valid,wrong)>0,"invalid schema accepted"); checks++;
    xmlFreeDoc(good); xmlFreeDoc(wrong); xmlSchemaFreeValidCtxt(valid); xmlSchemaFree(schema); xmlSchemaFreeParserCtxt(sp); xmlFreeDoc(document);
    printf("{\"version\":\"%s\",\"checks\":%d,\"invalid_inputs_rejected\":%d}\n",LIBXML_DOTTED_VERSION,checks,rejected);
    xmlCleanupParser(); return 0;
}
