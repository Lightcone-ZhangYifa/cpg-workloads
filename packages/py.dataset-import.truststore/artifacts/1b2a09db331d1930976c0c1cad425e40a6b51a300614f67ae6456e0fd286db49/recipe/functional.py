import ssl,truststore
ctx=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
assert ctx.verify_mode==ssl.CERT_REQUIRED
ctx.set_alpn_protocols(['h2','http/1.1'])
assert isinstance(ctx,ssl.SSLContext)
print('CPG_FUNCTIONAL_OK:truststore:sslcontext-creation')
