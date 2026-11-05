import execnet,sys
assert execnet.__version__ == '2.1.2'
gw = execnet.makegateway('popen//python=' + sys.executable)
try:
    ch = gw.remote_exec('channel.send({"answer": 6 * 7})')
    assert ch.receive() == {"answer": 42}
finally:
    gw.exit()
print('CPG_FUNCTIONAL_OK:execnet:popen-channel')
