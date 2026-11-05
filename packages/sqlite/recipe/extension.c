/* Minimal real loadable extension; it uses SQLite's extension API table. */
#include <sqlite3ext.h>
SQLITE_EXTENSION_INIT1

static void add_one(sqlite3_context *context, int count, sqlite3_value **values) {
    (void)count;
    sqlite3_result_int64(context, sqlite3_value_int64(values[0]) + 1);
}

int sqlite3_extension_init(sqlite3 *database, char **error, const sqlite3_api_routines *api) {
    (void)error;
    SQLITE_EXTENSION_INIT2(api);
    return sqlite3_create_function(database, "cpg_add_one", 1,
                                   SQLITE_UTF8 | SQLITE_DETERMINISTIC, 0, add_one, 0, 0);
}
