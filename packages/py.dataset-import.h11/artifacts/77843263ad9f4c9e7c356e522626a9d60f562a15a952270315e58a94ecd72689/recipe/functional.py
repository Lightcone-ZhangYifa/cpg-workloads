import h11
client=h11.Connection(h11.CLIENT)
wire=client.send(h11.Request(method='GET',target='/cpg',headers=[('Host','localhost')]))
wire+=client.send(h11.EndOfMessage())
server=h11.Connection(h11.SERVER)
server.receive_data(wire)
req=server.next_event()
assert isinstance(req,h11.Request) and req.target==b'/cpg'
assert isinstance(server.next_event(),h11.EndOfMessage)
print('CPG_FUNCTIONAL_OK:h11:http11-request-parse')
