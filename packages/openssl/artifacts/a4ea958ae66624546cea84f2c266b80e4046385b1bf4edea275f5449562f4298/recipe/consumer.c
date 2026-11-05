#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/err.h>
#include <openssl/ssl.h>
#include <stdio.h>
#include <string.h>

#define REQUIRE(condition, message) do { if (!(condition)) { \
    fprintf(stderr, "%s\n", message); ERR_print_errors_fp(stderr); return 1; } } while (0)

static int equals_hex(const unsigned char *data, size_t bytes, const char *expected) {
    static const char digits[] = "0123456789abcdef";
    if (strlen(expected) != bytes * 2) return 0;
    for (size_t i = 0; i < bytes; ++i)
        if (expected[2*i] != digits[data[i] >> 4] || expected[2*i+1] != digits[data[i] & 15]) return 0;
    return 1;
}

int main(void) {
    unsigned checks = 0, rejected = 0;
    unsigned char buffer[256], decrypted[256], zero[16] = {0}, iv[12] = {0}, tag[16];
    unsigned length = 0; size_t output_length = 0; int n = 0, m = 0;
    REQUIRE(OPENSSL_version_major() == 4 && OPENSSL_version_minor() == 0 && OPENSSL_version_patch() == 3,
            "linked runtime version mismatch");
    REQUIRE(EVP_Digest("abc", 3, buffer, &length, EVP_sha256(), NULL) == 1 && length == 32,
            "SHA-256 API failed");
    REQUIRE(equals_hex(buffer, length, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"), "SHA-256 known answer"); ++checks;
    const unsigned char *message = (const unsigned char *)"The quick brown fox jumps over the lazy dog";
    REQUIRE(EVP_Q_mac(NULL, "HMAC", NULL, "SHA256", NULL, "key", 3, message, strlen((const char *)message),
                      buffer, sizeof(buffer), &output_length) != NULL, "HMAC API failed");
    REQUIRE(equals_hex(buffer, output_length, "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"), "HMAC known answer"); ++checks;
    EVP_CIPHER_CTX *cipher = EVP_CIPHER_CTX_new(); REQUIRE(cipher != NULL, "cipher context");
    REQUIRE(EVP_EncryptInit_ex2(cipher, EVP_aes_128_ecb(), zero, NULL, NULL) == 1 &&
            EVP_CIPHER_CTX_set_padding(cipher, 0) == 1 &&
            EVP_EncryptUpdate(cipher, buffer, &n, zero, sizeof(zero)) == 1 &&
            EVP_EncryptFinal_ex(cipher, buffer+n, &m) == 1, "AES ECB encrypt");
    REQUIRE(n+m == 16 && equals_hex(buffer, 16, "66e94bd4ef8a2c3b884cfa59ca342b2e"), "AES ECB known answer"); ++checks;
    REQUIRE(EVP_DecryptInit_ex2(cipher, EVP_aes_128_ecb(), zero, NULL, NULL) == 1 &&
            EVP_CIPHER_CTX_set_padding(cipher, 0) == 1 &&
            EVP_DecryptUpdate(cipher, decrypted, &n, buffer, 16) == 1 &&
            EVP_DecryptFinal_ex(cipher, decrypted+n, &m) == 1 && n+m == 16 &&
            memcmp(decrypted, zero, 16) == 0, "AES ECB round trip"); ++checks;
    REQUIRE(EVP_EncryptInit_ex2(cipher, EVP_aes_128_gcm(), zero, iv, NULL) == 1 &&
            EVP_EncryptUpdate(cipher, buffer, &n, zero, 16) == 1 &&
            EVP_EncryptFinal_ex(cipher, buffer+n, &m) == 1 &&
            EVP_CIPHER_CTX_ctrl(cipher, EVP_CTRL_GCM_GET_TAG, 16, tag) == 1, "AES GCM encrypt");
    REQUIRE(n+m == 16 && equals_hex(buffer, 16, "0388dace60b6a392f328c2b971b2fe78") &&
            equals_hex(tag, 16, "ab6e47d42cec13bdf53a67b21257bddf"), "AES GCM known answer"); ++checks;
    REQUIRE(EVP_DecryptInit_ex2(cipher, EVP_aes_128_gcm(), zero, iv, NULL) == 1 &&
            EVP_DecryptUpdate(cipher, decrypted, &n, buffer, 16) == 1 &&
            EVP_CIPHER_CTX_ctrl(cipher, EVP_CTRL_GCM_SET_TAG, 16, tag) == 1 &&
            EVP_DecryptFinal_ex(cipher, decrypted+n, &m) == 1 && memcmp(decrypted, zero, 16) == 0,
            "AES GCM authenticated decrypt"); ++checks;
    tag[0] ^= 1;
    REQUIRE(EVP_DecryptInit_ex2(cipher, EVP_aes_128_gcm(), zero, iv, NULL) == 1 &&
            EVP_DecryptUpdate(cipher, decrypted, &n, buffer, 16) == 1 &&
            EVP_CIPHER_CTX_ctrl(cipher, EVP_CTRL_GCM_SET_TAG, 16, tag) == 1 &&
            EVP_DecryptFinal_ex(cipher, decrypted+n, &m) == 0, "tampered GCM tag must be rejected"); ++rejected;
    EVP_CIPHER_CTX_free(cipher);
    REQUIRE(EVP_EncodeBlock(buffer, (const unsigned char *)"abc", 3) == 4 && memcmp(buffer, "YWJj", 4) == 0, "base64 encode"); ++checks;
    REQUIRE(EVP_DecodeBlock(decrypted, buffer, 4) == 3 && memcmp(decrypted, "abc", 3) == 0, "base64 decode"); ++checks;
    unsigned char seed[32] = {0}, signature[64]; size_t signature_length = sizeof(signature);
    EVP_PKEY *key = EVP_PKEY_new_raw_private_key_ex(NULL, "ED25519", NULL, seed, sizeof(seed));
    EVP_MD_CTX *digest = EVP_MD_CTX_new(); REQUIRE(key != NULL && digest != NULL, "Ed25519 context");
    REQUIRE(EVP_DigestSignInit(digest, NULL, NULL, NULL, key) == 1 &&
            EVP_DigestSign(digest, signature, &signature_length, (const unsigned char *)"abc", 3) == 1 &&
            signature_length == 64 && EVP_DigestVerifyInit(digest, NULL, NULL, NULL, key) == 1 &&
            EVP_DigestVerify(digest, signature, signature_length, (const unsigned char *)"abc", 3) == 1,
            "Ed25519 sign/verify"); ++checks;
    REQUIRE(EVP_DigestVerify(digest, signature, signature_length, (const unsigned char *)"abd", 3) == 0,
            "changed signed message must be rejected"); ++rejected;
    EVP_MD_CTX_free(digest); EVP_PKEY_free(key);
    SSL_CTX *tls = SSL_CTX_new(TLS_method()); REQUIRE(tls != NULL, "TLS API context");
    REQUIRE(SSL_CTX_set_min_proto_version(tls, TLS1_3_VERSION) == 1 &&
            SSL_CTX_get_min_proto_version(tls) == TLS1_3_VERSION, "TLS version configuration API"); ++checks;
    SSL_CTX_free(tls);
    EVP_MD *unknown = EVP_MD_fetch(NULL, "CPG-NONEXISTENT-DIGEST", NULL);
    REQUIRE(unknown == NULL, "unknown algorithm must be rejected"); ++rejected;
    ERR_clear_error();
    printf("{\"checks\":%u,\"invalid_inputs_rejected\":%u,\"version\":\"4.0.3\",\"status\":\"passed\"}\n", checks, rejected);
    return 0;
}
