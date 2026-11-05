from termcolor import colored
value=colored('test','green',force_color=True)
assert value.startswith('\x1b[') and value.endswith('\x1b[0m')
assert 'test' in value
print('CPG_FUNCTIONAL_OK:termcolor:ansi-render')
