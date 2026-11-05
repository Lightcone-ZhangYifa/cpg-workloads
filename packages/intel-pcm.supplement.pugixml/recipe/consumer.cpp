#include <pugixml.hpp>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>

#if PUGIXML_VERSION != 1150
#error Incorrect pinned pugixml version
#endif
#if defined(PUGIXML_WCHAR_MODE) || defined(PUGIXML_NO_XPATH) || defined(PUGIXML_NO_STL) || defined(PUGIXML_NO_EXCEPTIONS)
#error The qualified standard UTF-8/XPath/STL/exception profile is required
#endif

static void require(bool result, const char* description) {
    if (!result) { std::cerr << "FAIL: " << description << '\n'; std::exit(1); }
}
static void self_test() {
    const char* xml = "<catalog><item id='a' price='10.5' available='false'>alpha</item><item id='b' price='21' available='true'>beta</item></catalog>";
    pugi::xml_document doc;
    require(bool(doc.load_string(xml)), "parse well-formed XML");
    require(doc.child("catalog").first_child().attribute("price").as_double()==10.5 &&
            std::string(doc.child("catalog").first_child().child_value())=="alpha", "DOM attributes and text");
    pugi::xpath_node_set selected=doc.select_nodes("/catalog/item[@available='true']");
    require(selected.size()==1 && std::string(selected[0].node().attribute("id").value())=="b", "XPath node-set predicate");
    require(pugi::xpath_query("sum(/catalog/item/@price)").evaluate_number(doc)==31.5 &&
            pugi::xpath_query("count(/catalog/item)=2").evaluate_boolean(doc), "XPath numeric and boolean aggregation");
    pugi::xpath_variable_set variables;
    require(variables.set("minimum",15.0), "XPath numeric variable creation");
    pugi::xpath_query variable_query("/catalog/item[@price > $minimum]",&variables);
    require(variable_query.evaluate_node_set(doc).size()==1 &&
            std::string(variable_query.evaluate_node(doc).node().attribute("id").value())=="b", "XPath bound variable");
    pugi::xml_node catalog=doc.child("catalog");
    pugi::xml_node added=catalog.append_child("item");
    require(added.append_attribute("id").set_value("c") && added.append_attribute("price").set_value(3) &&
            added.text().set("<&\" sample") && catalog.remove_child(catalog.first_child()), "DOM insertion/removal");
    require(doc.select_nodes("/catalog/item").size()==2 &&
            std::string(catalog.first_child().attribute("id").value())=="b", "DOM mutation outcome");
    std::ostringstream serialized;
    doc.save(serialized,"",pugi::format_raw,pugi::encoding_utf8);
    pugi::xml_document roundtrip;
    require(bool(roundtrip.load_string(serialized.str().c_str())) &&
            std::string(roundtrip.child("catalog").last_child().child_value())=="<&\" sample" &&
            serialized.str().find("&lt;&amp;")!=std::string::npos, "escaped serialization round trip");
    const std::string utf8="\xCF\x80\xE4\xB8\xAD\xE6\x96\x87";
    require(pugi::as_utf8(pugi::as_wide(utf8))==utf8 && pugi::as_wide(utf8)==L"\u03C0\u4E2D\u6587", "UTF-8/wide conversion");
    pugi::xml_document copy; copy.reset(doc);
    require(copy.child("catalog").first_child().attribute("id").set_value("changed") &&
            std::string(doc.child("catalog").first_child().attribute("id").value())=="b", "independent document copy");

    struct invalid_xml { const char* input; pugi::xml_parse_status status; } invalid[] = {
        {"<root><child></root>",pugi::status_end_element_mismatch},
        {"<root attr='unterminated></root>",pugi::status_bad_attribute},
        {"<root><!-- unterminated",pugi::status_bad_comment}
    };
    for (const invalid_xml& value: invalid) {
        pugi::xml_document broken;
        pugi::xml_parse_result result=broken.load_string(value.input);
        require(!result && result.status==value.status, "malformed XML rejected with expected status");
    }
    unsigned rejected_xpath=0;
    for (const char* query: {"/catalog/item[","cpg_unknown_function()"}) {
        try { pugi::xpath_query bad(query); }
        catch (const pugi::xpath_exception& error) {
            require(error.what()[0]!=0 && !error.result(), "XPath rejection includes diagnostic");
            ++rejected_xpath;
        }
    }
    require(rejected_xpath==2,"both invalid XPath expressions rejected");
    std::cout << "{\"status\":\"passed\",\"positive_cases\":8,\"malformed_xml_rejected\":3,\"invalid_xpath_rejected\":2,\"header_version\":1150}\n";
}
int main(int argc,char** argv) {
    if (argc!=2 || (std::strcmp(argv[1],"--info") && std::strcmp(argv[1],"--self-test"))) {
        std::cerr << "usage: pugixml-cpg-probe --info|--self-test\n"; return 2;
    }
    if (!std::strcmp(argv[1],"--info"))
        std::cout << "{\"library_version\":\"1.15\",\"header_version\":1150,\"xpath\":true,\"stl\":true,\"exceptions\":true,\"encoding\":\"char-UTF8\"}\n";
    else self_test();
    return 0;
}
