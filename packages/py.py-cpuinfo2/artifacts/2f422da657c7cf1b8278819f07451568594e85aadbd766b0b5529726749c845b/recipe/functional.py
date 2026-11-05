from cpuinfo import get_cpu_info
r=get_cpu_info()
assert isinstance(r,dict) and r.get('arch') and r.get('bits') in (32,64)
print('CPG_FUNCTIONAL_OK:py-cpuinfo2:host-cpu-query')
