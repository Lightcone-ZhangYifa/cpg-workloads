#include <shaderc/shaderc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct counts { int resolve, release; };
static shaderc_include_result *resolve(void *user, const char *requested, int type,
                                     const char *requesting, size_t depth) {
    (void)type; (void)requesting; (void)depth;
    struct counts *c = user; c->resolve++;
    shaderc_include_result *r = calloc(1, sizeof(*r));
    if (strcmp(requested, "constants.glsl") == 0) {
        r->source_name = "constants.glsl";
        r->source_name_length = strlen(r->source_name);
        r->content = "const float scale = 2.0;\n";
    } else {
        r->source_name = "";
        r->content = "CPG include resolver: unknown include";
    }
    r->content_length = strlen(r->content);
    return r;
}
static void release(void *user, shaderc_include_result *r) {
    ((struct counts*)user)->release++;
    free(r);
}
static void require(int ok, const char *msg) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", msg); exit(1); }
}
int main(int argc, char **argv) {
    require(argc == 2, "output file required");
    shaderc_compiler_t compiler = shaderc_compiler_initialize();
    shaderc_compile_options_t options = shaderc_compile_options_initialize();
    require(compiler && options, "initialize");
    struct counts c = {0, 0};
    shaderc_compile_options_set_include_callbacks(options, resolve, release, &c);
    shaderc_compile_options_set_target_env(options, shaderc_target_env_vulkan,
                                          shaderc_env_version_vulkan_1_1);
    const char *source = "#version 450\n#extension GL_GOOGLE_include_directive : require\n"
       "#include \"constants.glsl\"\nlayout(location=0) in vec4 pos;\n"
       "void main() { gl_Position = pos * scale; }\n";
    shaderc_compilation_result_t result = shaderc_compile_into_spv(compiler, source,
       strlen(source), shaderc_vertex_shader, "include.vert", "main", options);
    require(result != NULL, "result allocation");
    if (shaderc_result_get_compilation_status(result) != shaderc_compilation_status_success)
        fprintf(stderr, "%s", shaderc_result_get_error_message(result));
    require(shaderc_result_get_compilation_status(result) == shaderc_compilation_status_success,
            "include shader compiles");
    require(c.resolve == 1 && c.release == 1, "include callback ownership");
    require(shaderc_result_get_num_errors(result) == 0, "zero errors");
    size_t size = shaderc_result_get_length(result);
    require(size > 20 && size % 4 == 0, "SPIR-V byte length");
    FILE *file = fopen(argv[1], "wb"); require(file != NULL, "open output");
    require(fwrite(shaderc_result_get_bytes(result), 1, size, file) == size, "write SPIR-V");
    require(fclose(file) == 0, "close output");
    shaderc_result_release(result);
    const char *invalid = "#version 450\nvoid main(){gl_Position = undefined_identifier;}\n";
    result = shaderc_compile_into_spv(compiler, invalid, strlen(invalid),
                shaderc_vertex_shader, "bad.vert", "main", options);
    require(result != NULL, "negative result allocation");
    require(shaderc_result_get_compilation_status(result) == shaderc_compilation_status_compilation_error,
            "invalid source rejected");
    require(shaderc_result_get_num_errors(result) > 0, "diagnostic count");
    require(strstr(shaderc_result_get_error_message(result), "undefined_identifier") != NULL,
            "identifier preserved in diagnostic");
    printf("syntax diagnostic: %s", shaderc_result_get_error_message(result));
    shaderc_result_release(result);
    const char *missing = "#version 450\n#extension GL_GOOGLE_include_directive : require\n"
                          "#include \"missing.glsl\"\nvoid main(){}\n";
    result = shaderc_compile_into_spv(compiler, missing, strlen(missing),
                shaderc_vertex_shader, "missing.vert", "main", options);
    require(result != NULL, "include negative result allocation");
    require(shaderc_result_get_compilation_status(result) != shaderc_compilation_status_success,
            "missing include rejected");
    require(strstr(shaderc_result_get_error_message(result), "unknown include") != NULL,
            "resolver diagnostic propagated");
    require(c.resolve >= 2 && c.release == c.resolve, "negative include release");
    shaderc_result_release(result);
    shaderc_compile_options_release(options);
    shaderc_compiler_release(compiler);
    puts("SHADERC_C_API_OK");
    return 0;
}
