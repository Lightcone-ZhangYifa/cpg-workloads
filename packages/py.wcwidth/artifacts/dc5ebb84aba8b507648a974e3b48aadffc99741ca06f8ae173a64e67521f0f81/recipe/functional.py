from wcwidth import wcwidth,wcswidth
assert wcwidth('界')==2 and wcwidth('x')==1
assert wcwidth('\u0301')==0
assert wcswidth('x界')==3
print('CPG_FUNCTIONAL_OK:wcwidth:unicode-display-width')
