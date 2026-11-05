#define _GNU_SOURCE
#define SQLITE_ENABLE_SESSION 1
#define SQLITE_ENABLE_PREUPDATE_HOOK 1
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <sqlite3.h>

#define REQUIRE(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

static int execute(sqlite3 *db, const char *sql) {
    char *error = 0;
    int code = sqlite3_exec(db, sql, 0, 0, &error);
    if (code != SQLITE_OK) fprintf(stderr, "SQLite code %d: %s\n", code, error ? error : "unknown");
    sqlite3_free(error);
    return code;
}

static int scalar(sqlite3 *db, const char *sql, sqlite3_int64 expected) {
    sqlite3_stmt *statement = 0;
    int good = sqlite3_prepare_v2(db, sql, -1, &statement, 0) == SQLITE_OK;
    good = good && sqlite3_step(statement) == SQLITE_ROW && sqlite3_column_int64(statement, 0) == expected;
    good = good && sqlite3_step(statement) == SQLITE_DONE;
    return sqlite3_finalize(statement) == SQLITE_OK && good;
}

int main(int argc, char **argv) {
    sqlite3 *db = 0, *other = 0, *backup = 0;
    sqlite3_session *session = 0;
    sqlite3_stmt *insert = 0;
    Dl_info library;
    REQUIRE(argc == 2 && sqlite3_libversion_number() == 3054001);
    REQUIRE(strstr(sqlite3_sourceid(), "555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76") != 0);
    REQUIRE(dladdr((void *)sqlite3_libversion_number, &library) != 0);
    REQUIRE(sqlite3_open(argv[1], &db) == SQLITE_OK);
    REQUIRE(execute(db, "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;"
        "CREATE TABLE records(id INTEGER PRIMARY KEY, payload BLOB NOT NULL);"
        "CREATE TABLE child(id INTEGER REFERENCES records(id));") == SQLITE_OK);
    REQUIRE(sqlite3_prepare_v2(db, "INSERT INTO records VALUES(?1,?2)", -1, &insert, 0) == SQLITE_OK);
    const unsigned char blob[] = {0, 1, 2, 255, 0, 37};
    REQUIRE(sqlite3_bind_int(insert, 1, 1) == SQLITE_OK);
    REQUIRE(sqlite3_bind_blob(insert, 2, blob, sizeof(blob), SQLITE_STATIC) == SQLITE_OK);
    REQUIRE(sqlite3_step(insert) == SQLITE_DONE && sqlite3_finalize(insert) == SQLITE_OK);
    REQUIRE(execute(db, "INSERT INTO child VALUES(1)") == SQLITE_OK);
    REQUIRE(execute(db, "INSERT INTO child VALUES(99)") == SQLITE_CONSTRAINT);
    REQUIRE(scalar(db, "SELECT length(payload) FROM records WHERE id=1", 6));
    REQUIRE(execute(db, "BEGIN; INSERT INTO records VALUES(2,x'1122'); ROLLBACK;") == SQLITE_OK);
    REQUIRE(scalar(db, "SELECT count(*) FROM records", 1));
    REQUIRE(scalar(db, "SELECT json_extract('{\"answer\":42}', '$.answer')", 42));
    REQUIRE(execute(db, "CREATE VIRTUAL TABLE documents USING fts5(body);"
        "INSERT INTO documents VALUES('compiler optimization'),('relational storage');") == SQLITE_OK);
    REQUIRE(scalar(db, "SELECT count(*) FROM documents WHERE documents MATCH 'compiler'", 1));
    REQUIRE(execute(db, "CREATE VIRTUAL TABLE bounds USING rtree(id,x0,x1); INSERT INTO bounds VALUES(1,2,4);") == SQLITE_OK);
    REQUIRE(scalar(db, "SELECT count(*) FROM bounds WHERE x0<=3 AND x1>=3", 1));
    REQUIRE(sqlite3session_create(db, "main", &session) == SQLITE_OK);
    REQUIRE(sqlite3session_attach(session, "records") == SQLITE_OK);
    REQUIRE(execute(db, "INSERT INTO records VALUES(2,x'1122')") == SQLITE_OK);
    void *changeset = 0;
    int change_bytes = 0;
    REQUIRE(sqlite3session_changeset(session, &change_bytes, &changeset) == SQLITE_OK && change_bytes > 0);
    sqlite3_free(changeset);
    sqlite3session_delete(session);
    REQUIRE(sqlite3_open(argv[1], &other) == SQLITE_OK);
    REQUIRE(execute(db, "BEGIN IMMEDIATE; INSERT INTO records VALUES(3,x'33');") == SQLITE_OK);
    REQUIRE(scalar(other, "SELECT count(*) FROM records", 2));
    REQUIRE(execute(other, "INSERT INTO records VALUES(4,x'44')") == SQLITE_BUSY);
    REQUIRE(execute(db, "COMMIT;") == SQLITE_OK);
    REQUIRE(execute(other, "INSERT INTO records VALUES(4,x'44')") == SQLITE_OK);
    REQUIRE(scalar(db, "SELECT count(*) FROM records", 4));
    REQUIRE(sqlite3_open(":memory:", &backup) == SQLITE_OK);
    sqlite3_backup *copy = sqlite3_backup_init(backup, "main", db, "main");
    REQUIRE(copy != 0 && sqlite3_backup_step(copy, -1) == SQLITE_DONE && sqlite3_backup_finish(copy) == SQLITE_OK);
    REQUIRE(scalar(backup, "SELECT count(*) FROM records", 4));
    REQUIRE(scalar(db, "SELECT count(*) FROM pragma_integrity_check WHERE integrity_check='ok'", 1));
    REQUIRE(sqlite3_close(backup) == SQLITE_OK && sqlite3_close(other) == SQLITE_OK && sqlite3_close(db) == SQLITE_OK);
    printf("version=3.54.1\nsource_id=%s\nwal_writer_conflict=passed\nbackup=passed\nfts5_rtree_json_session=passed\nlibrary=%s\n", sqlite3_sourceid(), library.dli_fname);
    return 0;
}
