#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <yyjson.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "failed: %s at %d\n", #x, __LINE__); return 2; } } while (0)
int main(int argc, char **argv) {
    const char input[] = "{\"name\":\"compiler-playground\",\"n\":42,\"values\":[true,null,-7,1.5]}";
    REQUIRE(argc == 2);
    yyjson_doc *doc = yyjson_read(input, sizeof(input)-1, 0);
    REQUIRE(doc);
    yyjson_val *root = yyjson_doc_get_root(doc);
    REQUIRE(yyjson_is_obj(root) && yyjson_obj_size(root) == 3);
    REQUIRE(strcmp(yyjson_get_str(yyjson_obj_get(root,"name")),"compiler-playground") == 0);
    REQUIRE(yyjson_get_int(yyjson_obj_get(root,"n")) == 42);
    yyjson_val *array = yyjson_obj_get(root,"values");
    REQUIRE(yyjson_is_arr(array) && yyjson_arr_size(array) == 4);
    REQUIRE(yyjson_is_true(yyjson_arr_get(array,0)) && yyjson_is_null(yyjson_arr_get(array,1)));
    REQUIRE(yyjson_get_sint(yyjson_arr_get(array,2)) == -7 && yyjson_get_real(yyjson_arr_get(array,3)) == 1.5);
    size_t length = 0;
    char *serialized = yyjson_write(doc,0,&length);
    REQUIRE(serialized && length > 0);
    FILE *file = fopen(argv[1],"wb");
    REQUIRE(file && fwrite(serialized,1,length,file)==length && fclose(file)==0);
    yyjson_doc *copy = yyjson_read(serialized,length,0);
    REQUIRE(copy && yyjson_obj_size(yyjson_doc_get_root(copy))==3);
    REQUIRE(yyjson_read("{\"x\":}",6,0) == NULL);
    REQUIRE(yyjson_read("[1,2",4,0) == NULL);
    printf("{\"status\":\"passed\",\"library\":\"yyjson\",\"json_bytes\":%zu,\"negative_cases\":2}\n",length);
    yyjson_doc_free(copy);free(serialized);yyjson_doc_free(doc);
    return 0;
}
