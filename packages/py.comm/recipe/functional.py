from comm import create_comm,get_comm_manager
manager=get_comm_manager()
comm=create_comm(target_name='cpg-round-check')
assert manager.get_comm(comm.comm_id) is comm
assert comm._closed is False
comm.send({'answer':42})
comm.close()
assert comm._closed is True
assert comm.comm_id not in manager.comms
print('CPG_FUNCTIONAL_OK:comm:open-send-close')
