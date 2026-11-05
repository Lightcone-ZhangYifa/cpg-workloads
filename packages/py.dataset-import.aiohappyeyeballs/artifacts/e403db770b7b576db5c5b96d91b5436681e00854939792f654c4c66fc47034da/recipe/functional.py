import socket,aiohappyeyeballs
ipv4=(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',80))
ipv6=(socket.AF_INET6,socket.SOCK_STREAM,6,'',('::1',80,0,0))
addrs=[ipv4,ipv4,ipv6]
aiohappyeyeballs.pop_addr_infos_interleave(addrs,interleave=1)
assert addrs==[ipv4]
assert aiohappyeyeballs.addr_to_addr_infos(('::1',80))[0][0]==socket.AF_INET6
print('CPG_FUNCTIONAL_OK:aiohappyeyeballs:family-interleave')
